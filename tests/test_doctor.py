"""mb doctor: read-only diagnostics over a mocked transport and a temporary home."""

import json
import os
import shlex
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from mb import config
from mb.cli import app, package_version
from mb.commands.doctor import _install_method
from mb.state import StateStore
from tests.conftest import write_legacy_cursor
from tests.test_cli import _make_mock_init, _mock_transport

runner = CliRunner()
TOKEN = "doctor-secret-token-value"
BLOG = "https://testuser.micro.blog/"
BLOG_SCOPE = json.dumps(["testuser", BLOG])
REPLY_SCOPE = json.dumps(["testuser", "native-replies"])


def invoke(args, env=None):
    with patch("mb.api.MicroblogClient.__init__", _make_mock_init(_mock_transport())):
        return runner.invoke(app, args, env=env)


def doctor(args=(), env=None):
    result = invoke(["-f", "json", "doctor", *args], env=env)
    return result, json.loads(result.stdout)["data"]


def by_name(data, name):
    return [c for c in data["checks"] if c["name"] == name]


def snapshot(root: Path) -> dict:
    return {
        str(p): (p.stat().st_mtime_ns, p.stat().st_size, p.stat().st_mode)
        for p in sorted(root.rglob("*"))
    }


def save_profile(profile="default", **extra):
    config.save_config(token=TOKEN, username="testuser", profile=profile, **extra)


def state_with_receipts(path: Path) -> StateStore:
    store = StateStore(path)
    store.claim(BLOG_SCOPE, "op-pending", "f1")
    store.claim(REPLY_SCOPE, "op-unknown", "f2")
    store.finish(REPLY_SCOPE, "op-unknown", {"ok": False, "outcome": "unknown"})
    store.claim(BLOG_SCOPE, "op-done", "f3")  # refused: op-pending blocks the blog scope
    return store


def test_offline_without_config_reports_missing_token_and_creates_nothing(tmp_path):
    before = snapshot(tmp_path)
    result, data = doctor(["--offline"])
    assert result.exit_code == 1
    assert data["kind"] == "doctor" and data["version"] == package_version()
    assert data["healthy"] is False and data["offline"] is True
    assert by_name(data, "config")[0]["status"] == "warn"
    assert by_name(data, "token")[0]["status"] == "error"
    assert "mb auth -" in by_name(data, "token")[0]["hint"]
    assert by_name(data, "account")[0]["detail"] == "Skipped (--offline)"
    assert by_name(data, "state")[0]["status"] == "ok"
    assert data["summary"]["error"] == 1
    assert snapshot(tmp_path) == before


def test_version_check_reports_python_and_executable():
    _, data = doctor(["--offline"])
    version = by_name(data, "version")[0]
    assert version["version"] == package_version()
    assert version["python_executable"] == sys.executable
    assert by_name(data, "install")[0]["method"] in {"homebrew", "uv-tool", "pipx", "other"}


def test_online_checks_verify_token_blogs_and_destination_without_printing_token(tmp_path):
    save_profile()
    before = snapshot(tmp_path)
    for fmt in ("json", "agent", "human"):
        result = invoke(["-f", fmt, "doctor"])
        assert TOKEN not in result.output
    result, data = doctor()
    assert by_name(data, "token")[0] == {
        "name": "token",
        "status": "ok",
        "detail": "Token from profile default",
        "source": "profile",
    }
    assert by_name(data, "account")[0]["username"] == "testuser"
    assert by_name(data, "blogs")[0]["blogs"] == [BLOG, "https://testblog.micro.blog/"]
    assert by_name(data, "destination")[0]["destination"] == BLOG
    assert by_name(data, "config")[0]["profiles"] == ["default"]
    assert by_name(data, "config_permissions")[0]["status"] == "ok"
    assert data["summary"]["error"] == 0 and result.exit_code == 0
    assert snapshot(tmp_path) == before


def test_unresolved_destination_is_an_error():
    save_profile()
    result, data = doctor(["--blog", "https://nope.example/"])
    assert result.exit_code == 1
    check = by_name(data, "destination")[0]
    assert check["status"] == "error" and "mb blogs" in check["detail"]


def test_rejected_token_is_an_error():
    save_profile()
    with patch(
        "mb.api.MicroblogClient.verify_token",
        return_value={"ok": False, "error": "Unauthorized", "code": 401},
    ):
        result = runner.invoke(app, ["-f", "json", "doctor"])
    data = json.loads(result.stdout)["data"]
    assert result.exit_code == 1
    assert by_name(data, "account")[0]["status"] == "error"
    assert not by_name(data, "blogs")


def test_environment_token_is_reported_by_source_only():
    _, data = doctor(["--offline"], env={"MB_TOKEN": TOKEN})
    assert by_name(data, "token")[0]["source"] == "MB_TOKEN"
    assert TOKEN not in json.dumps(data)


def test_loose_config_permissions_are_an_error_with_chmod_hint():
    save_profile()
    config.CONFIG_FILE.chmod(0o644)
    result, data = doctor(["--offline"])
    check = by_name(data, "config_permissions")[0]
    assert result.exit_code == 1 and check["status"] == "error"
    assert check["hint"] == f"Run: chmod 600 {shlex.quote(str(config.CONFIG_FILE))}"


def test_invalid_toml_is_reported_without_a_traceback():
    config.CONFIG_DIR.mkdir(parents=True)
    config.CONFIG_FILE.write_text(f'[default]\ntoken = "{TOKEN}"\nbroken =\n')
    config.CONFIG_FILE.chmod(0o600)
    result, data = doctor(["--offline"])
    assert result.exit_code == 1 and isinstance(result.exception, SystemExit)
    assert "not valid TOML" in by_name(data, "config")[0]["detail"]
    assert by_name(data, "token")[0]["status"] == "error"
    assert TOKEN not in result.output


def test_unsupported_profile_names_are_flagged():
    config.CONFIG_DIR.mkdir(parents=True)
    config.CONFIG_FILE.write_text(
        f'[default]\ntoken = "{TOKEN}"\n\n["my blog"]\ntoken = "{TOKEN}"\n'
    )
    config.CONFIG_FILE.chmod(0o600)
    _, data = doctor(["--offline"])
    check = by_name(data, "config")[0]
    assert check["status"] == "warn" and '"my blog"' in check["detail"]
    assert check["profiles"] == ["default", "my blog"]


def test_pending_and_unknown_receipts_list_exact_resolve_commands(tmp_path):
    state = tmp_path / "state.sqlite3"
    with pytest.raises(ValueError):
        state_with_receipts(state)
    before = snapshot(tmp_path)
    result, data = doctor(["--offline", "--state-file", str(state)], env={"MB_TOKEN": TOKEN})
    assert result.exit_code == 1
    receipts = by_name(data, "receipt")
    assert [(r["operation_id"], r["status"], r["receipt_scope"]) for r in receipts] == [
        ("op-pending", "error", "blog"),
        ("op-unknown", "warn", "reply"),
    ]
    assert "blocks new writes" in receipts[0]["detail"]
    assert receipts[0]["commands"] == [
        shlex.join(
            [
                "mb",
                "--state-file",
                str(state),
                "--blog",
                BLOG,
                "operation-status",
                "op-pending",
                "--scope",
                "blog",
                "--resolve",
                outcome,
            ]
        )
        for outcome in ("applied", "not_applied")
    ]
    assert receipts[1]["commands"][1] == shlex.join(
        [
            "mb",
            "--state-file",
            str(state),
            "operation-status",
            "op-unknown",
            "--scope",
            "reply",
            "--resolve",
            "not_applied",
        ]
    )
    assert snapshot(tmp_path) == before


def test_doctor_hint_resolves_the_receipt_and_clears_the_finding(tmp_path):
    state = tmp_path / "state.sqlite3"
    with pytest.raises(ValueError):
        state_with_receipts(state)
    _, data = doctor(["--offline", "--state-file", str(state)], env={"MB_TOKEN": TOKEN})
    command = shlex.split(by_name(data, "receipt")[0]["commands"][1])
    assert command[0] == "mb"
    resolved = invoke(["-f", "json", *command[1:]], env={"MB_TOKEN": TOKEN})
    assert resolved.exit_code == 0, resolved.output
    _, after = doctor(["--offline", "--state-file", str(state)], env={"MB_TOKEN": TOKEN})
    assert [r["operation_id"] for r in by_name(after, "receipt")] == ["op-unknown"]
    assert StateStore(state).claim(BLOG_SCOPE, "op-next", "f4") is None


def test_non_default_profile_is_part_of_the_resolve_command(tmp_path):
    state = tmp_path / "state.sqlite3"
    StateStore(state).claim(BLOG_SCOPE, "op-1", "f1")
    _, data = doctor(
        ["--offline", "--profile", "work", "--state-file", str(state)], env={"MB_TOKEN": TOKEN}
    )
    assert by_name(data, "receipt")[0]["commands"][0].startswith(
        f"mb --profile work --state-file {shlex.quote(str(state))} --blog "
    )


def test_legacy_checkpoints_are_listed_for_review(tmp_path):
    state = tmp_path / "state.sqlite3"
    store = StateStore(state)
    legacy_scope = json.dumps(["testuser", BLOG, "dot", "heartbeat"])
    native_scope = json.dumps(["testuser", BLOG, "default", "inbox"])
    write_legacy_cursor(store, legacy_scope, "123")
    store.acknowledge(native_scope, "456", 0)
    result, data = doctor(["--offline", "--state-file", str(state)], env={"MB_TOKEN": TOKEN})
    checkpoints = by_name(data, "checkpoint")
    assert len(checkpoints) == 1
    assert checkpoints[0]["status"] == "warn"
    assert checkpoints[0]["scheme"] == "legacy-review-required"
    assert checkpoints[0]["checkpoint_scope"] == legacy_scope
    assert checkpoints[0]["detail"] == (
        f"dot/heartbeat for @testuser {BLOG} is legacy-review-required"
    )
    assert by_name(data, "receipts")[0]["status"] == "ok"
    assert result.exit_code == 0


def test_no_legacy_checkpoints_reports_count(tmp_path):
    state = tmp_path / "state.sqlite3"
    StateStore(state).acknowledge(json.dumps(["testuser", BLOG, "default", "inbox"]), "9", 0)
    _, data = doctor(["--offline", "--state-file", str(state)], env={"MB_TOKEN": TOKEN})
    assert by_name(data, "checkpoints")[0]["detail"] == "1 checkpoints, none need review"


def test_default_state_file_location_is_checked():
    StateStore(config.CONFIG_DIR / "mcp-state.sqlite3").claim(BLOG_SCOPE, "op-1", "f1")
    _, data = doctor(["--offline"], env={"MB_TOKEN": TOKEN})
    assert by_name(data, "state")[0]["path"] == str(config.CONFIG_DIR / "mcp-state.sqlite3")
    assert "--state-file" not in by_name(data, "receipt")[0]["commands"][0]


def test_unreadable_or_loose_state_file(tmp_path):
    state = tmp_path / "state.sqlite3"
    state.write_bytes(b"not a database at all" * 100)
    result, data = doctor(["--offline", "--state-file", str(state)], env={"MB_TOKEN": TOKEN})
    assert result.exit_code == 1
    assert by_name(data, "state")[0]["detail"].startswith("Cannot read receipts")

    loose = tmp_path / "loose.sqlite3"
    StateStore(loose).acknowledge(json.dumps(["u", BLOG, "default", "inbox"]), "1", 0)
    loose.chmod(0o644)
    _, data = doctor(["--offline", "--state-file", str(loose)], env={"MB_TOKEN": TOKEN})
    assert by_name(data, "state")[0]["status"] == "warn"
    assert "chmod 600" in by_name(data, "state")[0]["hint"]

    _, data = doctor(["--offline", "--state-file", str(tmp_path)], env={"MB_TOKEN": TOKEN})
    assert by_name(data, "state")[0]["status"] == "error"


def test_media_root_checks(tmp_path):
    _, data = doctor(["--offline"], env={"MB_TOKEN": TOKEN})
    assert "MCP local images are disabled" in by_name(data, "media_root")[0]["detail"]
    _, data = doctor(["--offline", "--media-root", str(tmp_path)], env={"MB_TOKEN": TOKEN})
    assert by_name(data, "media_root")[0] == {
        "name": "media_root",
        "status": "ok",
        "detail": os.path.realpath(tmp_path),
    }
    afile = tmp_path / "file.txt"
    afile.write_text("x")
    result, data = doctor(["--offline", "--media-root", str(afile)], env={"MB_TOKEN": TOKEN})
    assert by_name(data, "media_root")[0]["status"] == "error" and result.exit_code == 1
    _, data = doctor(
        ["--offline", "--media-root", str(tmp_path / "missing")], env={"MB_TOKEN": TOKEN}
    )
    assert "does not exist" in by_name(data, "media_root")[0]["detail"]


def _fake_bin(directory: Path) -> Path:
    directory.mkdir()
    script = directory / "mb"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o755)
    return script


def test_path_shadowing_and_duplicates(tmp_path, monkeypatch):
    mine, other = _fake_bin(tmp_path / "mine"), _fake_bin(tmp_path / "other")
    monkeypatch.setattr(sys, "executable", str(mine.parent / "python"))
    env = {"MB_TOKEN": TOKEN}

    env["PATH"] = os.pathsep.join([str(other.parent), str(mine.parent)])
    _, data = doctor(["--offline"], env=env)
    check = by_name(data, "path")[0]
    assert check["status"] == "warn" and "shadows" in check["detail"]
    assert check["found"] == [str(other), str(mine)]

    env["PATH"] = os.pathsep.join([str(mine.parent), str(other.parent)])
    _, data = doctor(["--offline"], env=env)
    assert "Several different" in by_name(data, "path")[0]["detail"]

    env["PATH"] = str(mine.parent)
    _, data = doctor(["--offline"], env=env)
    assert by_name(data, "path")[0] == {
        "name": "path",
        "status": "ok",
        "detail": str(mine),
        "found": [str(mine)],
    }

    env["PATH"] = str(tmp_path / "empty")
    _, data = doctor(["--offline"], env=env)
    assert by_name(data, "path")[0]["detail"] == "No mb executable on PATH"


def test_missing_mcp_extra_is_a_warning_with_install_hint():
    with patch("mb.commands.doctor.importlib.util.find_spec", return_value=None):
        _, data = doctor(["--offline"], env={"MB_TOKEN": TOKEN})
    check = by_name(data, "mcp")[0]
    assert check["status"] == "warn" and "mb[mcp]" in check["hint"]


@pytest.mark.parametrize(
    "path,method",
    [
        ("/opt/homebrew/Cellar/mb/2.0.0/libexec/lib/python3.14/site-packages/mb", "homebrew"),
        ("/Users/x/.local/share/uv/tools/mb/lib/python3.14/site-packages/mb", "uv-tool"),
        ("/Users/x/.local/pipx/venvs/mb/lib/python3.14/site-packages/mb", "pipx"),
        ("/Users/x/src/mb/src/mb", "other"),
    ],
)
def test_install_method_guess(path, method):
    assert _install_method(Path(path)) == method


def test_agent_and_human_formats(tmp_path):
    state = tmp_path / "state.sqlite3"
    StateStore(state).claim(BLOG_SCOPE, "op-1", "f1")
    args = ["--offline", "--state-file", str(state)]
    agent = invoke(["doctor", *args], env={"MB_TOKEN": TOKEN})
    lines = agent.stdout.splitlines()
    assert agent.exit_code == 1
    assert (
        "error receipt: op-1 is pending (@testuser " + BLOG + "); it blocks new writes there"
        in (lines)
    )
    assert any(line.startswith("  run: mb --state-file ") for line in lines)
    assert lines[-1].startswith("healthy=false ok=")
    human = invoke(["--human", "doctor", *args], env={"MB_TOKEN": TOKEN})
    assert human.exit_code == 1
    assert "Problems found" in human.stdout and "op-1" in human.stdout
