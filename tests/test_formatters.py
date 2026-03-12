"""Tests for output formatters."""

import json

from mb.formatters import strip_html, output_json, output_agent, output_human


class TestStripHtml:
    def test_removes_tags(self):
        assert strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_no_tags(self):
        assert strip_html("plain text") == "plain text"

    def test_empty(self):
        assert strip_html("") == ""

    def test_nested_tags(self):
        assert strip_html("<div><p><a href='#'>link</a></p></div>") == "link"


class TestOutputJson:
    def test_success_output(self, capsys):
        output_json({"ok": True, "data": {"id": "123"}})
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["ok"] is True
        assert parsed["data"]["id"] == "123"

    def test_error_output(self, capsys):
        output_json({"ok": False, "error": "not found", "code": 404})
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["ok"] is False
        assert parsed["code"] == 404


class TestOutputAgent:
    def test_timeline_output(self, capsys):
        data = {
            "ok": True,
            "data": {
                "items": [
                    {
                        "id": 12345,
                        "content_html": "<p>Hello world</p>",
                        "date_published": "2026-02-28T12:00:00+00:00",
                        "author": {"name": "testuser"},
                    }
                ]
            },
        }
        output_agent(data)
        captured = capsys.readouterr()
        assert "[12345]" in captured.out
        assert "@testuser" in captured.out
        assert "Hello world" in captured.out

    def test_error_output(self, capsys):
        output_agent({"ok": False, "error": "bad request"})
        captured = capsys.readouterr()
        assert "ERROR:" in captured.out

    def test_single_result(self, capsys):
        output_agent({"ok": True, "data": {"id": "abc", "url": "https://example.com"}})
        captured = capsys.readouterr()
        assert "OK id=abc" in captured.out

    def test_list_payload(self, capsys):
        """Agent format handles list payloads (e.g. following, muting)."""
        data = {"ok": True, "data": [
            {"username": "alice"}, {"username": "bob"},
        ]}
        output_agent(data)
        captured = capsys.readouterr()
        assert "@alice" in captured.out
        assert "@bob" in captured.out

    def test_filtered_users_payload(self, capsys):
        data = {"ok": True, "data": {
            "users": [
                {"username": "alice", "inactive_days": 90, "last_post_date": "2026-01-01T00:00:00+00:00", "last_post_content_text": "Hello world"},
            ],
            "errors": [],
        }}
        output_agent(data)
        captured = capsys.readouterr()
        assert "@alice inactive_days=90 last_post=2026-01-01: Hello world" in captured.out

    def test_action_results_payload(self, capsys):
        data = {"ok": True, "data": {
            "action": "follow",
            "results": [{"username": "alice", "ok": True}],
        }}
        output_agent(data)
        captured = capsys.readouterr()
        assert "@alice ok" in captured.out


class TestOutputHuman:
    def test_list_payload(self, capsys):
        """Human format handles list payloads without crashing."""
        data = {"ok": True, "data": [
            {"username": "alice"}, {"username": "bob"},
        ]}
        output_human(data)
        captured = capsys.readouterr()
        assert "@alice" in captured.out
        assert "@bob" in captured.out

    def test_empty_list_payload(self, capsys):
        """Human format handles empty list payloads gracefully."""
        data = {"ok": True, "data": []}
        output_human(data)
        captured = capsys.readouterr()
        assert "No items" in captured.out

    def test_filtered_users_payload(self, capsys):
        data = {"ok": True, "data": {
            "users": [
                {"username": "alice", "inactive_days": 90, "last_post_date": "2026-01-01T00:00:00+00:00", "last_post_content_text": "Hello world"},
            ],
            "errors": [],
        }}
        output_human(data)
        captured = capsys.readouterr()
        assert "@alice" in captured.out
        assert "90d" in captured.out
        assert "Hello world" in captured.out

    def test_action_results_payload(self, capsys):
        data = {"ok": True, "data": {
            "action": "follow",
            "ok_count": 1,
            "error_count": 0,
            "results": [{"username": "alice", "ok": True}],
        }}
        output_human(data)
        captured = capsys.readouterr()
        assert "follow" in captured.out.lower()
        assert "@alice" in captured.out
