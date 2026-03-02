"""Tests for new agent-oriented features: post edit, post get, memory forget,
search+category fix, agent output with categories, and @username extraction."""

import json

from mb.commands import _micropub_item_url
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
            categories=["memory", "core-memory"],
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
        result = mock_client.search_blog("testuser", query="hello", category="memory")
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
                            "categories": ["preferences", "core-memory"],
                        },
                    }
                ]
            },
        }
        output_agent(data)
        captured = capsys.readouterr()
        assert "[preferences, core-memory]" in captured.out
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
