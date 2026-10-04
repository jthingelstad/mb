"""Local transactional cursors and write receipts; never stores authentication."""

import hashlib
import json
import os
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path


class StateConflict(ValueError):
    pass


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
        if not self.path.exists():
            return None, 0
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as db:
            tables = db.execute("SELECT name FROM sqlite_master WHERE name='cursors'").fetchone()
            row = (
                db.execute("SELECT value,revision FROM cursors WHERE scope=?", (scope,)).fetchone()
                if tables
                else None
            )
        return (row[0], row[1]) if row else (None, 0)

    def acknowledge(self, scope: str, value: str, expected_revision: int) -> dict:
        with self.connection() as db:
            row = db.execute(
                "SELECT value,revision FROM cursors WHERE scope=?", (scope,)
            ).fetchone()
            current, revision = row if row else (None, 0)
            if revision != expected_revision:
                if current == value and revision == expected_revision + 1:
                    return {"checkpoint": value, "revision": revision, "already_applied": True}
                raise StateConflict("Checkpoint changed; read a fresh window before acknowledging")
            if current is not None and int(value) < int(current):
                raise StateConflict("Checkpoint cannot move backwards")
            db.execute(
                "INSERT OR REPLACE INTO cursors VALUES (?,?,?)", (scope, value, revision + 1)
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
            db.execute(
                "UPDATE operations SET status=?,result=? WHERE scope=? AND id=?",
                (
                    "unknown" if result.get("outcome") == "unknown" else "complete",
                    json.dumps(result),
                    scope,
                    operation_id,
                ),
            )
