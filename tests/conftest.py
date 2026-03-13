"""Shared fixtures for tests — mock HTTP transport for micro.blog API."""

import json

import httpx
import pytest

from mb.api import MicroblogClient

# ── Sample response data ────────────────────────────────────

VERIFY_RESPONSE = {
    "username": "testuser",
    "full_name": "Test User",
    "default_site": "testuser.micro.blog",
    "gravatar_url": "https://micro.blog/testuser/avatar.jpg",
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

ALICE_ITEMS = [
    {
        "id": 20001,
        "content_html": "<p>Alice post</p>",
        "date_published": "2000-01-01T00:00:00+00:00",
        "url": "https://alice.micro.blog/2000/01/01/alice.html",
        "author": {
            "name": "alice",
            "url": "https://micro.blog/alice",
            "avatar": "https://micro.blog/alice/avatar.jpg",
        },
    }
]

BOB_ITEMS = [
    {
        "id": 20002,
        "content_html": "<p>Bob post</p>",
        "date_published": "2100-01-01T00:00:00+00:00",
        "url": "https://bob.micro.blog/2100/01/01/bob.html",
        "author": {
            "name": "bob",
            "url": "https://micro.blog/bob",
            "avatar": "https://micro.blog/bob/avatar.jpg",
        },
    }
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
            "url": "https://alice.micro.blog/2026/02/28/root.html",
            "date_published": "2026-02-28T10:00:00+00:00",
            "author": {"name": "alice", "url": "https://micro.blog/alice", "_microblog": {"username": "alice"}},
            "_microblog": {},
        },
        {
            "id": 101,
            "content_html": "<p>Reply to root</p>",
            "url": "https://bob.micro.blog/2026/02/28/reply.html",
            "date_published": "2026-02-28T10:05:00+00:00",
            "author": {"name": "bob", "url": "https://micro.blog/bob", "_microblog": {"username": "bob"}},
            "_microblog": {"reply_to_id": 100},
        },
        {
            "id": 102,
            "content_html": "<p>Reply to reply</p>",
            "url": "https://alice.micro.blog/2026/02/28/reply2.html",
            "date_published": "2026-02-28T10:10:00+00:00",
            "author": {"name": "alice", "url": "https://micro.blog/alice", "_microblog": {"username": "alice"}},
            "_microblog": {"reply_to_id": 101},
        },
    ]
}

CHECK_RESPONSE = {
    "count": 3,
    "check_seconds": 30,
}

CATEGORIES_RESPONSE = {
    "categories": ["journal", "reference", "preferences"],
}

MICROPUB_CONFIG_RESPONSE = {
    "destination": [
        {"uid": "https://testuser.micro.blog/", "name": "testuser"},
        {"uid": "https://testblog.micro.blog/", "name": "testblog"},
    ],
}


MICROPUB_SOURCE_RESPONSE = {
    "type": ["h-entry"],
    "properties": {
        "name": ["My Post"],
        "content": ["Hello world"],
        "published": ["2026-02-28T12:00:00+00:00"],
        "url": ["https://testuser.micro.blog/2026/02/28/hello.html"],
        "category": ["journal", "preferences"],
    },
}


def _make_handler(routes: dict):
    """Create an httpx transport handler from a route dict."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        params = dict(request.url.params)

        # Rate limit test route
        if path == "/rate-limited":
            return httpx.Response(429, headers={"Retry-After": "60"})

        # Token verify endpoint
        if method == "POST" and path == "/account/verify":
            return httpx.Response(200, json=VERIFY_RESPONSE)

        # Auth failure test route
        if request.headers.get("Authorization") == "Bearer bad-token":
            return httpx.Response(401, json={"error": "Unauthorized"})

        # Micropub GET with different q= params
        if method == "GET" and path == "/micropub":
            q = params.get("q", "source")
            # Single post source query: ?q=source&url=...
            if q == "source" and "url" in params:
                return httpx.Response(200, json=MICROPUB_SOURCE_RESPONSE)
            q_key = ("GET", "/micropub", q)
            if q_key in routes:
                status, body, headers = routes[q_key]
                if isinstance(body, (dict, list)):
                    return httpx.Response(status, json=body, headers=headers)
                return httpx.Response(status, text=body, headers=headers)

        # Micropub POST — check for JSON body (update) vs form data (create/delete)
        if method == "POST" and path == "/micropub":
            content_type = request.headers.get("content-type", "")
            if "application/json" in content_type:
                body = json.loads(request.content)
                if body.get("action") == "update":
                    return httpx.Response(
                        200, text="",
                        headers={"Location": body.get("url", "")},
                    )

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
        ("GET", "/users/is_following"): (200, {"is_following": True, "is_you": False}, {}),
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
        ("GET", "/posts/alice"): (200, {
            "username": "alice",
            "name": "Alice",
            "avatar": "https://micro.blog/alice/avatar.jpg",
            "items": ALICE_ITEMS,
        }, {}),
        ("GET", "/posts/bob"): (200, {
            "username": "bob",
            "name": "Bob",
            "avatar": "https://micro.blog/bob/avatar.jpg",
            "items": BOB_ITEMS,
        }, {}),
        ("GET", "/users/following/testuser"): (200, [
            {"username": "alice"}, {"username": "bob"},
        ], {}),
        ("GET", "/users/discover/testuser"): (200, [
            {"username": "carol"}, {"username": "dave"},
        ], {}),
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
        ("POST", "/micropub/media"): (
            201,
            "",
            {"Location": "https://cdn.micro.blog/photos/example-upload.jpg"},
        ),
        ("GET", "/micropub", "source"): (200, MICROPUB_LIST_RESPONSE, {}),
        ("GET", "/micropub", "category"): (200, CATEGORIES_RESPONSE, {}),
        ("GET", "/micropub", "config"): (200, MICROPUB_CONFIG_RESPONSE, {}),
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
