"""Native-order checkpoint provenance, paging and transactional recovery contracts."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Barrier

import pytest

from mb.services import MicroblogService
from mb.state import (
    LEGACY_CURSOR,
    NATIVE_CURSOR,
    CheckpointReviewRequired,
    StateConflict,
    StateStore,
)
from tests.conftest import write_legacy_cursor
from tests.test_mcp_exercise import service_at


def native_feed(client, values, cap=2):
    """Server cursor positions are opaque; numeric magnitude is deliberately irrelevant."""

    def page(count=20, since_id=None, before_id=None):
        before = values.index(int(before_id)) + 1 if before_id is not None else 0
        since = values.index(int(since_id)) if since_id is not None else len(values)
        return {
            "ok": True,
            "data": {"items": [{"id": i} for i in values[before:since][: min(cap, count)]]},
        }

    client.get_timeline.side_effect = page


def consume(service, count=2, workflow="catchup"):
    seen, cursor = [], None
    for _ in range(20):
        result = service.attention(workflow, count=count, cursor=cursor)
        assert result["ok"], result
        data = result["data"]
        items = [entry.get("item", entry) for entry in data["items"]]
        seen.extend(item["id"] for item in items)
        cursor = data["next_cursor"]
        if cursor is None:
            return seen, data
        assert data["ack_receipt"] is None and not data["coverage_complete"]
    pytest.fail("Bounded fixture did not exhaust")


@pytest.mark.parametrize("ids", [[1, 2, 3, 4, 5], [9, 3, 20, 2, 14], [2**63 + 4, 7, 2**63 + 6]])
def test_native_order_across_capped_pages_and_smaller_new_anchor(tmp_path, ids):
    service, client = service_at(tmp_path)
    native_feed(client, ids)
    seen, data = consume(service)
    assert seen == [str(i) for i in ids]
    assert data["coverage_complete"] and data["checkpoint_status"] == "empty"
    assert not service.state.path.exists()
    receipt = data["ack_receipt"]
    assert service.acknowledge(receipt)["data"]["checkpoint"] == str(ids[0])
    assert service.acknowledge(receipt)["data"]["already_applied"]
    assert service.state.cursor_record(service._scope("catchup"))["scheme"] == NATIVE_CURSOR
    # Numerically smaller but chronologically newer, including a short server page.
    fresh = [1 if 1 not in ids else max(ids) + 1, 99, *ids]
    native_feed(client, fresh, cap=1)
    seen, data = consume(service, count=5)
    assert seen == [str(fresh[0]), "99"]
    assert service.acknowledge(data["ack_receipt"])["data"]["revision"] == 2
    assert service.state.cursor(service._scope("catchup")) == (str(fresh[0]), 2)


def test_native_since_does_not_drop_low_ids(tmp_path):
    service, client = service_at(tmp_path)
    service.identity()
    service.state.acknowledge(service._scope("catchup"), "100", 0)
    native_feed(client, [90, 110, 100, 200], cap=1)
    seen, data = consume(service, count=4)
    assert seen == ["90", "110"]
    assert service.acknowledge(data["ack_receipt"])["data"]["checkpoint"] == "90"


@pytest.mark.parametrize(
    "raw,expected,complete",
    [([90, 110, 100, 50], [90, 110], True), ([90, 80], [90, 80], False), ([], [], False)],
)
def test_inbox_requires_exact_anchor_with_nonmonotonic_ids(tmp_path, raw, expected, complete):
    service, client = service_at(tmp_path)
    service.identity()
    service.state.acknowledge(service._scope("inbox"), "100", 0)
    client.get_mentions.return_value = {"ok": True, "data": {"items": [{"id": i} for i in raw]}}
    seen, data = consume(service, count=1, workflow="inbox")
    assert seen == [str(i) for i in expected]
    assert data["coverage_complete"] is complete
    assert bool(data["ack_receipt"]) is complete
    if complete:
        assert service.acknowledge(data["ack_receipt"])["data"]["checkpoint"] == "90"


def test_exact_timeline_anchor_stops_before_older_history(tmp_path):
    service, client = service_at(tmp_path)
    service.identity()
    service.state.acknowledge(service._scope("catchup"), "100", 0)
    client.get_timeline.side_effect = [
        {"ok": True, "data": {"items": [{"id": 90}, {"id": 110}]}},
        {"ok": True, "data": {"items": [{"id": 80}, {"id": 100}, {"id": 999}]}},
    ]
    seen, data = consume(service, count=2)
    assert seen == ["90", "110", "80"]
    assert data["coverage_complete"]
    assert client.get_timeline.call_count == 2


@pytest.mark.parametrize("repeat", [9, 7, 3])
def test_overlap_checks_all_fetched_ids_including_buffered_lookahead(tmp_path, repeat):
    service, client = service_at(tmp_path)
    client.get_timeline.side_effect = [
        {"ok": True, "data": {"items": [{"id": 9}, {"id": 3}]}},
        {"ok": True, "data": {"items": [{"id": 7}, {"id": 2}]}},
        {"ok": True, "data": {"items": [{"id": repeat}]}},
    ]
    first = service.attention("catchup", count=2)["data"]
    assert service.attention("catchup", count=2, cursor=first["next_cursor"])["code"] == 502
    assert not service._receipts and not service.state.path.exists()


def test_cursor_retries_do_not_mutate_seen_set_of_previous_branch(tmp_path):
    service, client = service_at(tmp_path)
    native_feed(client, [9, 3, 7, 2, 8, 1])
    first = service.attention("catchup", count=2)["data"]
    cursor = first["next_cursor"]
    before = service._windows[cursor]["seen"]
    a = service.attention("catchup", count=2, cursor=cursor)["data"]
    b = service.attention("catchup", count=2, cursor=cursor)["data"]
    assert a["items"] == b["items"] and before == service._windows[cursor]["seen"]
    a_last = service.attention("catchup", count=2, cursor=a["next_cursor"])["data"]
    b_last = service.attention("catchup", count=2, cursor=b["next_cursor"])["data"]
    assert a_last["items"] == b_last["items"] and a_last["coverage_complete"]
    assert service.acknowledge(a_last["ack_receipt"])["ok"]
    assert service.acknowledge(b_last["ack_receipt"])["data"]["already_applied"]


def test_concurrent_identical_native_acks_change_revision_once(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.acknowledge("scope", "100", 0)
    barrier = Barrier(2)

    def acknowledge():
        barrier.wait(timeout=5)
        return StateStore(store.path).acknowledge("scope", "90", 1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(lambda _: acknowledge(), range(2)))
    assert sorted(r["already_applied"] for r in rows) == [False, True]
    assert store.cursor("scope") == ("90", 2)


def test_concurrent_different_native_acks_reject_stale_receipt(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.acknowledge("scope", "100", 0)
    barrier = Barrier(2)

    def acknowledge(value):
        barrier.wait(timeout=5)
        try:
            return StateStore(store.path).acknowledge("scope", value, 1)
        except StateConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(acknowledge, ["90", "80"]))
    assert sum(row is not None for row in rows) == 1
    assert store.cursor("scope")[1] == 2


@pytest.mark.parametrize("value", ["100", None, "", "not-an-id"])
def test_legacy_only_database_is_inspection_only_and_bytes_preserved(tmp_path, value):
    service, client = service_at(tmp_path)
    service.identity()
    with closing(sqlite3.connect(service.state.path)) as db, db:
        db.execute(
            "CREATE TABLE cursors (scope TEXT PRIMARY KEY, value TEXT, revision INTEGER NOT NULL)"
        )
        db.execute("INSERT INTO cursors VALUES (?,?,?)", (service._scope("catchup"), value, 7))
    before = service.state.path.read_bytes()
    client.get_timeline.side_effect = [
        {"ok": True, "data": {"items": [{"id": 90}, {"id": 110}]}},
        {"ok": True, "data": {"items": []}},
    ]
    seen, data = consume(service)
    assert seen == ["90", "110"]
    assert data["checkpoint_status"] == LEGACY_CURSOR and data["checkpoint_review_required"]
    assert data["mode"] == "checkpoint-review-required" and not data["coverage_complete"]
    assert data["ack_receipt"] is None and not service._receipts
    assert service.state.path.read_bytes() == before
    assert service.state.cursor(service._scope("catchup")) == (value, 7)


def test_mixed_legacy_native_and_new_consumer_state(tmp_path):
    service, client = service_at(tmp_path)
    service.identity()
    store = service.state
    write_legacy_cursor(store, service._scope("inbox"), "100")
    store.acknowledge(service._scope("catchup"), "100", 0)
    client.get_mentions.return_value = {"ok": True, "data": {"items": [{"id": 90}, {"id": 100}]}}
    assert not service.attention("inbox")["data"]["coverage_complete"]
    native_feed(client, [90, 100])
    seen, data = consume(service)
    assert seen == ["90"] and data["checkpoint_status"] == NATIVE_CURSOR
    other = MicroblogService(
        client, "default", "https://agent.micro.blog/", "new-consumer", store.path
    )
    _, bootstrap = consume(other)
    assert bootstrap["checkpoint_status"] == "empty" and bootstrap["mode"] == "bootstrap"
    assert store.cursor(service._scope("inbox")) == ("100", 1)


@pytest.mark.parametrize("replay", [False, True])
def test_legacy_write_invalidates_native_provenance(tmp_path, replay):
    store = StateStore(tmp_path / "state.sqlite")
    store.acknowledge("scope", "100", 0)
    write_legacy_cursor(store, "scope", "100" if replay else "110")
    assert store.cursor_record("scope")["scheme"] == LEGACY_CURSOR
    with pytest.raises(CheckpointReviewRequired):
        store.acknowledge("scope", "120", 2)


def test_rc2_style_write_between_read_and_ack_cannot_promote_legacy(tmp_path):
    service, client = service_at(tmp_path)
    service.identity()
    scope = service._scope("catchup")
    service.state.acknowledge(scope, "100", 0)
    native_feed(client, [90, 100])
    _, data = consume(service)
    # Old clients know only the original cursor table and leave stale provenance.
    with closing(sqlite3.connect(service.state.path)) as db, db:
        db.execute("UPDATE cursors SET value='110',revision=2 WHERE scope=?", (scope,))
    result = service.acknowledge(data["ack_receipt"])
    assert result["code"] == 409 and result["reason"] == "checkpoint_review_required"
    assert service.state.cursor(scope) == ("110", 2)


@pytest.mark.parametrize("orphan", [False, True])
def test_mismatched_and_orphan_provenance_require_review(tmp_path, orphan):
    service, client = service_at(tmp_path)
    service.identity()
    scope = service._scope("heartbeat")
    service.state.acknowledge(scope, "100", 0)
    with closing(sqlite3.connect(service.state.path)) as db, db:
        db.execute(
            "DELETE FROM cursors WHERE scope=?"
            if orphan
            else "UPDATE cursor_provenance SET revision=99 WHERE scope=?",
            (scope,),
        )
    client.get_timeline.side_effect = [{"ok": True, "data": {"items": []}}]
    data = service.attention("heartbeat")["data"]
    assert data["mode"] == "checkpoint-review-required" and data["checkpoint_review_required"]
    assert not data["coverage_complete"] and data["ack_receipt"] is None
    with pytest.raises(CheckpointReviewRequired):
        service.state.acknowledge(scope, "90", data["revision"])


def test_null_revision_in_malformed_legacy_schema_is_not_bootstrap(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    with closing(sqlite3.connect(store.path)) as db, db:
        db.execute("CREATE TABLE cursors (scope TEXT PRIMARY KEY,value TEXT,revision INTEGER)")
        db.execute("INSERT INTO cursors VALUES ('scope',NULL,NULL)")
    assert store.cursor_record("scope")["scheme"] == LEGACY_CURSOR


@pytest.mark.parametrize("scope_change", ["consumer", "workflow", "profile", "blog", "account"])
def test_handles_and_provenance_bind_verified_scope(tmp_path, scope_change):
    service, client = service_at(tmp_path)
    native_feed(client, [9, 3, 7, 2, 8, 1])
    first = service.attention("catchup", count=2)["data"]
    cursor = first["next_cursor"]
    if scope_change == "workflow":
        assert service.attention("inbox", cursor=cursor)["code"] == 409
        return
    blog = "https://other.micro.blog/" if scope_change == "blog" else "https://agent.micro.blog/"
    username = "stranger" if scope_change == "account" else "agent"
    other, other_client = service_at(tmp_path, username=username, blog=blog)
    native_feed(other_client, [9, 3, 7, 2, 8, 1])
    if scope_change == "consumer":
        other.consumer = "other"
    if scope_change == "profile":
        other.profile = "alias"
    assert other.attention("catchup", cursor=cursor)["code"] == 409  # handles are process-local
    _, data = consume(service)
    assert other.acknowledge(data["ack_receipt"])["code"] == 409
    assert service.acknowledge(data["ack_receipt"])["ok"]
    other.identity()
    expected = NATIVE_CURSOR if scope_change == "profile" else None
    assert other.state.cursor_record(other._scope("catchup"))["scheme"] == expected


@pytest.mark.parametrize("value", ["01", "0", "²", "-1", "1" * 21])
def test_native_state_requires_canonical_id(value, tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    with pytest.raises(StateConflict):
        store.acknowledge("scope", value, 0)
    assert not store.path.exists()


@pytest.mark.parametrize("cursor_table", [False, True])
def test_nullable_scheme_orphan_provenance_is_not_bootstrap(tmp_path, cursor_table):
    store = StateStore(tmp_path / "state.sqlite")
    with closing(sqlite3.connect(store.path)) as db, db:
        if cursor_table:
            db.execute("CREATE TABLE cursors (scope TEXT PRIMARY KEY,value TEXT,revision INTEGER)")
        db.execute(
            "CREATE TABLE cursor_provenance (scope TEXT PRIMARY KEY,value TEXT,revision INTEGER,scheme TEXT)"
        )
        db.execute("INSERT INTO cursor_provenance VALUES ('scope','100',1,NULL)")
    assert store.cursor_record("scope")["scheme"] == LEGACY_CURSOR
    with pytest.raises(CheckpointReviewRequired):
        store.acknowledge("scope", "90", 0)
