"""Compact result shapes, published schemas, inbox rebaseline and heartbeat paging."""

from unittest.mock import Mock

import jsonschema
import pytest

from mb import config
from mb.api import MicroblogClient
from mb.services import MicroblogService
from mb.shapes import (
    DATA_SCHEMAS,
    EXCERPT_CHARS,
    SCHEMA_VERSION,
    compact,
    compact_post,
    output_schema,
)

BLOG = "https://agent.example/"

UPSTREAM_POST = {
    "id": "98671022",
    "content_html": '<p>New report <a href="https://example.com/">here</a></p>\n'
    '<img src="https://cdn.example/shot.png" alt="" loading="lazy">\n',
    "content_text": "New report here\n\n",
    "summary": "",
    "url": "https://example.com/2026/10/04/report.html",
    "date_published": "2026-10-05T02:17:36+00:00",
    "author": {
        "name": "Jamie",
        "url": "https://example.com/",
        "avatar": "https://cdn.example/avatar.jpg",
        "_microblog": {"username": "jamie"},
    },
    "_microblog": {"date_timestamp": 1791166656, "is_conversation": True, "is_mention": False},
    "author_username": "jamie",
}


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


def test_compact_post_keeps_text_author_images_and_flags():
    post = compact_post(UPSTREAM_POST)
    assert post == {
        "id": "98671022",
        "url": "https://example.com/2026/10/04/report.html",
        "author_username": "jamie",
        "author_name": "Jamie",
        "date_published": "2026-10-05T02:17:36+00:00",
        "content_text": "New report here",
        "links": ["https://example.com/"],
        "images": ["https://cdn.example/shot.png"],
        "is_conversation": True,
    }


def test_compact_drops_feed_noise_and_builds_profile():
    result = {
        "ok": True,
        "data": {
            "version": "https://jsonfeed.org/version/1",
            "title": "Micro.blog - Manton",
            "home_page_url": "https://micro.blog",
            "feed_url": "https://micro.blog/posts/manton",
            "_microblog": {"username": "manton", "bio": "Hi", "following_count": 3},
            "author": {"name": "Manton", "url": "https://manton.org", "avatar": "a.jpg"},
            "items": [UPSTREAM_POST],
            "returned_count": 1,
            "truncated": False,
            "coverage": "recent-user-posts",
            "coverage_complete": False,
            "scope": "account",
        },
    }
    data = compact("profile_get", result)["data"]
    assert set(data) == {
        "items",
        "returned_count",
        "truncated",
        "coverage",
        "coverage_complete",
        "scope",
        "profile",
    }
    assert data["profile"]["username"] == "manton"
    assert data["profile"]["following_count"] == 3
    assert "content_html" not in data["items"][0]
    jsonschema.validate({"schema_version": 1, **result}, output_schema("profile_get"))
    jsonschema.validate(
        {"schema_version": 1, **compact("profile_get", result)}, output_schema("profile_get")
    )


def test_source_posts_are_excerpts_with_a_truncation_flag():
    long = "word " * 300
    result = {
        "ok": True,
        "data": {
            "identity": {"username": "agent"},
            "items": [
                {
                    "id": "1",
                    "url": "https://agent.example/1.html",
                    "content_html": long,
                    "content_text": long,
                    "tags": ["notes"],
                    "_microblog": {"post_status": "draft"},
                }
            ],
            "returned_count": 1,
            "truncated": False,
            "coverage": "recent-source-window",
            "coverage_complete": False,
            "scope": "selected-blog",
        },
    }
    data = compact("blog_posts", result)["data"]
    assert "identity" not in data
    item = data["items"][0]
    assert len(item["content_text"]) == EXCERPT_CHARS
    assert item["content_truncated"] is True
    assert item["status"] == "draft" and item["tags"] == ["notes"]


def test_categories_compact_to_names():
    result = {
        "ok": True,
        "data": {
            "categories": ["agents"],
            "microblog-categories": [{"uid": 1, "name": "agents"}],
            "identity": {},
            "scope": "selected-blog",
        },
    }
    assert compact("blog_categories", result)["data"] == {
        "categories": ["agents"],
        "scope": "selected-blog",
    }


@pytest.mark.parametrize("tool", ["timeline", "post_create", "identity", "operation_status"])
def test_failures_and_non_read_results_pass_through(tool):
    failed = {"ok": False, "error": "nope", "code": 404}
    assert compact(tool, failed) == failed
    if tool != "timeline":
        written = {"ok": True, "data": {"url": "https://agent.example/1.html", "extra": 1}}
        assert compact(tool, written) == written


def test_every_tool_publishes_a_valid_versioned_schema():
    from mb.mcp_server import CATALOG

    assert set(CATALOG) == set(DATA_SCHEMAS)
    for tool in CATALOG:
        schema = output_schema(tool)
        jsonschema.Draft202012Validator.check_schema(schema)
        assert schema["properties"]["schema_version"] == {"const": SCHEMA_VERSION}
        jsonschema.validate({"schema_version": 1, "ok": False, "error": "x", "code": 400}, schema)


def test_inbox_rebaseline_recovers_an_aged_out_anchor(service, client):
    service.identity()
    scope = service._scope("inbox")
    service.state.acknowledge(scope, "10", 0)
    client.get_mentions.return_value = {"ok": True, "data": {"items": [{"id": 30}, {"id": 29}]}}

    stuck = service.attention("inbox")["data"]
    assert stuck["anchor_missing"] is True and stuck["rebaselined"] is False
    assert stuck["ack_receipt"] is None

    recovered = service.attention("inbox", rebaseline=True)["data"]
    assert recovered["anchor_missing"] is True and recovered["rebaselined"] is True
    assert recovered["coverage_complete"] is True
    acknowledged = service.acknowledge(recovered["ack_receipt"])
    assert acknowledged["data"]["rebaselined"] is True
    assert acknowledged["data"]["previous_checkpoint"] == "10"
    assert service.state.cursor(scope) == ("30", 2)

    # Once rebaselined, the normal path completes without the flag.
    client.get_mentions.return_value = {
        "ok": True,
        "data": {"items": [{"id": 31}, {"id": 30}]},
    }
    after = service.attention("inbox")["data"]
    assert after["anchor_missing"] is False and after["ack_receipt"]


def test_rebaseline_is_a_no_op_while_the_anchor_is_present(service, client):
    service.identity()
    service.state.acknowledge(service._scope("inbox"), "29", 0)
    client.get_mentions.return_value = {"ok": True, "data": {"items": [{"id": 30}, {"id": 29}]}}
    data = service.attention("inbox", rebaseline=True)["data"]
    assert data["rebaselined"] is False
    assert "rebaselined" not in service.acknowledge(data["ack_receipt"])["data"]


def test_rebaseline_never_acknowledges_on_a_read_only_server(client, tmp_path):
    service = MicroblogService(
        client, "default", BLOG, "dot", tmp_path / "state.sqlite", read_only=True
    )
    service.identity()
    service.state.acknowledge(service._scope("inbox"), "10", 0)
    client.get_mentions.return_value = {"ok": True, "data": {"items": [{"id": 30}]}}
    receipt = service.attention("inbox", rebaseline=True)["data"]["ack_receipt"]
    assert service.acknowledge(receipt)["code"] == 403
    assert service.state.cursor(service._scope("inbox")) == ("10", 1)


def test_heartbeat_pages_three_first_then_twenty(service, client):
    calls = []

    def page(count=20, since_id=None, before_id=None):
        calls.append(count)
        return {"ok": True, "data": {"items": []}}

    client.get_timeline.side_effect = page
    service.heartbeat()
    assert calls[0] == 3
    service.state.acknowledge(service._scope("heartbeat"), "5", 0)
    calls.clear()
    service.heartbeat()
    assert calls[0] == 20
    calls.clear()
    service.heartbeat(count=7)
    assert calls[0] == 7


def test_state_path_keeps_the_2_0_file_until_a_new_one_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    assert config.default_state_path() == tmp_path / "state.sqlite3"
    (tmp_path / "mcp-state.sqlite3").write_bytes(b"")
    assert config.default_state_path() == tmp_path / "mcp-state.sqlite3"
    (tmp_path / "state.sqlite3").write_bytes(b"")
    assert config.default_state_path() == tmp_path / "state.sqlite3"


def test_published_schema_document_is_current():
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("export", root / "scripts/export_schemas.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert (root / "docs/mcp-schemas.json").read_text() == module.render(), (
        "run: uv run python scripts/export_schemas.py"
    )
