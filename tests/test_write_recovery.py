"""Interrupted writes, human reconciliation and pre-claim failures; synthetic HTTP only."""

import asyncio
import json
import sqlite3
from contextlib import closing
from unittest.mock import Mock, patch

import pytest

from mb.api import MicroblogClient
from mb.services import MicroblogService
from mb.state import StateConflict, StateStore
from tests.test_cli_write_safety import BLOG, URL, Harness

AGENT = "https://agent.example/"


@pytest.fixture
def client():
    client = Mock(spec=MicroblogClient)
    client.token = "synthetic"
    client.verify_token.return_value = {"ok": True, "data": {"username": "agent"}}
    client.micropub_get_config.return_value = {
        "ok": True,
        "data": {"destination": [{"uid": AGENT}]},
    }
    client.micropub_create.return_value = {"ok": True, "data": {"url": AGENT + "post"}}
    return client


def statuses(path):
    with closing(sqlite3.connect(path)) as db:
        return dict(db.execute("SELECT id,status FROM operations").fetchall())


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt, SystemExit, asyncio.CancelledError])
def test_interrupted_dispatch_finishes_unknown_and_unblocks_scope(tmp_path, client, interrupt):
    service = MicroblogService(client, "default", None, "cli", tmp_path / "state.sqlite")
    client.micropub_create.side_effect = interrupt()
    with pytest.raises(interrupt):
        service.write("post_create", "interrupted", {"content": "Hello"})
    assert statuses(service.state.path) == {"interrupted": "unknown"}
    receipt = service.operation_status("interrupted")
    assert receipt["outcome"] == "unknown" and receipt["error"] == "write_outcome_unknown"
    client.micropub_create.side_effect = None
    assert service.write("post_create", "next", {"content": "Later"})["outcome"] == "applied"
    # The uncertain write is never resent under its own ID.
    assert service.write("post_create", "interrupted", {"content": "Hello"})["outcome"] == (
        "unknown"
    )
    assert client.micropub_create.call_count == 2


def test_interrupt_still_raises_when_receipt_storage_also_fails(tmp_path, client):
    service = MicroblogService(client, "default", None, "cli", tmp_path / "state.sqlite")
    client.micropub_create.side_effect = KeyboardInterrupt()
    with patch.object(StateStore, "finish", side_effect=OSError("disk")):
        with pytest.raises(KeyboardInterrupt):
            service.write("post_create", "interrupted", {"content": "Hello"})
    # The claim stays pending for a human to resolve.
    assert statuses(service.state.path) == {"interrupted": "pending"}


def stuck_claim(tmp_path, operation_id="cli-killed"):
    state = StateStore(tmp_path / "receipts.sqlite")
    scope = json.dumps(["agent", BLOG])
    state.claim(scope, operation_id, state.fingerprint("post_create", {"content": "Hello"}))
    return state


def test_killed_process_claim_resolves_and_new_writes_proceed(tmp_path):
    stuck_claim(tmp_path)
    harness = Harness(tmp_path)
    blocked, data = harness.invoke(["post", "new", "Next", "--operation-id", "next"])
    assert blocked.exit_code == 1 and "cli-killed" in data["error"] and not harness.writes
    result, resolved = harness.invoke(
        ["operation-status", "cli-killed", "--resolve", "not_applied", "--note", "Not on blog"]
    )
    assert result.exit_code == 0, resolved
    assert resolved["outcome"] == "not_applied" and resolved["operation_id"] == "cli-killed"
    assert resolved["data"]["previous_status"] == "pending"
    assert resolved["data"]["resolved_by"] == "cli"
    assert resolved["data"]["note"] == "Not on blog"
    assert resolved["data"]["receipt_scope"] == "blog"
    _, created = harness.invoke(["post", "new", "Next", "--operation-id", "next"])
    assert created["outcome"] == "applied" and len(harness.writes) == 1
    _, receipt = harness.invoke(["operation-status", "cli-killed"])
    assert receipt["outcome"] == "not_applied" and receipt["error"] == "write_not_applied"
    history = receipt["resolution"]
    assert history["previous_status"] == "pending" and history["previous_receipt"] is None
    assert history["resolved_at"].endswith("+00:00")


def test_unknown_receipt_resolved_applied_keeps_previous_receipt(tmp_path):
    harness = Harness(tmp_path, "timeout")
    _, uncertain = harness.invoke(["post", "new", "Hello", "--operation-id", "maybe"])
    assert uncertain["outcome"] == "unknown"
    result, resolved = harness.invoke(["operation-status", "maybe", "--resolve", "applied"])
    assert result.exit_code == 0 and resolved["outcome"] == "applied"
    _, receipt = harness.invoke(["operation-status", "maybe"])
    assert receipt["ok"] and receipt["outcome"] == "applied" and "recovery_command" not in receipt
    previous = receipt["resolution"]["previous_receipt"]
    assert previous["outcome"] == "unknown" and previous["operation_id"] == "maybe"
    _, retry = harness.invoke(["post", "new", "Hello", "--operation-id", "maybe"])
    assert retry["outcome"] == "applied" and len(harness.writes) == 1


def test_resolution_refuses_settled_receipts_and_bad_arguments(tmp_path):
    harness = Harness(tmp_path)
    _, applied = harness.invoke(["post", "new", "Hello", "--operation-id", "done"])
    assert applied["outcome"] == "applied"
    result, refused = harness.invoke(["operation-status", "done", "--resolve", "not_applied"])
    assert result.exit_code == 1 and refused["code"] == 409
    assert refused["reason"] == "not_resolvable" and refused["outcome"] == "applied"
    _, receipt = harness.invoke(["operation-status", "done"])
    assert receipt["outcome"] == "applied" and "resolution" not in receipt
    _, missing = harness.invoke(["operation-status", "absent", "--resolve", "applied"])
    assert missing["code"] == 404
    for args in [
        ["operation-status", "done", "--resolve", "maybe"],
        ["operation-status", "done", "--note", "no answer"],
        ["operation-status", "--latest", "--resolve", "applied"],
    ]:
        result, data = harness.invoke(args)
        assert result.exit_code == 1 and data["code"] == 400
    assert len(harness.writes) == 1


def test_resolution_requires_scope_when_id_is_in_both(tmp_path):
    harness = Harness(tmp_path, "timeout")
    harness.invoke(["post", "new", "Hello", "--operation-id", "shared"])
    harness.invoke(["post", "reply", "12", "Hello", "--operation-id", "shared"])
    _, ambiguous = harness.invoke(["operation-status", "shared", "--resolve", "applied"])
    assert ambiguous["reason"] == "ambiguous_operation"
    _, resolved = harness.invoke(
        ["operation-status", "shared", "--scope", "reply", "--resolve", "applied"]
    )
    assert resolved["data"]["receipt_scope"] == "reply"
    _, blog = harness.invoke(["operation-status", "shared", "--scope", "blog"])
    assert blog["outcome"] == "unknown"


def test_late_finish_keeps_human_resolution(tmp_path):
    state = stuck_claim(tmp_path)
    scope = json.dumps(["agent", BLOG])
    state.resolve(scope, "cli-killed", "not_applied", resolved_at="now", resolved_by="cli")
    state.finish(scope, "cli-killed", {"ok": True, "outcome": "applied"})
    receipt = state.operation(scope, "cli-killed")
    assert receipt["outcome"] == "not_applied"
    assert receipt["resolution"]["late_receipt"]["outcome"] == "applied"
    with pytest.raises(StateConflict):
        state.resolve(scope, "cli-killed", "applied", resolved_at="now", resolved_by="cli")
    with pytest.raises(ValueError):
        state.resolve(scope, "cli-killed", "unknown", resolved_at="now", resolved_by="cli")


def test_resolution_of_missing_state_file_does_not_create_it(tmp_path):
    state = StateStore(tmp_path / "absent.sqlite")
    assert state.resolve("s", "id", "applied", resolved_at="now", resolved_by="cli") is None
    assert not state.path.exists()


def test_failure_before_claim_is_not_applied_without_recovery(tmp_path):
    harness = Harness(tmp_path)
    with patch.object(MicroblogService, "identity", side_effect=RuntimeError("private detail")):
        result, data = harness.invoke(["post", "new", "Hello"])
    assert result.exit_code == 1
    assert data["outcome"] == "not_applied" and "recovery_command" not in data
    assert "operation_id" not in data and "private" not in json.dumps(data)
    assert not harness.writes and not (tmp_path / "receipts.sqlite").exists()


def test_failed_reply_recipient_read_never_consumes_the_operation_id(tmp_path):
    harness = Harness(tmp_path)
    harness.unavailable = True
    result, data = harness.invoke(["post", "reply", "12", "Hello", "--operation-id", "reply-1"])
    assert result.exit_code == 1 and data["outcome"] == "not_applied"
    assert "recovery_command" not in data and not harness.writes
    _, status = harness.invoke(["operation-status", "reply-1"])
    assert status["code"] == 404
    harness.unavailable = False
    _, sent = harness.invoke(["post", "reply", "12", "Hello", "--operation-id", "reply-1"])
    assert sent["outcome"] == "applied" and len(harness.writes) == 1
    assert b"%40other+Hello" in harness.writes[0].content


@pytest.mark.parametrize(
    "args,stdin",
    [
        (["--content", ""], None),
        (["--content", "   "], None),
        (["--content", "-"], ""),
        (["--content", "-"], " \n "),
    ],
)
def test_empty_edit_content_is_refused_before_claim(tmp_path, args, stdin):
    harness = Harness(tmp_path)
    result, data = harness.invoke(["post", "edit", URL, *args], input=stdin)
    assert result.exit_code == 1 and data["error"] == "Content is empty"
    assert data["outcome"] == "not_applied" and not harness.writes
    assert not (tmp_path / "receipts.sqlite").exists()


@pytest.mark.parametrize("args", [["--title", "New title"], ["--category", "notes"]])
def test_title_or_category_only_edit_still_works(tmp_path, args):
    harness = Harness(tmp_path)
    result, data = harness.invoke(["post", "edit", URL, *args])
    assert result.exit_code == 0 and data["outcome"] == "applied"
    replace = json.loads(harness.writes[0].content)["replace"]
    assert "content" not in replace and len(replace) == 1


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def call(adapter, name, arguments):
    types = pytest.importorskip("mcp.types")

    return (
        await adapter.call_tool(None, types.CallToolRequestParams(name=name, arguments=arguments))
    ).structured_content


@pytest.mark.anyio
async def test_mcp_empty_edit_content_is_invalid(tmp_path, client):
    from mb.mcp_server import Adapter

    service = MicroblogService(client, "default", None, "dot", tmp_path / "state.sqlite")
    result = await call(
        Adapter(lambda: service),
        "post_edit",
        {"identifier": AGENT + "post", "content": "", "operation_id": "edit-1"},
    )
    assert result["code"] == 400 and "content" in result["error"]
    client.micropub_update.assert_not_called()
    whitespace = service.write(
        "post_edit", "edit-2", {"identifier": AGENT + "post", "content": "  "}
    )
    assert whitespace["error"] == "Content is empty" and whitespace["outcome"] == "not_applied"


@pytest.mark.anyio
async def test_mcp_failure_before_claim_is_not_applied(tmp_path, client):
    from mb.mcp_server import Adapter

    service = MicroblogService(client, "default", None, "dot", tmp_path / "state.sqlite")
    adapter = Adapter(lambda: service)
    client.verify_token.side_effect = RuntimeError("private")
    result = await call(adapter, "post_create", {"content": "hello", "operation_id": "early"})
    assert result["outcome"] == "not_applied" and "operation_id" not in result
    client.verify_token.side_effect = None
    with patch.object(service.state, "lookup", side_effect=sqlite3.OperationalError("locked")):
        result = await call(adapter, "post_create", {"content": "hello", "operation_id": "early"})
    assert result["outcome"] == "not_applied" and result["code"] == 503
    assert not service.state.path.exists()
    client.micropub_create.assert_not_called()
