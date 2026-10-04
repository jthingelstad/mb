"""Agent contracts tested with synthetic accounts and no external writes."""

import sqlite3
from unittest.mock import Mock
from urllib.parse import parse_qs

import httpx
import pytest

from mb.api import MicroblogClient
from mb.services import MicroblogService
from mb.state import StateConflict, StateStore

BLOG = "https://agent.example/"


@pytest.fixture
def client():
    client = Mock(spec=MicroblogClient)
    client.verify_token.return_value = {
        "ok": True,
        "data": {"username": "agent", "default_site": "agent.example"},
    }
    client.micropub_get_config.return_value = {
        "ok": True,
        "data": {"destination": [{"uid": BLOG, "name": "Agent"}]},
    }
    client.get_mentions.return_value = {"ok": True, "data": {"items": []}}
    client.get_conversation.return_value = {"ok": True, "data": {"items": []}}
    return client


@pytest.fixture
def service(client, tmp_path):
    return MicroblogService(client, "default", BLOG, "dot", tmp_path / "state.sqlite")


def timeline(items):
    def page(count=20, since_id=None, before_id=None):
        values = [
            i
            for i in items
            if (since_id is None or i > since_id) and (before_id is None or i < before_id)
        ]
        # Simulate a server cap below our request: a short page is not proof of exhaustion.
        return {
            "ok": True,
            "data": {
                "items": [{"id": i, "content_html": f"post {i}"} for i in values[: min(count, 2)]]
            },
        }

    return page


def test_attention_paginates_then_acknowledges_and_isolates_consumers(service, client):
    items = list(range(110, 100, -1))
    client.get_timeline.side_effect = timeline(items)
    seen = []
    cursor = None
    for _ in range(10):
        page = service.attention("catchup", count=3, cursor=cursor)["data"]
        assert page["advanced"] is False
        assert not service.state.path.exists()
        seen += [int(i["id"]) for i in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
        assert page["ack_receipt"] is None
        # Incoming activity must be excluded from this frozen window.
        if 111 not in items:
            items.insert(0, 111)
    assert seen == list(range(110, 100, -1))
    assert page["coverage_complete"]
    receipt = page["ack_receipt"]
    assert service.acknowledge(receipt)["data"]["checkpoint"] == "110"
    assert service.acknowledge(receipt)["data"]["already_applied"]
    fresh = service.attention("catchup", count=3)["data"]
    assert fresh["items"][0]["id"] == "111"
    other = MicroblogService(client, "default", BLOG, "openclaw", service.state.path)
    assert other.attention("catchup")["data"]["mode"] == "bootstrap"


def test_stale_ack_and_cursor_conflict(service, client):
    client.get_timeline.side_effect = timeline([3, 2, 1])
    first = service.attention("catchup", count=1)["data"]
    second = service.attention("catchup", count=5)["data"]
    while second["next_cursor"]:
        second = service.attention("catchup", count=5, cursor=second["next_cursor"])["data"]
    assert service.acknowledge(second["ack_receipt"])["ok"]
    assert service.attention("catchup", count=1, cursor=first["next_cursor"])["code"] == 409
    assert service.acknowledge("invented")["code"] == 409


def test_broken_upstream_paging_never_acknowledges(service, client):
    client.get_timeline.return_value = {"ok": True, "data": {"items": [{"id": 3}]}}
    assert service.attention("catchup", count=1)["code"] == 502
    assert not service.state.path.exists()


def test_inbox_recent_window_gap_is_reported(service, client):
    service.identity()
    service.state.acknowledge(service._scope("inbox"), "10", 0, native=True)
    client.get_mentions.return_value = {"ok": True, "data": {"items": [{"id": 30}, {"id": 29}]}}
    result = service.attention("inbox")["data"]
    assert result["coverage"] == "recent-mentions-window"
    assert not result["coverage_complete"]
    assert result["ack_receipt"] is None
    assert service.state.cursor(service._scope("inbox")) == ("10", 1)


def test_identity_is_verified_canonical_and_pinned(service, client):
    assert service.identity()["data"]["blog"] == BLOG
    client.verify_token.return_value = {"ok": True, "data": {"username": "changed"}}
    assert service.identity()["data"]["username"] == "agent"
    client.verify_token.assert_called_once()
    service.requested_blog = "Unknown"
    assert service.identity()["data"]["blog"] == BLOG
    ambiguous = MicroblogService(client, "p", "Missing", "dot", service.state.path)
    assert ambiguous.identity()["code"] == 400


def test_create_receipt_survives_restart_and_no_body_persists(service, client):
    client.micropub_create.return_value = {
        "ok": True,
        "data": {"url": BLOG + "post", "id": "post", "content": "private body"},
    }
    result = service.write("post_create", "unique-1", {"content": "private body"})
    assert result["outcome"] == "applied"
    restarted = MicroblogService(client, "default", BLOG, "openclaw", service.state.path)
    retry = restarted.write("post_create", "unique-1", {"content": "private body"})
    assert retry["data"] == {"url": BLOG + "post", "id": "post"}
    client.micropub_create.assert_called_once()
    assert restarted.write("post_create", "unique-1", {"content": "changed"})["code"] == 409
    assert "private body" not in service.state.path.read_bytes().decode(errors="ignore")
    assert service.state.path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("failure", ["timeout", "exception", "rate"])
def test_failed_write_is_not_automatically_resent(service, client, failure):
    if failure == "exception":
        client.micropub_create.side_effect = RuntimeError("SECRET")
    else:
        client.micropub_create.return_value = {
            "ok": False,
            "error": "rate_limited" if failure == "rate" else "network_error",
            "code": 429 if failure == "rate" else 599,
            "outcome": "not_applied" if failure == "rate" else "unknown",
            "retry_after": 60,
        }
    result = service.write("post_create", "same", {"content": "hello"})
    assert result["outcome"] == ("not_applied" if failure == "rate" else "unknown")
    retry = service.write("post_create", "same", {"content": "hello"})
    assert retry == service.operation_status("same")
    assert "SECRET" not in str(retry)
    client.micropub_create.assert_called_once()


def test_delete_retry_does_not_require_deleted_source(service, client):
    client.micropub_get.return_value = {"ok": True, "data": {"properties": {}}}
    client.micropub_delete.return_value = {"ok": True, "data": {}}
    args = {"identifier": BLOG + "post"}
    assert service.write("post_delete", "delete-1", args)["ok"]
    client.micropub_get.return_value = {"ok": False, "code": 404, "error": "gone"}
    assert service.write("post_delete", "delete-1", args)["ok"]
    client.micropub_get.assert_called_once()
    assert (
        service.write("post_delete", "delete-other", {"identifier": "https://other.example/post"})[
            "code"
        ]
        == 403
    )


def test_reply_adds_native_recipient_mention(service, client):
    client.get_conversation.return_value = {
        "ok": True,
        "data": {"items": [{"id": 12, "author": {"_microblog": {"username": "alice"}}}]},
    }
    client.post_reply.return_value = {"ok": True, "data": {"id": 13}}
    assert service.write("post_reply", "reply-1", {"post_id": "12", "content": "Useful"})["ok"]
    client.post_reply.assert_called_once_with(12, "@alice Useful")


def test_read_only_blocks_all_mutations_but_allows_preview(service, client):
    service.read_only = True
    assert service.preview(content="hello")["data"]["dry_run"]
    assert service.write("post_create", "id", {"content": "hello"})["code"] == 403
    assert service.acknowledge("receipt")["code"] == 403
    assert not service.state.path.exists()


def test_pending_claim_blocks_competing_process_and_unknown_retry(tmp_path):
    state = StateStore(tmp_path / "state.sqlite")
    assert state.claim("blog", "first", "fingerprint") is None
    other = StateStore(state.path)
    with pytest.raises(StateConflict):
        other.claim("blog", "second", "other")
    assert other.lookup("blog", "first", "fingerprint")["outcome"] == "unknown"
    with pytest.raises(StateConflict):
        other.lookup("blog", "first", "different")


def test_cursor_compare_and_swap(tmp_path):
    state = StateStore(tmp_path / "state.sqlite")
    state.acknowledge("dot", "100", 0)
    with pytest.raises(StateConflict):
        state.acknowledge("dot", "200", 0)
    with pytest.raises(StateConflict):
        state.acknowledge("dot", "99", 1)
    assert state.cursor("openclaw") == (None, 0)


def test_state_read_handles_empty_database_without_writing(tmp_path):
    path = tmp_path / "empty.sqlite"
    sqlite3.connect(path).close()
    assert StateStore(path).cursor("dot") == (None, 0)
    assert StateStore(path).operation("blog", "id") is None


def test_actual_http_payload_is_selected_blog_and_rate_limit_preserved(tmp_path):
    requests = []

    def response(request):
        requests.append(request)
        if request.url.path == "/account/verify":
            return httpx.Response(200, json={"username": "agent", "default_site": "agent.example"})
        if request.method == "GET":
            return httpx.Response(200, json={"destination": [{"uid": BLOG}]})
        return httpx.Response(429, headers={"Retry-After": "42"})

    with MicroblogClient("synthetic") as client:
        client._client.close()
        client._client = httpx.Client(
            transport=httpx.MockTransport(response), base_url="https://micro.blog"
        )
        service = MicroblogService(client, "default", BLOG, "dot", tmp_path / "state.sqlite")
        result = service.write("post_create", "limited", {"content": "hello"})
    assert result["retry_after"] == 42
    assert result["outcome"] == "not_applied"
    assert parse_qs(requests[-1].content.decode())["mp-destination"] == [BLOG]


def test_bounded_timeline_detects_more_when_upstream_caps_page(service, client):
    client.get_timeline.side_effect = timeline([5, 4, 3, 2, 1])
    result = service.timeline(count=10)["data"]
    assert result["returned_count"] == 2
    assert result["next_cursor"] == "4"


def test_draft_preview_not_persisted(service, client):
    client.micropub_create.return_value = {
        "ok": True,
        "data": {"url": BLOG + "draft", "preview": "sensitive-preview-link"},
    }
    assert service.write("post_create", "draft-1", {"content": "Draft", "draft": True})["data"][
        "preview"
    ]
    assert "preview" not in service.operation_status("draft-1")["data"]
    assert b"sensitive-preview-link" not in service.state.path.read_bytes()


def test_first_heartbeat_is_a_bounded_explicit_baseline(service, client):
    client.get_timeline.side_effect = timeline(list(range(100, 0, -1)))
    result = service.heartbeat(count=3)["data"]
    assert result["coverage"] == "bootstrap-recent-baseline"
    assert result["mode"] == "bootstrap"
    assert result["next_cursor"] is None
    assert result["ack_receipt"]
    assert not service.state.path.exists()
    client.get_timeline.assert_called_once()
    assert service.acknowledge(result["ack_receipt"])["data"]["checkpoint"] == "100"
