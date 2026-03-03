"""Tests for new agent-oriented features: post edit, post get, notes forget,
search+category fix, agent output with categories, and @username extraction."""

import json

from mb.commands import _micropub_item_url, resolve_post_url, _extract_author_username
from mb.commands.post import _extract_post_id
from mb.formatters import _extract_username, output_agent


class TestMicropubUpdate:
    def test_update_content(self, mock_client):
        result = mock_client.micropub_update(
            "https://testuser.micro.blog/2026/02/28/hello.html",
            content="Updated content",
        )
        assert result["ok"] is True

    def test_update_title(self, mock_client):
        result = mock_client.micropub_update(
            "https://testuser.micro.blog/2026/02/28/hello.html",
            title="New Title",
        )
        assert result["ok"] is True

    def test_update_categories(self, mock_client):
        result = mock_client.micropub_update(
            "https://testuser.micro.blog/2026/02/28/hello.html",
            categories=["notes", "preferences"],
        )
        assert result["ok"] is True

    def test_update_nothing_returns_error(self, mock_client):
        result = mock_client.micropub_update(
            "https://testuser.micro.blog/2026/02/28/hello.html",
        )
        assert result["ok"] is False
        assert "Nothing to update" in result["error"]


class TestMicropubGet:
    def test_get_post(self, mock_client):
        result = mock_client.micropub_get(
            "https://testuser.micro.blog/2026/02/28/hello.html"
        )
        assert result["ok"] is True
        assert result["data"]["properties"]["content"] == ["Hello world"]
        assert "category" in result["data"]["properties"]


class TestSearchWithCategory:
    def test_search_blog_with_category(self, mock_client):
        result = mock_client.search_blog("testuser", query="hello", category="notes")
        assert result["ok"] is True

    def test_search_blog_without_category(self, mock_client):
        result = mock_client.search_blog("testuser", query="hello")
        assert result["ok"] is True


class TestMicropubItemUrl:
    def test_from_properties(self):
        """Extract URL from Micropub h-entry format."""
        item = {"type": "h-entry", "properties": {
            "url": ["https://blog.example/post.html"],
            "content": ["Hello"],
        }}
        assert _micropub_item_url(item) == "https://blog.example/post.html"

    def test_from_flat(self):
        """Extract URL from flat JSON Feed format."""
        item = {"id": "123", "url": "https://blog.example/post.html"}
        assert _micropub_item_url(item) == "https://blog.example/post.html"

    def test_empty_item(self):
        assert _micropub_item_url({}) == ""

    def test_properties_empty_url_list(self):
        item = {"properties": {"url": [], "content": ["Hello"]}}
        assert _micropub_item_url(item) == ""


class TestExtractPostId:
    def test_bare_numeric(self):
        assert _extract_post_id("85444185") == 85444185

    def test_microblog_url(self):
        assert _extract_post_id("https://micro.blog/alice/100") == 100

    def test_microblog_url_trailing_slash(self):
        assert _extract_post_id("https://micro.blog/alice/100/") == 100

    def test_blog_url_non_numeric(self):
        """Blog URLs with slug paths should return None."""
        assert _extract_post_id("https://alice.micro.blog/2026/02/28/hello.html") is None

    def test_non_numeric_string(self):
        assert _extract_post_id("not-a-number") is None


class TestExtractAuthorUsername:
    def test_from_microblog_extension(self):
        author = {"name": "Alice", "_microblog": {"username": "alice"}}
        assert _extract_author_username(author) == "alice"

    def test_from_url(self):
        author = {"name": "Alice", "url": "https://micro.blog/alice"}
        assert _extract_author_username(author) == "alice"

    def test_fallback_to_name(self):
        author = {"name": "alice"}
        assert _extract_author_username(author) == "alice"


class TestExtractUsername:
    def test_from_url(self):
        author = {"name": "Test User", "url": "https://micro.blog/testuser"}
        assert _extract_username(author) == "testuser"

    def test_from_url_with_trailing_slash(self):
        author = {"name": "Test User", "url": "https://micro.blog/testuser/"}
        assert _extract_username(author) == "testuser"

    def test_fallback_to_name(self):
        author = {"name": "testuser"}
        assert _extract_username(author) == "testuser"

    def test_empty_author(self):
        assert _extract_username({}) == "?"


class TestAgentOutputWithCategories:
    def test_categories_in_output(self, capsys):
        data = {
            "ok": True,
            "data": {
                "items": [
                    {
                        "id": 12345,
                        "content_html": "<p>User prefers dark mode</p>",
                        "date_published": "2026-02-28T12:00:00+00:00",
                        "author": {"name": "agent", "url": "https://micro.blog/agent"},
                        "_microblog": {
                            "categories": ["preferences", "notes"],
                        },
                    }
                ]
            },
        }
        output_agent(data)
        captured = capsys.readouterr()
        assert "[preferences, notes]" in captured.out
        assert "@agent" in captured.out

    def test_no_categories(self, capsys):
        data = {
            "ok": True,
            "data": {
                "items": [
                    {
                        "id": 12345,
                        "content_html": "<p>Hello</p>",
                        "date_published": "2026-02-28T12:00:00+00:00",
                        "author": {"name": "testuser", "url": "https://micro.blog/testuser"},
                    }
                ]
            },
        }
        output_agent(data)
        captured = capsys.readouterr()
        assert "[12345] @testuser" in captured.out
        # No category brackets when no categories
        assert "[]" not in captured.out

    def test_username_from_url_not_name(self, capsys):
        data = {
            "ok": True,
            "data": {
                "items": [
                    {
                        "id": 99,
                        "content_html": "<p>Post</p>",
                        "date_published": "2026-02-28T12:00:00+00:00",
                        "author": {
                            "name": "John Smith",
                            "url": "https://micro.blog/johnsmith",
                        },
                    }
                ]
            },
        }
        output_agent(data)
        captured = capsys.readouterr()
        assert "@johnsmith" in captured.out
        assert "@John Smith" not in captured.out


class TestResolvePostUrl:
    def test_full_url_passthrough(self, mock_client):
        url = resolve_post_url(mock_client, "https://example.com/post.html", "json")
        assert url == "https://example.com/post.html"

    def test_bare_numeric_id_resolves_via_conversation(self, mock_client):
        """Bare numeric ID should resolve to the post's blog URL via conversation API."""
        url = resolve_post_url(mock_client, "100", "json")
        assert url == "https://alice.micro.blog/2026/02/28/root.html"

    def test_bare_numeric_id_different_post(self, mock_client):
        url = resolve_post_url(mock_client, "101", "json")
        assert url == "https://bob.micro.blog/2026/02/28/reply.html"

    def test_bare_numeric_id_not_found_exits(self, mock_client):
        import pytest
        with pytest.raises(SystemExit):
            resolve_post_url(mock_client, "99999", "json")

    def test_slug_falls_back_to_micropub(self, mock_client):
        """Non-numeric identifiers should still use micropub listing suffix match."""
        url = resolve_post_url(mock_client, "hello.html", "json")
        assert url == "https://testuser.micro.blog/2026/02/28/hello.html"


class TestAgentOutputDepth:
    def test_depth_indentation(self, capsys):
        data = {
            "ok": True,
            "data": {
                "items": [
                    {
                        "id": 100, "depth": 0,
                        "content_html": "<p>Root post</p>",
                        "date_published": "2026-02-28T10:00:00+00:00",
                        "author": {"name": "alice", "url": "https://micro.blog/alice"},
                    },
                    {
                        "id": 101, "depth": 1,
                        "content_html": "<p>Reply to root</p>",
                        "date_published": "2026-02-28T10:05:00+00:00",
                        "author": {"name": "bob", "url": "https://micro.blog/bob"},
                    },
                    {
                        "id": 102, "depth": 2,
                        "content_html": "<p>Reply to reply</p>",
                        "date_published": "2026-02-28T10:10:00+00:00",
                        "author": {"name": "alice", "url": "https://micro.blog/alice"},
                    },
                ]
            },
        }
        output_agent(data)
        lines = capsys.readouterr().out.strip().split("\n")
        assert lines[0].startswith("[100]")
        assert lines[1].startswith("  [101]")
        assert lines[2].startswith("    [102]")

    def test_no_depth_key_no_indent(self, capsys):
        """Items without depth key should have no indentation (backwards compatible)."""
        data = {
            "ok": True,
            "data": {
                "items": [
                    {
                        "id": 200,
                        "content_html": "<p>Normal post</p>",
                        "date_published": "2026-02-28T12:00:00+00:00",
                        "author": {"name": "test", "url": "https://micro.blog/test"},
                    },
                ]
            },
        }
        output_agent(data)
        captured = capsys.readouterr()
        assert captured.out.startswith("[200]")
