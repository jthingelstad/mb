"""Subprocess fixture: actual mb mcp command with synthetic HTTP and isolated config."""

import json
import os
from pathlib import Path
from urllib.parse import parse_qs

import httpx

from mb import config
from mb.api import MicroblogClient
from mb.cli import app

BLOG = "https://agent.example/"
config.CONFIG_DIR = Path(os.environ["MB_TEST_DIR"])
config.CONFIG_FILE = config.CONFIG_DIR / "config.toml"
os.environ["MB_TOKEN"] = "synthetic-never-a-real-token"
os.environ["MB_BLOG"] = BLOG
if os.environ.get("MB_TEST_MISSING_AUTH"):
    os.environ.pop("MB_TOKEN", None)
posts = {}


def response(request):
    if request.url.path == "/account/verify":
        return httpx.Response(200, json={"username": "agent", "default_site": "agent.example"})
    if request.url.path == "/micropub/media":
        return httpx.Response(202, headers={"Location": "https://agent.example/uploads/image.png"})
    if request.url.path == "/conversation.js":
        return httpx.Response(200, json={"items": [{"id": 10, "content_html": "Webmention reply"}]})
    if request.url.path in {"/posts/discover", "/posts/agent", "/posts/replies"}:
        return httpx.Response(
            200, json={"title": "Agent", "items": [{"id": 10, "content_html": "Account post"}]}
        )
    if request.url.path == "/posts/all":
        params = request.url.params
        since = int(params.get("since_id", "0"))
        before = int(params.get("before_id", "999"))
        items = [
            {"id": i, "content_html": f"post {i}", "author": {"name": "alice"}}
            for i in range(8, 0, -1)
            if since < i < before
        ]
        return httpx.Response(200, json={"items": items[: int(params.get("count", "20"))]})
    if request.url.path == "/posts/mentions":
        return httpx.Response(200, json={"items": [{"id": 8, "content_html": "@agent hello"}]})
    if request.url.path == "/posts/conversation":
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": int(request.url.params["id"]),
                        "url": BLOG + "post",
                        "author": {"name": "alice"},
                    }
                ]
            },
        )
    if request.url.path == "/posts/reply":
        return httpx.Response(200, json={"id": 9})
    if request.method == "GET":
        query = request.url.params.get("q")
        if query == "category":
            return httpx.Response(200, json={"categories": ["photos"]})
        if query == "config":
            return httpx.Response(200, json={"destination": [{"uid": BLOG}]})
        if "url" in request.url.params:
            url = request.url.params["url"]
            return httpx.Response(200, json=posts[url]) if url in posts else httpx.Response(404)
        return httpx.Response(200, json={"items": list(posts.values())})
    if request.method == "POST":
        if request.content.startswith(b"{"):
            payload = json.loads(request.content)
            action = payload["action"]
            url = payload["url"]
            if action == "delete":
                posts.pop(url, None)
            elif action == "update":
                posts[url]["properties"].update(payload["replace"])
            return httpx.Response(204)
        payload = parse_qs(request.content.decode())
        if payload.get("action") == ["delete"]:
            posts.pop(payload["url"][0], None)
            return httpx.Response(204)
        url = BLOG + "post"
        posts[url] = {
            "type": ["h-entry"],
            "properties": {
                "url": [url],
                "content": payload["content"],
                "post-status": payload.get("post-status", ["published"]),
                **(
                    {"photo": payload["photo"], "mp-photo-alt": payload["mp-photo-alt"]}
                    if "photo" in payload
                    else {}
                ),
            },
        }
        return httpx.Response(201, headers={"Location": url})
    raise AssertionError("Unexpected request")


def client_factory(token):
    client = MicroblogClient(token)
    client._client.close()
    client._client = httpx.Client(
        base_url="https://micro.blog", transport=httpx.MockTransport(response)
    )
    return client


import mb.cli  # noqa: E402

mb.cli.MicroblogClient = client_factory
app()
