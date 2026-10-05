"""Local transactional cursors and write receipts; never stores authentication."""

import hashlib
import json
import os
import re
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path


class StateConflict(ValueError):
    pass


class CheckpointReviewRequired(StateConflict):
    pass


NATIVE_CURSOR = "native-order-v1"
LEGACY_CURSOR = "legacy-review-required"


class StateStore:
    def __init__(self, path: Path):
        self.path = path.absolute()

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        self.path.chmod(0o600)
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        try:
            db.execute("PRAGMA busy_timeout=5000")
            db.execute(
                "CREATE TABLE IF NOT EXISTS cursors (scope TEXT PRIMARY KEY, value TEXT, revision INTEGER NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS cursor_provenance (scope TEXT PRIMARY KEY, value TEXT NOT NULL, revision INTEGER NOT NULL, scheme TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS operations (scope TEXT, id TEXT, fingerprint TEXT, status TEXT, result TEXT, PRIMARY KEY(scope,id))"
            )
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def cursor(self, scope: str) -> tuple[str | None, int]:
        record = self.cursor_record(scope)
        return record["value"], record["revision"]

    @staticmethod
    def _cursor_record(db, scope: str) -> dict:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "cursors" not in tables:
            row = (
                db.execute(
                    "SELECT NULL,NULL,value,revision,scheme,NULL,scope FROM cursor_provenance WHERE scope=?",
                    (scope,),
                ).fetchone()
                if "cursor_provenance" in tables
                else None
            )
        elif "cursor_provenance" in tables:
            # One statement reads the anchor, revision and provenance together.
            row = db.execute(
                "SELECT c.value,c.revision,p.value,p.revision,p.scheme,c.scope,p.scope FROM (SELECT ? AS scope) s "
                "LEFT JOIN cursors c ON c.scope=s.scope LEFT JOIN cursor_provenance p ON p.scope=s.scope",
                (scope,),
            ).fetchone()
        else:
            row = db.execute(
                "SELECT value,revision,NULL,NULL,NULL,scope,NULL FROM cursors WHERE scope=?",
                (scope,),
            ).fetchone()
        if row is None or (row[5] is None and row[6] is None):
            return {"value": None, "revision": 0, "scheme": None}
        native = (
            isinstance(row[0], str)
            and re.fullmatch(r"[0-9]{1,20}", row[0]) is not None
            and int(row[0]) > 0
            and row[0] == str(int(row[0]))
            and isinstance(row[1], int)
            and row[1] > 0
            and row[0:2] == row[2:4]
            and row[4] == NATIVE_CURSOR
        )
        return {
            "value": row[0],
            "revision": row[1] if row[1] is not None else 0,
            "scheme": NATIVE_CURSOR if native else LEGACY_CURSOR,
        }

    def cursor_record(self, scope: str) -> dict:
        if not self.path.exists():
            return {"value": None, "revision": 0, "scheme": None}
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as db:
            return self._cursor_record(db, scope)

    def acknowledge(self, scope: str, value: str, expected_revision: int) -> dict:
        """Save a native-order checkpoint from a complete window, with its provenance."""
        if not re.fullmatch(r"[0-9]{1,20}", value) or int(value) <= 0 or value != str(int(value)):
            raise StateConflict("Invalid native checkpoint")
        with self.connection() as db:
            record = self._cursor_record(db, scope)
            current, revision = record["value"], record["revision"]
            if record["scheme"] == LEGACY_CURSOR:
                raise CheckpointReviewRequired(
                    "Checkpoint requires operator review; no automatic migration"
                )
            if revision != expected_revision:
                if current == value and revision == expected_revision + 1:
                    return {"checkpoint": value, "revision": revision, "already_applied": True}
                raise StateConflict("Checkpoint changed; read a fresh window before acknowledging")
            db.execute(
                "INSERT OR REPLACE INTO cursors VALUES (?,?,?)", (scope, value, revision + 1)
            )
            db.execute(
                "INSERT OR REPLACE INTO cursor_provenance VALUES (?,?,?,?)",
                (scope, value, revision + 1, NATIVE_CURSOR),
            )
            return {"checkpoint": value, "revision": revision + 1, "already_applied": False}

    @staticmethod
    def fingerprint(action: str, arguments: dict) -> str:
        payload = json.dumps([action, arguments], sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    def _operation_row(self, scope: str, operation_id: str):
        if not self.path.exists():
            return None
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as db:
            tables = db.execute("SELECT name FROM sqlite_master WHERE name='operations'").fetchone()
            return (
                db.execute(
                    "SELECT fingerprint,result FROM operations WHERE scope=? AND id=?",
                    (scope, operation_id),
                ).fetchone()
                if tables
                else None
            )

    @staticmethod
    def _receipt(row, operation_id: str) -> dict:
        return (
            json.loads(row[1])
            if row[1]
            else {
                "ok": False,
                "error": "write_outcome_unknown",
                "code": 409,
                "outcome": "unknown",
                "operation_id": operation_id,
            }
        )

    def operation(self, scope: str, operation_id: str) -> dict | None:
        row = self._operation_row(scope, operation_id)
        return self._receipt(row, operation_id) if row else None

    def latest_operation(self, scope: str) -> tuple[int, dict] | None:
        """Read the newest claimed receipt in one verified scope without changing state."""
        if not self.path.exists():
            return None
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='operations'").fetchone():
                return None
            row = db.execute(
                "SELECT rowid,id,fingerprint,result FROM operations WHERE scope=? ORDER BY rowid DESC LIMIT 1",
                (scope,),
            ).fetchone()
            return (row[0], self._receipt(row[2:], row[1])) if row else None

    def lookup(self, scope: str, operation_id: str, fingerprint: str) -> dict | None:
        row = self._operation_row(scope, operation_id)
        if row and row[0] != fingerprint:
            raise StateConflict("Operation ID was already used for different arguments")
        return self._receipt(row, operation_id) if row else None

    def claim(self, scope: str, operation_id: str, fingerprint: str) -> dict | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT fingerprint,result FROM operations WHERE scope=? AND id=?",
                (scope, operation_id),
            ).fetchone()
            if row:
                if row[0] != fingerprint:
                    raise StateConflict("Operation ID was already used for different arguments")
                return (
                    json.loads(row[1])
                    if row[1]
                    else {
                        "ok": False,
                        "error": "write_outcome_unknown",
                        "code": 409,
                        "outcome": "unknown",
                        "operation_id": operation_id,
                    }
                )
            pending = db.execute(
                "SELECT id FROM operations WHERE scope=? AND status='pending'", (scope,)
            ).fetchone()
            if pending:
                raise StateConflict(
                    f"Another write is unresolved: {pending[0]}; inspect operation_status before proceeding"
                )
            db.execute(
                "INSERT INTO operations VALUES (?,?,?,'pending',NULL)",
                (scope, operation_id, fingerprint),
            )
        return None

    def finish(self, scope: str, operation_id: str, result: dict) -> None:
        with self.connection() as db:
            row = db.execute(
                "SELECT status,result FROM operations WHERE scope=? AND id=?",
                (scope, operation_id),
            ).fetchone()
            if row and row[0] == "resolved":
                # A human resolution stands; keep the late dispatch result beside it for review.
                resolved = json.loads(row[1])
                resolved["resolution"]["late_receipt"] = result
                db.execute(
                    "UPDATE operations SET result=? WHERE scope=? AND id=?",
                    (json.dumps(resolved), scope, operation_id),
                )
                return
            db.execute(
                "UPDATE operations SET status=?,result=? WHERE scope=? AND id=?",
                (
                    "unknown" if result.get("outcome") == "unknown" else "complete",
                    json.dumps(result),
                    scope,
                    operation_id,
                ),
            )

    def resolve(
        self,
        scope: str,
        operation_id: str,
        outcome: str,
        *,
        resolved_at: str,
        resolved_by: str,
        note: str | None = None,
    ) -> dict | None:
        """Record a human answer for a pending or unknown receipt, keeping what it replaced."""
        if outcome not in {"applied", "not_applied"}:
            raise ValueError("Resolve with applied or not_applied")
        if self._operation_row(scope, operation_id) is None:
            return None
        with self.connection() as db:
            row = db.execute(
                "SELECT status,result FROM operations WHERE scope=? AND id=?",
                (scope, operation_id),
            ).fetchone()
            if row is None:
                return None
            if row[0] not in {"pending", "unknown"}:
                raise StateConflict("Only pending or unknown receipts can be resolved")
            previous = json.loads(row[1]) if row[1] else None
            receipt = {
                "ok": outcome == "applied",
                "operation_id": operation_id,
                "outcome": outcome,
                "data": (previous or {}).get("data", {}),
                "resolution": {
                    "outcome": outcome,
                    "resolved_at": resolved_at,
                    "resolved_by": resolved_by,
                    "note": note,
                    "previous_status": row[0],
                    "previous_receipt": previous,
                },
            }
            if outcome == "not_applied":
                receipt.update(error="write_not_applied", code=409)
            # The resolved status no longer blocks new claims in this scope.
            db.execute(
                "UPDATE operations SET status='resolved',result=? WHERE scope=? AND id=?",
                (json.dumps(receipt), scope, operation_id),
            )
        return receipt
