"""Shared fixtures for tests — mock HTTP transport for micro.blog API."""

import json

import httpx
import pytest

from mb.api import MicroblogClient

# ── Sample response data ────────────────────────────────────

VERIFY_RESPONSE = {
    "username": "testuser",
    "name": "Test User",
    "url": "https://testuser.micro.blog/",
    "avatar": "https://micro.blog/testuser/avatar.jpg",
}

TIMELINE_ITEMS = [
    {
        "id": 12345,
        "content_html": "<p>Hello from <b>micro.blog</b>!</p>",
        "date_published": "2026-02-28T12:00:00+00:00",
        "url": "https://testuser.micro.blog/2026/02/28/hello.html",
        "author": {
            "name": "testuser",
            "url": "https://micro.blog/testuser",
            "avatar": "https://micro.blog/testuser/avatar.jpg",
        },
    },
    {
        "id": 12346,
        "content_html": "<p>Another post here.</p>",
        "date_published": "2026-02-28T11:00:00+00:00",
        "url": "https://otheruser.micro.blog/2026/02/28/another.html",
        "author": {
            "name": "otheruser",
            "url": "https://micro.blog/otheruser",
            "avatar": "https://micro.blog/otheruser/avatar.jpg",
        },
    },
]

MICROPUB_LIST_RESPONSE = {
    "items": [
        {
            "type": ["h-entry"],
            "properties": {
                "name": ["My Post"],
                "content": ["Hello world"],
                "published": ["2026-02-28T12:00:00+00:00"],
                "url": ["https://testuser.micro.blog/2026/02/28/hello.html"],
            },
            "url": "https://testuser.micro.blog/2026/02/28/hello.html",
        }
    ]
}

CONVERSATION_RESPONSE = {
    "items": [
        {
            "id": 100,
            "content_html": "<p>Root post</p>",
            "date_published": "2026-02-28T10:00:00+00:00",
            "author": {"name": "alice"},
            "_microblog": {},
        },
        {
            "id": 101,
            "content_html": "<p>Reply to root</p>",
            "date_published": "2026-02-28T10:05:00+00:00",
            "author": {"name": "bob"},
            "_microblog": {"reply_to_id": 100},
        },
        {
            "id": 102,
            "content_html": "<p>Reply to reply</p>",
            "date_published": "2026-02-28T10:10:00+00:00",
            "author": {"name": "alice"},
            "_microblog": {"reply_to_id": 101},
        },
    ]
}

CHECK_RESPONSE = {
    "count": 3,
    "check_seconds": 30,
}


def _make_handler(routes: dict):
    """Create an httpx transport handler from a route dict."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method

        # Rate limit test route
        if path == "/rate-limited":
            return httpx.Response(429, headers={"Retry-After": "60"})

        # Auth failure test route
        if request.headers.get("Authorization") == "Bearer bad-token":
            return httpx.Response(401, json={"error": "Unauthorized"})

        key = (method, path)
        if key in routes:
            status, body, headers = routes[key]
            if isinstance(body, (dict, list)):
                return httpx.Response(status, json=body, headers=headers)
            return httpx.Response(status, text=body, headers=headers)

        return httpx.Response(404, json={"error": "Not found"})

    return handler


@pytest.fixture
def mock_client():
    """Return a MicroblogClient backed by a mock transport."""
    routes = {
        ("GET", "/posts/account/verify"): (200, VERIFY_RESPONSE, {}),
        ("GET", "/posts/all"): (200, {"items": TIMELINE_ITEMS}, {}),
        ("GET", "/posts/mentions"): (200, {"items": TIMELINE_ITEMS[:1]}, {}),
        ("GET", "/posts/photos"): (200, {"items": TIMELINE_ITEMS}, {}),
        ("GET", "/posts/discover"): (200, {"items": TIMELINE_ITEMS}, {}),
        ("GET", "/posts/discover/books"): (200, {"items": TIMELINE_ITEMS[:1]}, {}),
        ("GET", "/posts/conversation"): (200, CONVERSATION_RESPONSE, {}),
        ("GET", "/posts/check"): (200, CHECK_RESPONSE, {}),
        ("GET", "/posts/testuser"): (200, {
            "username": "testuser",
            "name": "Test User",
            "avatar": "https://micro.blog/testuser/avatar.jpg",
            "items": TIMELINE_ITEMS[:1],
        }, {}),
        ("GET", "/users/following/testuser"): (200, [
            {"username": "alice"}, {"username": "bob"},
        ], {}),
        ("GET", "/users/is-following/alice"): (200, {"is_following": True}, {}),
        ("POST", "/users/follow"): (200, {}, {}),
        ("POST", "/users/unfollow"): (200, {}, {}),
        ("POST", "/users/mute"): (200, {}, {}),
        ("GET", "/users/muting"): (200, [{"id": 1, "username": "spammer"}], {}),
        ("POST", "/users/unmute"): (200, {}, {}),
        ("POST", "/users/block"): (200, {}, {}),
        ("GET", "/users/blocking"): (200, [{"id": 1, "username": "troll"}], {}),
        ("POST", "/users/unblock"): (200, {}, {}),
        ("POST", "/micropub"): (
            201,
            "",
            {"Location": "https://testuser.micro.blog/2026/02/28/newpost.html"},
        ),
        ("GET", "/micropub"): (200, MICROPUB_LIST_RESPONSE, {}),
    }
    transport = httpx.MockTransport(_make_handler(routes))
    client = MicroblogClient(token="test-token", base_url="https://micro.blog")
    client._client = httpx.Client(
        transport=transport,
        base_url="https://micro.blog",
        headers={"Authorization": "Bearer test-token"},
    )
    return client


@pytest.fixture
def rate_limited_client():
    """Return a client that always gets rate-limited."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "60"})

    transport = httpx.MockTransport(handler)
    client = MicroblogClient(token="test-token", base_url="https://micro.blog")
    client._client = httpx.Client(
        transport=transport,
        base_url="https://micro.blog",
        headers={"Authorization": "Bearer test-token"},
    )
    return client


@pytest.fixture
def auth_failure_client():
    """Return a client with a bad token."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "Unauthorized"})

    transport = httpx.MockTransport(handler)
    client = MicroblogClient(token="bad-token", base_url="https://micro.blog")
    client._client = httpx.Client(
        transport=transport,
        base_url="https://micro.blog",
        headers={"Authorization": "Bearer bad-token"},
    )
    return client
