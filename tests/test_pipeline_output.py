"""Pipe-friendly output, stdin parsing and verified destinations for legacy reads."""

import json
from unittest.mock import Mock, patch

from typer.testing import CliRunner

from mb.cli import app
from mb.formatters import output
from tests.test_cli_write_safety import BLOG, URL, Harness

runner = CliRunner()


def test_agent_coverage_metadata_goes_to_stderr(capsys):
    result = {
        "ok": True,
        "data": {
            "coverage": "recent-source-window",
            "coverage_complete": False,
            "items": [{"id": 1, "content_text": "Hello", "author": {"name": "a"}}],
        },
    }
    output(result, "agent")
    captured = capsys.readouterr()
    assert "coverage=" not in captured.out and captured.out.startswith("[1]")
    assert captured.err.startswith("coverage=recent-source-window complete=false")
    output(result, "json")
    assert json.loads(capsys.readouterr().out)["data"]["coverage"] == "recent-source-window"


def lookup_users(args, input=None, results=None):
    seen = []

    def fetch(token, base_url, username, last_post, days):
        seen.append(username)
        if results and username in results:
            return results[username]
        return {"ok": True, "username": username, "inactive_days": 1}

    client = Mock(token="synthetic", base_url="https://micro.blog")
    with (
        patch("mb.commands.lookup.get_client", return_value=client),
        patch("mb.commands.lookup._fetch_user_lookup", side_effect=fetch),
    ):
        result = runner.invoke(app, ["lookup", "users", "--days-since-posting", *args], input=input)
    return result, seen


def test_lookup_users_stdin_skips_blank_and_comment_lines():
    result, seen = lookup_users([], input="alice\n\n# reviewed list\n   # indented\n@bob: hi\n")
    assert result.exit_code == 0 and seen == ["alice", "bob"]


def test_lookup_users_errors_go_to_stderr_and_fail_the_pipeline():
    failed = {"bob": {"ok": False, "username": "bob", "error": "not_found", "code": 404}}
    result, _ = lookup_users(["alice", "bob"], results=failed)
    assert result.exit_code == 1
    assert result.stdout == "@alice inactive_days=1\n"
    assert result.stderr == "@bob error=not_found\n"


def test_follow_stdin_skips_comment_lines():
    from mb.commands.user import _read_usernames_from_stdin

    with patch("sys.stdin", ["# header\n", "\n", "carol\n"]):
        assert _read_usernames_from_stdin() == ["carol"]


def lookup_posts(args, input=None, identity=None):
    calls = []

    def fetch(token, base_url, identifier, post, conversation, destination=None):
        calls.append((identifier, destination))
        if identifier == "404":
            return {"ok": False, "identifier": identifier, "error": "missing", "code": 404}
        return {"ok": True, "identifier": identifier, "id": "1", "url": identifier}

    service = Mock()
    service.identity.return_value = identity or {
        "ok": True,
        "data": {"username": "agent", "blog": BLOG},
    }
    client = Mock(token="synthetic", base_url="https://micro.blog")
    with (
        patch("mb.commands.lookup.get_client", return_value=client),
        patch("mb.commands.lookup.get_service", return_value=service),
        patch("mb.commands.lookup._fetch_post_lookup", side_effect=fetch),
    ):
        result = runner.invoke(app, ["lookup", "posts", *args], input=input)
    return result, calls, service


def test_lookup_post_urls_use_the_verified_destination():
    result, calls, service = lookup_posts(["--post", URL, "12"])
    assert result.exit_code == 0, result.output
    assert calls == [(URL, BLOG), ("12", BLOG)]
    service.identity.assert_called_once()


def test_lookup_conversations_and_ids_skip_identity():
    _, calls, service = lookup_posts(["--conversation", URL])
    assert calls == [(URL, None)]
    _, calls, _ = lookup_posts(["--post", "12"])
    assert calls == [("12", None)]
    service.identity.assert_not_called()


def test_lookup_post_identity_failure_stops_before_reads():
    refused = {"ok": False, "error": "Blog must resolve to exactly one", "code": 400}
    result, calls, _ = lookup_posts(["-f", "json", "--post", URL], identity=refused)
    assert result.exit_code == 1 and calls == []
    assert json.loads(result.stdout)["code"] == 400


def test_lookup_posts_stdin_comments_and_errors():
    result, calls, _ = lookup_posts(["--post", "-"], input="# ids\n\n12\n404\n")
    assert [c[0] for c in calls] == ["12", "404"]
    assert result.exit_code == 1 and "404 error=missing" in result.stderr
    assert "error=" not in result.stdout


def micropub_reads(harness):
    return [r for r in harness.requests if r.method == "GET" and r.url.path == "/micropub"]


def test_post_get_sends_verified_destination_not_raw_blog(tmp_path):
    harness = Harness(tmp_path)
    result, _ = harness.invoke(["post", "get", URL], blog=BLOG.rstrip("/"))
    assert result.exit_code == 0
    source = [r for r in micropub_reads(harness) if r.url.params.get("q") == "source"]
    assert [r.url.params.get("mp-destination") for r in source] == [BLOG]


def test_post_list_sends_verified_destination(tmp_path):
    harness = Harness(tmp_path)
    # The synthetic source body is not a listing; only the request matters here.
    harness.invoke(["post", "list"], blog=BLOG.rstrip("/"))
    source = [r for r in micropub_reads(harness) if r.url.params.get("q") == "source"]
    assert [r.url.params.get("mp-destination") for r in source] == [BLOG]


def test_post_get_refuses_unresolvable_blog_before_reading(tmp_path):
    harness = Harness(tmp_path)
    result, data = harness.invoke(["post", "get", URL], blog="https://unknown.example/")
    assert result.exit_code == 1 and "mb blogs" in data["error"]
    assert not [r for r in micropub_reads(harness) if r.url.params.get("q") == "source"]
