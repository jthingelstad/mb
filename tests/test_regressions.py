"""Failures reproduced during the read-only MB review."""

import io
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from typer.testing import CliRunner

from mb.api import MicroblogClient
from mb.cli import app
from mb.commands import catchup, inbox, user
from mb.formatters import _agent_post_line, output_agent


def test_auth_preserves_global_blog():
    client = SimpleNamespace(verify_token=lambda: {"ok": True, "data": {"username": "otto"}})
    with (
        patch("mb.cli.MicroblogClient", return_value=client),
        patch("mb.config.save_config") as save,
    ):
        result = CliRunner().invoke(app, ["auth", "test", "--blog", "https://test.micro.blog/"])
    assert result.exit_code == 0
    assert save.call_args.kwargs["blog"] == "https://test.micro.blog/"


def test_multiline_posts_do_not_add_follow_candidates():
    line = _agent_post_line(
        {"id": 1, "author": {"name": "alice"}, "content_html": "Hello\n@bob another paragraph"}
    )
    with patch.object(user.sys, "stdin", io.StringIO(line)):
        assert user._read_usernames_from_stdin() == ["alice"]


@pytest.mark.parametrize("module", [catchup, inbox])
def test_truncated_attention_does_not_advance(module):
    items = [{"id": 200}, {"id": 199}]
    client = SimpleNamespace(
        get_timeline=lambda **kw: {"ok": True, "data": {"items": items}},
        get_mentions=lambda: {"ok": True, "data": {"items": items}},
        check_timeline=lambda **kw: {"ok": True, "data": {"count": 50}},
        verify_token=lambda: {"ok": True, "data": {"username": "otto"}},
        get_conversation=lambda *args: {"ok": True, "data": {"items": []}},
    )
    with (
        patch.object(module, "get_client", return_value=client),
        patch("mb.config.get_named_checkpoint", return_value=100),
        patch("mb.config.save_named_checkpoint") as save,
    ):
        with pytest.raises(SystemExit):
            module.run(SimpleNamespace(obj={"format": "json"}), count=1, advance=True)
        save.assert_not_called()


@pytest.mark.parametrize(
    "method,outcome", [("get_timeline", "not_applied"), ("micropub_create", "unknown")]
)
def test_transport_errors_are_sanitized(method, outcome):
    def fail(request):
        raise httpx.ReadTimeout("sensitive request detail", request=request)

    with MicroblogClient("test") as client:
        client._client.close()
        client._client = httpx.Client(
            transport=httpx.MockTransport(fail), base_url="https://micro.blog"
        )
        result = getattr(client, method)(
            **({"content": "hello"} if method == "micropub_create" else {})
        )
    assert result["error"] == "network_error"
    assert result["outcome"] == outcome
    assert "sensitive" not in str(result)


def test_agent_error_retains_recovery_information(capsys):
    output_agent({"ok": False, "error": "rate_limited", "retry_after": 60, "outcome": "unknown"})
    assert "retry_after=60" in capsys.readouterr().out


def test_metadata_cannot_escape_pipeline_record():
    line = _agent_post_line(
        {
            "id": "1\n@intruder",
            "author": {"name": "alice\n@intruder"},
            "tags": ["tag\n@intruder"],
            "content_html": "Hello",
        }
    )
    assert len(line.splitlines()) == 1


def test_malformed_read_is_a_failure_not_an_empty_feed():
    with MicroblogClient("synthetic") as client:
        result = client._handle_response(httpx.Response(200, text="<html>proxy error</html>"))
    assert result == {"ok": False, "error": "invalid_response", "code": 502}


def test_draft_response_retains_initial_preview_url():
    with MicroblogClient("synthetic") as client:
        result = client._handle_micropub_response(
            httpx.Response(
                201,
                json={
                    "url": "https://agent.example/draft",
                    "preview": "https://micro.blog/account/posts/1/preview/2",
                },
            )
        )
    assert result["data"]["url"] == "https://agent.example/draft"
    assert result["data"]["preview"].endswith("/preview/2")
