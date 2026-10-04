"""Review regressions, entirely synthetic transport/state and no external writes."""

from unittest.mock import Mock

import httpx
import pytest

from mb.api import MicroblogClient
from mb.services import MicroblogService


def make_service(
    tmp_path,
    username="agent",
    blog="https://agent.micro.blog/",
    profile="default",
    destinations=None,
):
    client = Mock(spec=MicroblogClient)
    client.token = "synthetic-secret"
    client.verify_token.return_value = {"ok": True, "data": {"username": username}}
    client.micropub_get_config.return_value = {
        "ok": True,
        "data": {"destination": destinations or [{"uid": blog, "name": "public.example"}]},
    }
    client.micropub_get.return_value = {"ok": True, "data": {"properties": {}}}
    client.micropub_delete.return_value = {"ok": True, "data": {}}
    return MicroblogService(client, profile, blog, "dot", tmp_path / "state.sqlite"), client


def test_selected_custom_domain_read_delete_and_numeric_resolution(tmp_path):
    service, client = make_service(tmp_path)
    target = "https://public.example/2026/post.html"
    assert service.post_get(target)["ok"]
    assert service.identity()["data"]["blog"] == "https://agent.micro.blog/"
    client.get_conversation.return_value = {
        "ok": True,
        "data": {"items": [{"id": 12, "url": target}]},
    }
    assert service.write("post_delete", "delete-12", {"identifier": "12"})["ok"]
    client.micropub_delete.assert_called_once_with(target)


@pytest.mark.parametrize(
    "target",
    [
        "https://other.example/post",
        "https://agent.micro.blog.evil.example/post",
        "https://user@agent.micro.blog/post",
        "https://agent.micro.blog/blog/../other/post",
        "https://agent.micro.blog/blog/%2e%2e/other/post",
        "https://agent.micro.blog/blog/%252e%252e/other/post",
        "https://agent.micro.blog/blog/%5c../other/post",
    ],
)
def test_foreign_or_traversing_targets_never_reach_source_or_write(tmp_path, target):
    service, client = make_service(tmp_path, blog="https://agent.micro.blog/blog/")
    assert service.post_get(target)["code"] == 403
    assert service.write("post_delete", "refused", {"identifier": target})["code"] == 403
    client.micropub_get.assert_not_called()
    client.micropub_delete.assert_not_called()
    assert not service.state.path.exists()


def test_ambiguous_custom_hostname_is_not_an_ownership_alias(tmp_path):
    service, client = make_service(
        tmp_path,
        destinations=[
            {"uid": "https://agent.micro.blog/", "name": "public.example"},
            {"uid": "https://second.micro.blog/", "name": "public.example"},
        ],
    )
    assert service.post_get("https://public.example/post")["code"] == 403
    client.micropub_get.assert_not_called()


@pytest.mark.parametrize(
    "payload", [{"error": "temporary failure"}, {}, {"items": None}, {"items": [None]}]
)
def test_bad_feed_page_never_yields_ack_receipt(tmp_path, payload):
    def response(request):
        if request.url.path == "/account/verify":
            return httpx.Response(200, json={"username": "agent"})
        if request.url.path == "/micropub":
            return httpx.Response(200, json={"destination": [{"uid": "https://agent.micro.blog/"}]})
        return httpx.Response(200, json=payload)

    with MicroblogClient("synthetic") as client:
        client._client.close()
        client._client = httpx.Client(
            transport=httpx.MockTransport(response), base_url="https://micro.blog"
        )
        service = MicroblogService(client, "default", None, "dot", tmp_path / "state.sqlite")
        assert service.attention("catchup")["code"] == 502
        assert service._receipts == {}
        assert not service.state.path.exists()


def test_unsorted_pages_use_lowest_id_and_exhaust_all_items(tmp_path):
    service, client = make_service(tmp_path)
    calls = []
    pages = [[9, 10], [7, 8], [5, 6], []]

    def page(**kwargs):
        calls.append(kwargs.get("before_id"))
        return {"ok": True, "data": {"items": [{"id": i} for i in pages.pop(0)]}}

    client.get_timeline.side_effect = page
    cursor = None
    seen = []
    for _ in range(4):
        result = service.attention("catchup", count=2, cursor=cursor)["data"]
        seen += [item["id"] for item in result["items"]]
        cursor = result["next_cursor"]
        if cursor is None:
            break
        assert result["ack_receipt"] is None
    assert seen == ["10", "9", "8", "7", "6", "5"]
    assert calls == [None, 9, 7, 5]
    assert service.acknowledge(result["ack_receipt"])["data"]["checkpoint"] == "10"


@pytest.mark.parametrize("items", [[{"id": "bad"}], [{"id": 1}, {"id": 1}], [None]])
def test_invalid_ids_do_not_create_receipts(tmp_path, items):
    service, client = make_service(tmp_path)
    client.get_timeline.return_value = {"ok": True, "data": {"items": items}}
    assert service.attention("catchup")["code"] == 502
    assert not service._receipts


@pytest.mark.parametrize("family", ["reply", "create", "delete"])
def test_200_error_write_stays_unknown_and_is_not_resent(tmp_path, family):
    requests = []

    def response(request):
        if request.url.path == "/account/verify":
            return httpx.Response(200, json={"username": "agent"})
        if request.method == "GET" and request.url.path == "/micropub":
            if request.url.params.get("q") == "config":
                return httpx.Response(
                    200, json={"destination": [{"uid": "https://agent.micro.blog/"}]}
                )
            return httpx.Response(200, json={"properties": {}})
        if request.url.path == "/posts/conversation":
            return httpx.Response(
                200, json={"items": [{"id": 12, "author": {"_microblog": {"username": "alice"}}}]}
            )
        requests.append(request)
        return httpx.Response(200, json={"error": "temporary failure"})

    with MicroblogClient("synthetic") as client:
        client._client.close()
        client._client = httpx.Client(
            transport=httpx.MockTransport(response), base_url="https://micro.blog"
        )
        service = MicroblogService(client, "default", None, "dot", tmp_path / "state.sqlite")
        arguments = (
            {"post_id": "12", "content": "hello"}
            if family == "reply"
            else {"content": "hello"}
            if family == "create"
            else {"identifier": "https://agent.micro.blog/post"}
        )
        first = service.write("post_" + family, "error-1", arguments)
        assert not first["ok"] and first["outcome"] == "unknown"
        assert service.write("post_" + family, "error-1", arguments)["outcome"] == "unknown"
        assert service.operation_status("error-1")["outcome"] == "unknown"
        assert len(requests) == 1


def test_create_missing_location_unknown_but_empty_delete_succeeds():
    with MicroblogClient("synthetic") as client:
        client._client.close()
        client._client = httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(201)),
            base_url="https://micro.blog",
        )
        assert client.micropub_create(content="hello")["outcome"] == "unknown"
        assert client.micropub_delete("https://agent.micro.blog/post")["ok"]


def test_recovery_metadata_does_not_persist_echoed_token(tmp_path):
    service, client = make_service(tmp_path)
    client.micropub_create.return_value = {
        "ok": True,
        "data": {
            "url": "https://agent.micro.blog/synthetic-secret",
            "id": "synthetic-secret",
            "content": "private body",
        },
    }
    assert service.write("post_create", "echo", {"content": "private body"})["ok"]
    assert service.operation_status("echo")["data"] == {}
    raw = service.state.path.read_bytes()
    assert b"synthetic-secret" not in raw and b"private body" not in raw


def test_profile_aliases_share_identity_state_but_other_principals_do_not(tmp_path):
    first, client = make_service(tmp_path)
    first.identity()
    first.state.acknowledge(first._scope("catchup"), "10", 0)
    client.micropub_create.return_value = {
        "ok": True,
        "data": {"url": "https://public.example/post"},
    }
    first.write("post_create", "created", {"content": "hello"})
    alias, alias_client = make_service(tmp_path, profile="alias")
    alias.identity()
    assert alias.state.cursor(alias._scope("catchup")) == ("10", 1)
    assert alias.write("post_create", "created", {"content": "hello"})["ok"]
    alias_client.micropub_create.assert_not_called()
    other, other_client = make_service(tmp_path, username="other", profile="other")
    other.identity()
    assert other.state.cursor(other._scope("catchup")) == (None, 0)
    assert other.operation_status("created")["code"] == 404
    other_client.micropub_create.assert_not_called()


def test_unknown_native_reply_is_shared_across_blog_profiles(tmp_path):
    first, client = make_service(tmp_path)
    client.get_conversation.return_value = {
        "ok": True,
        "data": {"items": [{"id": 12, "author": {"_microblog": {"username": "alice"}}}]},
    }
    client.post_reply.return_value = {
        "ok": False,
        "code": 599,
        "error": "network_error",
        "outcome": "unknown",
    }
    args = {"post_id": "12", "content": "hello"}
    assert first.write("post_reply", "reply-1", args)["outcome"] == "unknown"
    second, second_client = make_service(
        tmp_path, blog="https://second.micro.blog/", profile="second"
    )
    assert second.operation_status("reply-1")["outcome"] == "unknown"
    assert second.write("post_reply", "reply-1", args)["outcome"] == "unknown"
    second_client.get_conversation.assert_not_called()
    second_client.post_reply.assert_not_called()
    assert second.operation_status("nonexistent")["code"] == 404


def test_custom_url_selection_resolves_to_native_uid(tmp_path):
    service, client = make_service(tmp_path)
    service.requested_blog = "https://public.example/"
    assert service.identity()["data"]["blog"] == "https://agent.micro.blog/"
    assert client.default_destination == "https://agent.micro.blog/"


def test_different_destination_keeps_read_and_publication_state_separate(tmp_path):
    first, client = make_service(tmp_path)
    first.identity()
    first.state.acknowledge(first._scope("catchup"), "10", 0)
    client.micropub_create.return_value = {
        "ok": True,
        "data": {"url": "https://public.example/post"},
    }
    first.write("post_create", "created", {"content": "hello"})
    second, second_client = make_service(
        tmp_path, blog="https://second.micro.blog/", profile="second"
    )
    second.identity()
    assert second.state.cursor(second._scope("catchup")) == (None, 0)
    assert second.operation_status("created")["code"] == 404
    second_client.micropub_create.assert_not_called()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="bad response"),
        httpx.Response(200, json=["unexpected"]),
        httpx.Response(302, headers={"Location": "https://micro.blog/signin"}),
        httpx.Response(201, json={"url": "not-a-url"}),
    ],
)
def test_malformed_write_confirmation_is_unknown(response):
    with MicroblogClient("synthetic") as client:
        client._client.close()
        client._client = httpx.Client(
            transport=httpx.MockTransport(lambda r: response), base_url="https://micro.blog"
        )
        result = client.micropub_create(content="hello")
        assert not result["ok"] and result["outcome"] == "unknown"


def test_malformed_source_is_not_proof_of_ownership():
    with MicroblogClient("synthetic") as client:
        client._client.close()
        client._client = httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
            base_url="https://micro.blog",
        )
        assert client.micropub_get("https://agent.micro.blog/post")["code"] == 502
