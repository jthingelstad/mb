"""Tests for the API client layer."""

import httpx

from mb.api import MicroblogClient
from tests.conftest import TIMELINE_ITEMS, VERIFY_RESPONSE, CONVERSATION_RESPONSE


class TestVerifyToken:
    def test_success(self, mock_client):
        result = mock_client.verify_token()
        assert result["ok"] is True
        assert result["data"]["username"] == "testuser"

    def test_auth_failure(self, auth_failure_client):
        result = auth_failure_client.verify_token()
        assert result["ok"] is False
        assert result["code"] == 401

    def test_invalid_token_api_error(self):
        """API returns 200 with {"error": "..."} for invalid tokens."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"error": "App token was not valid."})

        transport = httpx.MockTransport(handler)
        client = MicroblogClient(token="bad", base_url="https://micro.blog")
        client._client = httpx.Client(transport=transport, base_url="https://micro.blog")
        result = client.verify_token()
        assert result["ok"] is False
        assert result["code"] == 401
        assert "not valid" in result["error"]


class TestTimeline:
    def test_get_timeline(self, mock_client):
        result = mock_client.get_timeline()
        assert result["ok"] is True
        items = result["data"]["items"]
        assert len(items) == 2
        assert items[0]["id"] == 12345

    def test_get_mentions(self, mock_client):
        result = mock_client.get_mentions()
        assert result["ok"] is True
        assert len(result["data"]["items"]) == 1

    def test_get_photos(self, mock_client):
        result = mock_client.get_photos()
        assert result["ok"] is True

    def test_get_discover(self, mock_client):
        result = mock_client.get_discover()
        assert result["ok"] is True

    def test_get_discover_collection(self, mock_client):
        result = mock_client.get_discover(collection="books")
        assert result["ok"] is True
        assert len(result["data"]["items"]) == 1

    def test_check_timeline(self, mock_client):
        result = mock_client.check_timeline(since_id=12340)
        assert result["ok"] is True
        assert result["data"]["count"] == 3


class TestConversation:
    def test_get_conversation(self, mock_client):
        result = mock_client.get_conversation(post_id=101)
        assert result["ok"] is True
        items = result["data"]["items"]
        assert len(items) == 3


class TestUser:
    def test_get_user(self, mock_client):
        result = mock_client.get_user("testuser")
        assert result["ok"] is True
        assert result["data"]["username"] == "testuser"

    def test_get_following(self, mock_client):
        result = mock_client.get_following("testuser")
        assert result["ok"] is True

    def test_get_user_discover(self, mock_client):
        result = mock_client.get_user_discover("testuser")
        assert result["ok"] is True
        assert len(result["data"]) == 2

    def test_is_following(self, mock_client):
        result = mock_client.is_following("alice")
        assert result["ok"] is True
        assert result["data"]["is_following"] is True

    def test_follow(self, mock_client):
        result = mock_client.follow("alice")
        assert result["ok"] is True

    def test_unfollow(self, mock_client):
        result = mock_client.unfollow("alice")
        assert result["ok"] is True

    def test_mute(self, mock_client):
        result = mock_client.mute("spammer")
        assert result["ok"] is True

    def test_get_muting(self, mock_client):
        result = mock_client.get_muting()
        assert result["ok"] is True

    def test_unmute(self, mock_client):
        result = mock_client.unmute(1)
        assert result["ok"] is True

    def test_block(self, mock_client):
        result = mock_client.block("troll")
        assert result["ok"] is True

    def test_get_blocking(self, mock_client):
        result = mock_client.get_blocking()
        assert result["ok"] is True

    def test_unblock(self, mock_client):
        result = mock_client.unblock(1)
        assert result["ok"] is True


class TestMicropub:
    def test_create_post(self, mock_client):
        result = mock_client.micropub_create(content="Hello world")
        assert result["ok"] is True
        assert "url" in result["data"]
        assert result["data"]["id"] == "newpost.html"

    def test_create_draft(self, mock_client):
        result = mock_client.micropub_create(content="Draft", draft=True)
        assert result["ok"] is True

    def test_delete_post(self, mock_client):
        result = mock_client.micropub_delete("https://testuser.micro.blog/2026/02/28/hello.html")
        assert result["ok"] is True

    def test_list_posts(self, mock_client):
        result = mock_client.micropub_list()
        assert result["ok"] is True
        assert "items" in result["data"]


class TestRateLimiting:
    def test_rate_limited_response(self, rate_limited_client):
        result = rate_limited_client.get_timeline()
        assert result["ok"] is False
        assert result["error"] == "rate_limited"
        assert result["retry_after"] == 60

    def test_rate_limited_micropub(self, rate_limited_client):
        result = rate_limited_client.micropub_create(content="test")
        assert result["ok"] is False
        assert result["error"] == "rate_limited"


class TestErrorMessages:
    def test_empty_error_body_has_fallback(self):
        """HTTP errors with empty bodies should include a fallback message."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="")

        transport = httpx.MockTransport(handler)
        client = MicroblogClient(token="test", base_url="https://micro.blog")
        client._client = httpx.Client(transport=transport, base_url="https://micro.blog")
        result = client._handle_response(httpx.Response(404, text=""))
        assert result["ok"] is False
        assert result["error"] == "HTTP 404 error"

    def test_empty_micropub_error_has_fallback(self):
        """Micropub errors with empty bodies should include a fallback message."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="")

        transport = httpx.MockTransport(handler)
        client = MicroblogClient(token="test", base_url="https://micro.blog")
        client._client = httpx.Client(transport=transport, base_url="https://micro.blog")
        result = client._handle_micropub_response(httpx.Response(404, text=""))
        assert result["ok"] is False
        assert result["error"] == "HTTP 404 error"
