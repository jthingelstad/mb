"""Tests for output formatters."""

import json

from mb.formatters import strip_html, output_json, output_agent


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
