"""Exploratory MCP regressions: synthetic transports, credentials and isolated state."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import httpx
import pytest

from mb.api import MicroblogClient
from mb.domain import _build_thread
from mb.services import MicroblogService, read_conversation


def service_at(tmp_path, username="agent", blog="https://agent.micro.blog/"):
    client = Mock(spec=MicroblogClient)
    client.token = "synthetic-secret"
    client.verify_token.return_value = {"ok": True, "data": {"username": username}}
    client.micropub_get_config.return_value = {
        "ok": True,
        "data": {"destination": [{"uid": blog}]},
    }
    client.get_conversation.return_value = {
        "ok": True,
        "data": {"items": [{"id": 12, "author": {"_microblog": {"username": "alice"}}}]},
    }
    client.micropub_create.return_value = {
        "ok": True,
        "data": {"url": blog + "created"},
    }
    client.post_reply.return_value = {
        "ok": False,
        "code": 599,
        "error": "network_error",
        "outcome": "unknown",
    }
    return MicroblogService(client, "default", blog, "dot", tmp_path / "state.sqlite"), client


@pytest.mark.parametrize("reply_first", [False, True])
def test_status_never_prefers_an_unrelated_success(tmp_path, reply_first):
    service, client = service_at(tmp_path)

    def create():
        assert service.write("post_create", "same-id", {"content": "hello"})["outcome"] == "applied"

    def reply():
        assert (
            service.write("post_reply", "same-id", {"post_id": "12", "content": "hello"})["outcome"]
            == "unknown"
        )

    for action in [reply, create] if reply_first else [create, reply]:
        action()
    ambiguous = service.operation_status("same-id")
    assert not ambiguous["ok"] and ambiguous["reason"] == "ambiguous_operation"
    assert "outcome" not in ambiguous
    assert service.operation_status("same-id", "blog")["outcome"] == "applied"
    assert service.operation_status("same-id", "reply")["outcome"] == "unknown"
    assert service.operation_status("same-id", "other")["code"] == 400
    other, _ = service_at(tmp_path, blog="https://other.micro.blog/")
    assert other.operation_status("same-id")["outcome"] == "unknown"
    assert other.operation_status("same-id", "blog")["code"] == 404
    stranger, _ = service_at(tmp_path, username="stranger")
    assert stranger.operation_status("same-id")["code"] == 404
    client.micropub_create.assert_called_once()
    client.post_reply.assert_called_once()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"unexpected": "value"},
        [],
        None,
        {"id": True},
        {"id": 0},
        {"id": "bad"},
        {"id": "²"},
        {"id": "٣"},
        pytest.param({"id": "1" * 4500}, id="oversized-id"),
    ],
)
def test_malformed_reply_success_is_durable_unknown(tmp_path, payload):
    service, mock = service_at(tmp_path)
    writes = []

    def respond(request):
        writes.append(request)
        return httpx.Response(
            200, content=json.dumps(payload), headers={"Content-Type": "application/json"}
        )

    with MicroblogClient("synthetic-secret") as client:
        client._client.close()
        client._client = httpx.Client(
            transport=httpx.MockTransport(respond), base_url="https://micro.blog"
        )
        mock.post_reply.side_effect = client.post_reply
        args = {"post_id": "12", "content": "hello"}
        result = service.write("post_reply", "malformed", args)
        assert not result["ok"] and result["outcome"] == "unknown"
        assert service.operation_status("malformed")["outcome"] == "unknown"
        assert service.write("post_reply", "malformed", args)["outcome"] == "unknown"
        assert len(writes) == 1
        with service.state.connection() as db:
            assert db.execute("SELECT status FROM operations").fetchone()[0] == "unknown"


@pytest.mark.parametrize("reply_id", [13, "13"])
def test_identifiable_reply_confirmation(reply_id):
    with MicroblogClient("synthetic") as client:
        client._client.close()
        client._client = httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"id": reply_id})),
            base_url="https://micro.blog",
        )
        assert client.post_reply(12, "hello")["data"]["id"] == reply_id


@pytest.mark.parametrize("status", [401, 429, 500])
def test_reply_errors_preserve_rate_limit_and_uncertainty(tmp_path, status):
    service, mock = service_at(tmp_path)
    with MicroblogClient("synthetic") as client:
        client._client.close()
        client._client = httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(status, headers={"Retry-After": "7"})
            ),
            base_url="https://micro.blog",
        )
        mock.post_reply.side_effect = client.post_reply
        result = service.write("post_reply", "failed", {"post_id": "12", "content": "hello"})
        assert result["code"] == status
        assert result["outcome"] == ("unknown" if status == 500 else "not_applied")
        if status == 429:
            assert result["retry_after"] == 7


@pytest.mark.parametrize(
    "items",
    [
        [{"id": 1, "_microblog": {"reply_to_id": 2}}, {"id": 2, "_microblog": {"reply_to_id": 1}}],
        [{"id": 3}, {"id": 1, "_microblog": {"reply_to_id": 1}}],
        [{"id": 1}, {"id": "1"}],
        [{"content_html": "missing ID"}],
        [{"id": 1, "_microblog": []}],
    ],
)
def test_invalid_conversation_is_not_successful_empty_feed(tmp_path, items):
    service, client = service_at(tmp_path)
    client.get_conversation.return_value = {"ok": True, "data": {"items": items}}
    result = read_conversation(client, "1")
    assert result == {"ok": False, "error": "Invalid conversation response", "code": 502}
    assert not service.state.path.exists()


def test_deep_conversation_preserves_all_items():
    items = [{"id": i, "_microblog": {"reply_to_id": i - 1}} for i in range(1, 2501)]
    ordered = _build_thread(items)
    assert len(ordered) == 2500 and ordered[-1]["depth"] == 2499
    assert [i["id"] for i in ordered] == list(range(1, 2501))


@pytest.mark.parametrize(
    "arguments,ids",
    [({"before": "10"}, [10, 9]), ({"since": "10"}, [11, 10])],
)
def test_timeline_bounds_fail_closed(tmp_path, arguments, ids):
    service, client = service_at(tmp_path)
    client.get_timeline.return_value = {"ok": True, "data": {"items": [{"id": i} for i in ids]}}
    result = service.timeline(count=1, **arguments)
    assert not result["ok"] and result["code"] == 502
    assert "next_cursor" not in result.get("data", {})
    assert not service.state.path.exists()


def test_timeline_probe_cannot_claim_more_or_exhaustion_from_wrong_bounds(tmp_path):
    service, client = service_at(tmp_path)
    client.get_timeline.side_effect = [
        {"ok": True, "data": {"items": [{"id": 9}]}},
        {"ok": True, "data": {"items": [{"id": 9}]}},
    ]
    assert service.timeline(count=3)["code"] == 502


def test_two_process_services_share_one_claim_during_dispatch(tmp_path):
    first, client = service_at(tmp_path)
    second, other_client = service_at(tmp_path)
    entered, release = Event(), Event()

    def slow_create(**kwargs):
        entered.set()
        assert release.wait(5)
        return {"ok": True, "data": {"url": "https://agent.micro.blog/created"}}

    client.micropub_create.side_effect = slow_create
    arguments = {"content": "hello"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(first.write, "post_create", "one", arguments)
        try:
            assert entered.wait(5)
            assert second.write("post_create", "one", arguments)["outcome"] == "unknown"
            assert second.write("post_create", "two", arguments)["code"] == 409
        finally:
            release.set()
        assert pending.result()["outcome"] == "applied"
    assert second.write("post_create", "one", arguments)["outcome"] == "applied"
    assert second.write("post_create", "one", {"content": "changed"})["code"] == 409
    client.micropub_create.assert_called_once()
    other_client.micropub_create.assert_not_called()


@pytest.mark.anyio
async def test_mcp_redacts_nested_keys_and_untrusted_validation_locations(tmp_path):
    pytest.importorskip("mcp")
    from mcp import types

    from mb.mcp_server import Adapter

    service, client = service_at(tmp_path)
    client.get_timeline.side_effect = [
        {
            "ok": True,
            "data": {
                "items": [
                    {
                        "id": 1,
                        "synthetic-secret": "private",
                        "nested": {
                            "prefix-synthetic-secret": "private",
                            "prefix-[redacted]": "safe",
                            "value": "synthetic-secret",
                        },
                    }
                ]
            },
        },
        {"ok": True, "data": {"items": []}},
    ]
    adapter = Adapter(lambda: service)
    result = await adapter.call_tool(
        None, types.CallToolRequestParams(name="timeline", arguments={"count": 1})
    )
    assert result.structured_content == json.loads(result.content[0].text)
    assert "synthetic-secret" not in str(result)
    assert result.structured_content["data"]["items"][0]["nested"]["prefix-[redacted]"] == "safe"
    invalid = await adapter.call_tool(
        None,
        types.CallToolRequestParams(name="identity", arguments={"synthetic-secret": "private"}),
    )
    assert invalid.is_error and "synthetic-secret" not in str(invalid)


def test_timeline_preserves_native_order_and_uses_last_returned_id(tmp_path):
    service, client = service_at(tmp_path)
    feed = [10, 7, 9, 5, 8, 2]

    def page(count=20, before_id=None, since_id=None):
        start = feed.index(int(before_id)) + 1 if before_id is not None else 0
        return {
            "ok": True,
            "data": {"items": [{"id": i} for i in feed[start : start + min(count, 3)]]},
        }

    client.get_timeline.side_effect = page
    seen = []
    before = None
    for _ in range(5):
        result = service.timeline(count=2, before=before)["data"]
        seen += [int(item["id"]) for item in result["items"]]
        before = result["next_cursor"]
        if before is None:
            break
        before = str(before)
    assert seen == feed
    assert not service.state.path.exists()


@pytest.mark.parametrize("ids", [[90, 110], [90, 80]])
def test_inbox_cannot_acknowledge_a_numeric_guess_of_checkpoint(tmp_path, ids):
    service, client = service_at(tmp_path)
    service.identity()
    service.state.acknowledge(service._scope("inbox"), "100", 0)
    client.get_mentions.return_value = {"ok": True, "data": {"items": [{"id": i} for i in ids]}}
    result = service.attention("inbox")
    if result["ok"]:
        assert [int(entry["item"]["id"]) for entry in result["data"]["items"]] == ids
        assert not result["data"]["coverage_complete"] and result["data"]["ack_receipt"] is None
    else:
        assert result["code"] == 502
    assert not service._receipts
    assert service.state.cursor(service._scope("inbox")) == ("100", 1)


def test_inbox_exact_checkpoint_proves_prefix_only(tmp_path):
    service, client = service_at(tmp_path)
    service.identity()
    service.state.acknowledge(service._scope("inbox"), "100", 0, native=True)
    client.get_mentions.return_value = {
        "ok": True,
        "data": {"items": [{"id": i} for i in [110, 100, 90]]},
    }
    result = service.attention("inbox")["data"]
    assert [entry["item"]["id"] for entry in result["items"]] == ["110"]
    assert result["coverage_complete"] and result["ack_receipt"]
    assert service.acknowledge(result["ack_receipt"])["data"]["checkpoint"] == "110"


def test_legacy_checkpoint_does_not_gain_trust_from_native_exhaustion(tmp_path):
    service, client = service_at(tmp_path)
    service.identity()
    service.state.acknowledge(service._scope("catchup"), "100", 0)
    client.get_timeline.side_effect = [
        {"ok": True, "data": {"items": [{"id": 90}]}},
        {"ok": True, "data": {"items": []}},
    ]
    data = service.attention("catchup")["data"]
    assert data["items"][0]["id"] == "90"
    assert data["checkpoint_review_required"] and not data["coverage_complete"]
    assert data["ack_receipt"] is None
    assert not service._receipts
    assert service.state.cursor(service._scope("catchup")) == ("100", 1)
