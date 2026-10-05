"""Entry-point hardening: config safety, version, option parsing and token input; no network."""

import json
import os
import stat
from unittest.mock import Mock, patch

import pytest
from typer.testing import CliRunner

from mb import commands, config
from mb.api import MicroblogClient
from mb.cli import app, package_version
from mb.services import MicroblogService
from tests.test_cli import _make_mock_init, _mock_transport

runner = CliRunner()


def invoke(args, **kwargs):
    with patch("mb.api.MicroblogClient.__init__", _make_mock_init(_mock_transport())):
        return runner.invoke(app, args, **kwargs)


# ── --version ──────────────────────────────────────────────


@pytest.mark.parametrize("flag", ["--version", "-V"])
def test_version_prints_name_and_version(flag):
    result = invoke([flag])
    assert result.exit_code == 0
    assert result.stdout == f"mb {package_version()}\n"


@pytest.mark.parametrize(
    "args", [["-f", "json", "--version"], ["--format=json", "-V"], ["--version", "-f", "json"]]
)
def test_version_json_envelope(args):
    result = invoke(args)
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "schema_version": 1,
        "ok": True,
        "data": {"version": package_version()},
    }


def test_version_flag_after_a_command_is_not_intercepted():
    result = invoke(["profiles", "-V"])
    assert result.exit_code == 2 and "mb " + package_version() not in result.stdout


def test_package_version_unknown_when_not_installed():
    from importlib.metadata import PackageNotFoundError

    with patch("importlib.metadata.version", side_effect=PackageNotFoundError("mb")):
        assert package_version() == "unknown"


# ── formats and option parsing ─────────────────────────────


def test_long_option_equals_form_is_hoisted():
    result = invoke(["profiles", "--format=json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["ok"] is True


@pytest.mark.parametrize("args", [["--format", "yaml", "profiles"], ["profiles", "--format=xml"]])
def test_unknown_format_exits_2_with_clear_message(args):
    result = invoke(args)
    assert result.exit_code == 2 and result.stdout == ""
    assert "unknown output format" in result.stderr and "--format" in result.stderr


def test_unknown_mb_format_names_the_variable(monkeypatch):
    monkeypatch.setenv("MB_FORMAT", "toml")
    result = invoke(["profiles"])
    assert result.exit_code == 2 and "MB_FORMAT" in result.stderr


def test_output_refuses_unknown_format():
    from mb.formatters import output

    with pytest.raises(ValueError):
        output({"ok": True, "data": {}}, "yaml")


@pytest.mark.parametrize(
    "args",
    [
        ["timeline", "--count", "51"],
        ["timeline", "--count", "0"],
        ["heartbeat", "--count", "51"],
        ["heartbeat", "--mention-count", "51"],
        ["catchup", "--count", "51"],
        ["poll", "--since", "1", "--interval", "0"],
    ],
)
def test_counts_are_bounded(args):
    result = invoke(args)
    assert result.exit_code == 2
    assert "Invalid value" in result.output


def test_mcp_consumer_default_and_install_hint():
    result = invoke(["mcp", "--help"])
    assert result.exit_code == 0
    assert "dot, openclaw" not in result.stdout and "default" in result.stdout
    with patch.dict("sys.modules", {"anyio": None}):
        missing = invoke(["mcp"])
    assert missing.exit_code == 1
    assert "brew install jthingelstad/tap/mb" in missing.stderr
    assert "uv tool install --from git+https://github.com/jthingelstad/mb 'mb[mcp]'" in (
        missing.stderr
    )


# ── profile and checkpoint names, config file safety ───────


@pytest.mark.parametrize("name", ["bad name", "../up", "x.y", "", "a]b"])
def test_invalid_profile_name_is_a_structured_error(name):
    result = invoke(["-f", "json", "-p", name, "whoami"])
    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data["ok"] is False and data["code"] == 400 and "profile name" in data["error"]
    assert not config.CONFIG_FILE.exists()


@pytest.mark.parametrize("name", ["work", "agent_2", "A-b"])
def test_valid_profile_names_pass(name):
    assert config.validate_name("profile", name) == name


def test_invalid_checkpoint_names_are_refused_without_writing():
    for call in (
        lambda: config.save_named_checkpoint("bad.name", 1),
        lambda: config.get_named_checkpoint("a b"),
        lambda: config.clear_named_checkpoint("x=y"),
        lambda: config.save_config("token", profile="bad profile"),
    ):
        with pytest.raises(config.ConfigError):
            call()
    assert not config.CONFIG_FILE.exists()


def test_invalid_toml_names_path_and_line_without_contents():
    config.CONFIG_DIR.mkdir(parents=True)
    config.CONFIG_FILE.write_text('[default]\ntoken = "zzsecretzz\n')
    result = invoke(["-f", "json", "whoami"])
    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert str(config.CONFIG_FILE) in data["error"] and "line 2" in data["error"]
    assert "zzsecretzz" not in result.output
    agent = invoke(["whoami"])
    assert agent.exit_code == 1 and agent.stdout.startswith("ERROR: Config file")


def test_config_write_is_private_and_atomic():
    config.CONFIG_DIR.mkdir(parents=True)
    config.CONFIG_FILE.write_text("[default]\ntoken = 'old'\n")
    config.CONFIG_FILE.chmod(0o644)
    config.save_config("new-token", username="me", profile="default")
    assert stat.S_IMODE(config.CONFIG_FILE.stat().st_mode) == 0o600
    assert config.get_token() == "new-token"
    assert sorted(p.name for p in config.CONFIG_DIR.iterdir()) == ["config.toml"]


def test_failed_config_write_keeps_old_file_and_removes_temporary():
    config.save_config("first", profile="default")
    with patch("mb.config.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            config.save_config("second", profile="default")
    assert config.get_token() == "first"
    assert sorted(p.name for p in config.CONFIG_DIR.iterdir()) == ["config.toml"]


# ── username resolution with MB_TOKEN ──────────────────────


def username_context(client):
    ctx = Mock()
    return (
        ctx,
        patch("mb.commands.get_client", return_value=client),
        patch("mb.commands.get_profile", return_value="default"),
    )


def test_get_username_prefers_config_without_mb_token():
    config.save_config("profile-token", username="configured", profile="default")
    client = Mock(spec=MicroblogClient, token="profile-token")
    ctx, get_client, get_profile = username_context(client)
    with get_client, get_profile:
        assert commands.get_username(ctx) == "configured"
    client.verify_token.assert_not_called()


def test_get_username_verifies_mb_token_once_per_process(monkeypatch):
    config.save_config("profile-token", username="configured", profile="default")
    monkeypatch.setenv("MB_TOKEN", "environment-token")
    client = Mock(spec=MicroblogClient, token="environment-token")
    client.verify_token.return_value = {"ok": True, "data": {"username": "envuser"}}
    ctx, get_client, get_profile = username_context(client)
    with get_client, get_profile:
        assert commands.get_username(ctx) == "envuser"
        assert commands.get_username(ctx) == "envuser"
    assert client.verify_token.call_count == 1
    assert "environment-token" not in json.dumps(commands._VERIFIED_USERNAMES)


# ── mb auth - ──────────────────────────────────────────────


def test_auth_reads_token_from_stdin_and_never_prints_it():
    result = invoke(["-f", "json", "auth", "-"], input="  stdin-token-value\n")
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["data"]["username"] == "testuser"
    assert "stdin-token-value" not in result.output
    assert config.get_token() == "stdin-token-value"
    assert stat.S_IMODE(os.stat(config.CONFIG_FILE).st_mode) == 0o600


@pytest.mark.parametrize("stdin", ["", " \n\n"])
def test_auth_refuses_empty_stdin(stdin):
    result = invoke(["-f", "json", "auth", "-"], input=stdin)
    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "schema_version": 1,
        "ok": False,
        "error": "No token on stdin",
        "code": 400,
    }
    assert not config.CONFIG_FILE.exists()


# ── mb auth (guided) ───────────────────────────────────────

GOOD = "good-token-value"
TWO_BLOGS = [
    {"uid": "https://one.example/", "name": "One"},
    {"uid": "https://two.example/", "name": "Two", "microblog-default": True},
]


def guided(args, stdin, blogs=None, verify=None):
    """Run mb auth as if at a terminal, against a fake micro.blog that accepts GOOD."""

    def client(token):
        def verify_token():
            if verify:
                return verify
            if token == GOOD:
                return {"ok": True, "data": {"username": "newuser"}}
            return {"ok": False, "error": "Unauthorized", "code": 401}

        destinations = blogs if blogs is not None else [{"uid": "https://newuser.micro.blog/"}]
        return Mock(
            verify_token=verify_token,
            micropub_get_config=lambda: {"ok": True, "data": {"destination": destinations}},
        )

    with (
        patch("mb.cli._interactive", return_value=True),
        patch("mb.cli.MicroblogClient", side_effect=lambda token: client(token)),
    ):
        return runner.invoke(app, ["-f", "json", *args], input=stdin)


def envelope(result):
    """The JSON result; CliRunner also echoes visible prompt answers onto stdout."""
    return json.loads(result.stdout[result.stdout.index("{") :])


def test_bare_auth_without_a_terminal_refuses_instead_of_prompting():
    result = invoke(["-f", "json", "auth"], input="")
    assert result.exit_code == 1
    assert envelope(result)["code"] == 400
    assert "mb auth -" in envelope(result)["error"]
    assert not config.CONFIG_FILE.exists()


def test_guided_auth_hides_the_token_and_saves_a_single_blog_account():
    result = guided(["auth"], f"{GOOD}\n")
    assert result.exit_code == 0, result.output
    assert GOOD not in result.output
    assert "https://micro.blog/account/apps" in result.stderr
    assert "@newuser" in result.stderr and "mb doctor" in result.stderr
    data = envelope(result)["data"]
    assert data == {"username": "newuser", "message": "Token saved", "profile": "default"}
    assert config.get_token() == GOOD and config.get_blog() is None
    assert stat.S_IMODE(os.stat(config.CONFIG_FILE).st_mode) == 0o600


def test_guided_auth_retries_a_rejected_token():
    result = guided(["auth"], f"wrong\n   \n{GOOD}\n")
    assert result.exit_code == 0, result.output
    assert "did not accept that token" in result.stderr
    assert "No token entered" in result.stderr
    assert config.get_token() == GOOD


def test_guided_auth_gives_up_after_three_rejections():
    result = guided(["auth"], "a\nb\nc\n")
    assert result.exit_code == 1
    assert envelope(result)["code"] == 401
    assert not config.CONFIG_FILE.exists()


def test_guided_auth_reports_a_network_failure_without_retrying():
    failure = {"ok": False, "error": "Network error", "code": 503}
    result = guided(["auth"], f"{GOOD}\n", verify=failure)
    assert result.exit_code == 1
    assert envelope(result)["error"] == "Network error"
    assert "did not accept" not in result.stderr


def test_guided_auth_asks_which_blog_when_there_are_several():
    result = guided(["auth"], f"{GOOD}\n1\n", blogs=TWO_BLOGS)
    assert result.exit_code == 0, result.output
    assert "1. One (https://one.example/)" in result.stderr
    assert "[2]" in result.stderr  # the account default is offered first
    assert envelope(result)["data"]["blog"] == "https://one.example/"
    assert config.get_blog() == "https://one.example/"


def test_guided_auth_defaults_to_the_profile_blog_on_a_rerun():
    config.save_config(token="old", blog="https://one.example/")
    result = guided(["auth"], f"{GOOD}\n\n", blogs=TWO_BLOGS)
    assert result.exit_code == 0, result.output
    assert config.get_blog() == "https://one.example/" and config.get_token() == GOOD


def test_guided_auth_with_blog_option_skips_the_picker():
    result = guided(["auth", "--blog", "https://two.example/"], f"{GOOD}\n", blogs=TWO_BLOGS)
    assert result.exit_code == 0, result.output
    assert "several blogs" not in result.stderr
    assert config.get_blog() == "https://two.example/"


def test_guided_auth_names_a_non_default_profile():
    result = guided(["--profile", "work", "auth"], f"{GOOD}\n")
    assert result.exit_code == 0, result.output
    assert "profile work" in result.stderr
    assert config.get_token(profile="work") == GOOD


# ── destination hint ───────────────────────────────────────


def test_ambiguous_default_destination_points_to_mb_blogs(tmp_path):
    client = Mock(spec=MicroblogClient)
    client.token = "synthetic"
    client.base_url = "https://micro.blog"
    client.verify_token.return_value = {
        "ok": True,
        "data": {"username": "agent", "default_site": "elsewhere.example"},
    }
    client.micropub_get_config.return_value = {
        "ok": True,
        "data": {"destination": [{"uid": "https://a.example/"}, {"uid": "https://b.example/"}]},
    }
    service = MicroblogService(client, "default", None, "cli", tmp_path / "state.sqlite")
    result = service.identity()
    assert result["ok"] is False and "mb blogs" in result["error"]
    named = MicroblogService(client, "default", "nope", "cli", tmp_path / "state.sqlite")
    assert "mb blogs" in named.identity()["error"]


# ── MCP argument errors and resource types ─────────────────


@pytest.fixture
def anyio_backend():
    return "asyncio"


def mcp_adapter(tmp_path):
    pytest.importorskip("mcp.types")
    from mb.mcp_server import Adapter

    client = Mock(spec=MicroblogClient)
    client.token = "synthetic"
    service = MicroblogService(client, "default", None, "default", tmp_path / "state.sqlite")
    return Adapter(lambda: service), client


@pytest.mark.anyio
@pytest.mark.parametrize(
    "name,arguments,message",
    [
        ("timeline", {"count": 51}, "count must be between 1 and 50"),
        ("timeline", {"count": 0}, "count must be between 1 and 50"),
        ("inbox", {"count": "5"}, "count must be an integer"),
        ("timeline", {"since": "abc-secret"}, "since does not match the allowed format"),
        ("post_get", {}, "identifier is required"),
        ("timeline", {"surprise": "abc-secret"}, "unknown field"),
        ("operation_status", {"operation_id": "x", "scope": "abc-secret"}, "scope must be"),
        (
            "post_edit",
            {"identifier": "https://a.example/1", "content": "", "operation_id": "e"},
            "content must not be empty",
        ),
    ],
)
async def test_mcp_validation_errors_state_the_allowed_shape(tmp_path, name, arguments, message):
    import mcp.types as types

    adapter, client = mcp_adapter(tmp_path)
    result = await adapter.call_tool(
        None, types.CallToolRequestParams(name=name, arguments=arguments)
    )
    error = result.structured_content["error"]
    assert error.startswith("Invalid arguments: ") and message in error
    assert "abc-secret" not in error
    assert result.structured_content["code"] == 400
    client.verify_token.assert_not_called()


@pytest.mark.anyio
async def test_mcp_resources_declare_their_media_types(tmp_path):
    import mcp.types as types

    adapter, _ = mcp_adapter(tmp_path)
    listed = {r.name: r.mime_type for r in (await adapter.list_resources(None, None)).resources}
    assert listed == {
        "guide": "text/markdown",
        "identity": "application/json",
        "discover-collections": "application/json",
    }
    for uri, expected in [
        ("mb://guide", "text/markdown"),
        ("mb://discover-collections", "application/json"),
    ]:
        read = await adapter.read_resource(None, types.ReadResourceRequestParams(uri=uri))
        assert read.contents[0].mime_type == expected
