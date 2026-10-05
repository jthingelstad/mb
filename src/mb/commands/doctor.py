"""Read-only installation, configuration and local-state diagnostics."""

import importlib.util
import json
import os
import platform
import shlex
import sqlite3
import stat
import sys
from pathlib import Path

import typer

from mb import config
from mb.api import MicroblogClient
from mb.commands import get_format, get_profile

OK, WARN, ERROR = "ok", "warn", "error"


class _Report:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, name: str, status: str, detail: str, hint: str | None = None, **extra) -> None:
        check = {"name": name, "status": status, "detail": detail}
        if hint:
            check["hint"] = hint
        check.update(extra)
        self.checks.append(check)


def _install_method(module_path: Path) -> str:
    text = str(module_path)
    if "/Cellar/" in text or "/homebrew/" in text.lower():
        return "homebrew"
    if "/uv/tools/" in text:
        return "uv-tool"
    if "/pipx/venvs/" in text:
        return "pipx"
    return "other"


def _mb_on_path() -> list[str]:
    found: list[str] = []
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        candidate = Path(directory) / "mb"
        if candidate.is_file() and os.access(candidate, os.X_OK) and str(candidate) not in found:
            found.append(str(candidate))
    return found


def _check_install(report: _Report) -> None:
    import mb

    version = _version()
    report.add(
        "version",
        OK,
        f"mb {version}; Python {platform.python_version()} at {sys.executable}",
        version=version,
        python=platform.python_version(),
        python_executable=sys.executable,
    )
    module_path = Path(mb.__file__).resolve()
    method = _install_method(module_path)
    report.add("install", OK, f"{method} install at {module_path.parent}", method=method)

    this_script = Path(sys.executable).parent / "mb"
    current = os.path.realpath(this_script) if this_script.exists() else None
    on_path = _mb_on_path()
    resolved = [os.path.realpath(p) for p in on_path]
    if not on_path:
        report.add(
            "path",
            WARN,
            "No mb executable on PATH",
            "Add the install's bin directory to PATH",
            found=[],
        )
    elif current is not None and resolved[0] != current:
        report.add(
            "path",
            WARN,
            f"{on_path[0]} shadows this mb ({this_script})",
            "Remove the older install or reorder PATH so one mb runs",
            found=on_path,
        )
    elif len(set(resolved)) > 1:
        report.add(
            "path",
            WARN,
            "Several different mb executables on PATH: " + ", ".join(on_path),
            "Remove installs you no longer use",
            found=on_path,
        )
    else:
        report.add("path", OK, f"{on_path[0]}", found=on_path)

    if importlib.util.find_spec("mcp") and importlib.util.find_spec("anyio"):
        report.add("mcp", OK, "MCP extra installed")
    else:
        report.add(
            "mcp",
            WARN,
            "MCP extra not installed; mb mcp is unavailable",
            "brew install jthingelstad/tap/mb, or uv tool install --from "
            "git+https://github.com/jthingelstad/mb 'mb[mcp]'",
        )


def _version() -> str:
    from mb.cli import package_version

    return package_version()


def _private(path: Path) -> bool:
    return stat.S_IMODE(path.stat().st_mode) & 0o077 == 0


def _check_config(report: _Report, profile: str) -> str | None:
    """Report the config file and token source; return the token without printing it."""
    path = config.CONFIG_FILE
    parsed = True
    if not path.exists():
        report.add("config", WARN, f"No config file at {path}", "Run: mb auth - (paste the token)")
        parsed = False
    else:
        if not _private(path):
            mode = oct(stat.S_IMODE(path.stat().st_mode))
            report.add(
                "config_permissions",
                ERROR,
                f"{path} is readable by other users (mode {mode})",
                f"Run: chmod 600 {shlex.quote(str(path))}",
            )
        else:
            report.add("config_permissions", OK, f"{path} mode 0o600")
        try:
            profiles = config.list_profiles()
        except config.ConfigError as exc:
            report.add("config", ERROR, str(exc), "Fix the file, or run mb auth - to rewrite it")
            parsed = False
        else:
            names = [p["name"] for p in profiles]
            invalid = [n for n in names if not config.NAME_PATTERN.fullmatch(n)]
            if invalid:
                report.add(
                    "config",
                    WARN,
                    "Profiles with unsupported names: " + ", ".join(map(json.dumps, invalid)),
                    "Rename them to letters, digits, _ and - so --profile can select them",
                    profiles=names,
                )
            else:
                report.add(
                    "config", OK, "profiles: " + (", ".join(names) or "none"), profiles=names
                )

    environment = os.environ.get("MB_TOKEN")
    if environment:
        report.add("token", OK, "Token from MB_TOKEN (overrides the profile)", source="MB_TOKEN")
        return environment
    token = None
    if parsed:
        token = config.get_token(profile=profile)
    if token:
        report.add("token", OK, f"Token from profile {profile}", source="profile")
        return token
    report.add(
        "token",
        ERROR,
        f"No token for profile {profile}",
        "Run: mb auth - (paste the token, then Ctrl-D)",
        source=None,
    )
    return None


def _check_account(report: _Report, ctx: typer.Context, token: str, profile: str) -> None:
    from mb.services import MicroblogService

    client = MicroblogClient(token=token)
    try:
        verified = client.verify_token()
        if not verified["ok"]:
            report.add("account", ERROR, f"Token check failed: {verified.get('error')}")
            return
        username = verified["data"].get("username", "")
        report.add("account", OK, f"@{username}", username=username)
        configuration = client.micropub_get_config()
        if not configuration["ok"]:
            report.add("blogs", ERROR, f"Could not list blogs: {configuration.get('error')}")
            return
        uids = [d.get("uid", "") for d in configuration["data"].get("destination", [])]
        report.add("blogs", OK, ", ".join(uids) or "none", blogs=uids)
        requested = (ctx.obj or {}).get("blog")
        if not requested:
            try:
                requested = config.get_blog(profile=profile)
            except config.ConfigError:
                requested = os.environ.get("MB_BLOG")
        service = MicroblogService(client, profile, requested, "cli", Path(os.devnull))
        identity = service.identity()
        if identity["ok"]:
            blog = identity["data"]["blog"]
            report.add("destination", OK, blog, destination=blog)
        else:
            report.add("destination", ERROR, identity.get("error", "Unresolved destination"))
    finally:
        client.close()


def _scope_label(scope: str) -> tuple[str, str, str | None]:
    """Return (account, receipt scope, blog) from a stored scope key."""
    try:
        values = json.loads(scope)
    except ValueError:
        return "?", "blog", None
    if not isinstance(values, list) or len(values) < 2:
        return "?", "blog", None
    if values[1] == "native-replies":
        return str(values[0]), "reply", None
    return str(values[0]), "blog", str(values[1])


def _resolve_command(
    ctx: typer.Context, profile: str, operation_id: str, scope: str, blog: str | None, outcome: str
) -> str:
    command = ["mb"]
    if profile != config.DEFAULT_PROFILE:
        command += ["--profile", profile]
    if (ctx.obj or {}).get("state_file"):
        command += ["--state-file", ctx.obj["state_file"]]
    blog = blog or (ctx.obj or {}).get("blog")
    if blog:
        command += ["--blog", blog]
    command += ["operation-status", operation_id, "--scope", scope, "--resolve", outcome]
    return shlex.join(command)


def _check_state(report: _Report, ctx: typer.Context, profile: str) -> None:
    from mb.state import LEGACY_CURSOR, StateStore

    configured = (ctx.obj or {}).get("state_file")
    path = Path(configured) if configured else config.default_state_path()
    if not path.exists():
        report.add("state", OK, f"No receipts yet at {path}", path=str(path))
        return
    if not path.is_file():
        report.add("state", ERROR, f"{path} is not a regular file", path=str(path))
        return
    try:
        summary = StateStore(path).summary()
    except (OSError, sqlite3.Error):
        report.add(
            "state",
            ERROR,
            f"Cannot read receipts at {path}",
            "Check the file's owner and permissions; do not delete it without review",
            path=str(path),
        )
        return
    if _private(path):
        report.add("state", OK, f"{path} readable, mode 0o600", path=str(path))
    else:
        mode = oct(stat.S_IMODE(path.stat().st_mode))
        report.add(
            "state",
            WARN,
            f"{path} is readable by other users (mode {mode})",
            f"Run: chmod 600 {shlex.quote(str(path))}",
            path=str(path),
        )

    for operation in summary["operations"]:
        account, scope, blog = _scope_label(operation["scope"])
        where = f"@{account} " + (blog or "native replies")
        pending = operation["status"] == "pending"
        commands = [
            _resolve_command(ctx, profile, operation["id"], scope, blog, outcome)
            for outcome in ("applied", "not_applied")
        ]
        report.add(
            "receipt",
            ERROR if pending else WARN,
            f"{operation['id']} is {operation['status']} ({where})"
            + ("; it blocks new writes there" if pending else ""),
            "Check the blog for this write, then record what happened with one of the commands",
            operation_id=operation["id"],
            receipt_status=operation["status"],
            receipt_scope=scope,
            commands=commands,
        )
    if not summary["operations"]:
        report.add("receipts", OK, "No pending or unknown receipts")

    legacy = [c for c in summary["cursors"] if c["scheme"] == LEGACY_CURSOR]
    for cursor in legacy:
        try:
            values = json.loads(cursor["scope"])
            label = f"{values[2]}/{values[3]} for @{values[0]} {values[1]}"
        except (ValueError, IndexError, TypeError, KeyError):
            label = cursor["scope"]
        report.add(
            "checkpoint",
            WARN,
            f"{label} is {LEGACY_CURSOR}",
            "Review it with the operator before MCP acknowledges it; MB never migrates it",
            checkpoint_scope=cursor["scope"],
            scheme=cursor["scheme"],
        )
    if not legacy:
        report.add("checkpoints", OK, f"{len(summary['cursors'])} checkpoints, none need review")


def _check_media_root(report: _Report, ctx: typer.Context) -> None:
    root = (ctx.obj or {}).get("media_root")
    if not root:
        report.add(
            "media_root",
            OK,
            "Not set: MCP local images are disabled; the CLI reads any local path",
        )
        return
    path = Path(root)
    if not path.is_absolute():
        report.add("media_root", ERROR, f"{root} is not absolute")
    elif not path.exists():
        report.add("media_root", ERROR, f"{root} does not exist")
    elif not path.is_dir():
        report.add("media_root", ERROR, f"{root} is not a directory")
    else:
        report.add("media_root", OK, root)


def run(ctx: typer.Context, offline: bool = False) -> None:
    from mb.formatters import output

    profile = get_profile(ctx)
    report = _Report()
    _check_install(report)
    token = _check_config(report, profile)
    if offline:
        report.add("account", OK, "Skipped (--offline)")
    elif token:
        _check_account(report, ctx, token, profile)
    _check_state(report, ctx, profile)
    _check_media_root(report, ctx)

    counts = {status: 0 for status in (OK, WARN, ERROR)}
    for check in report.checks:
        counts[check["status"]] += 1
    output(
        {
            "ok": True,
            "data": {
                "kind": "doctor",
                "version": _version(),
                "profile": profile,
                "offline": offline,
                "healthy": counts[ERROR] == 0,
                "summary": counts,
                "checks": report.checks,
            },
        },
        get_format(ctx),
    )
    if counts[ERROR]:
        raise SystemExit(1)
