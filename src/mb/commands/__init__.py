"""Shared helpers for command modules."""

import hashlib
import os
import re
import shlex
from uuid import uuid4

import typer

from mb.domain import _extract_author_username as _extract_author_username
from mb.domain import add_content_text as add_content_text


def get_client(ctx: typer.Context | None = None):
    from mb.cli import get_client as _get_client

    return _get_client(ctx)


def get_format(ctx: typer.Context) -> str:
    from mb.cli import get_format as _get_format

    return _get_format(ctx)


def get_profile(ctx: typer.Context) -> str:
    from mb.cli import get_profile as _get_profile

    return _get_profile(ctx)


# Verified usernames per token digest, so one process verifies each token once.
_VERIFIED_USERNAMES: dict[str, str] = {}


def get_username(ctx: typer.Context) -> str:
    """Resolve the current username from config or by verifying the token.

    MB_TOKEN may belong to a different account than the profile's saved username,
    so an environment token is always verified instead of trusting the config.
    """
    from mb import config
    from mb.formatters import output

    profile = get_profile(ctx)
    if not os.environ.get("MB_TOKEN"):
        username = config.get_username(profile=profile)
        if username:
            return username

    client = get_client(ctx)
    key = hashlib.sha256(str(client.token).encode()).hexdigest()
    if key in _VERIFIED_USERNAMES:
        return _VERIFIED_USERNAMES[key]
    result = client.verify_token()
    if result["ok"]:
        username = result["data"].get("username", "")
        if username:
            _VERIFIED_USERNAMES[key] = username
        return username

    fmt = get_format(ctx)
    output(
        {"ok": False, "error": "Cannot determine username. Run: mb auth <token>", "code": 401}, fmt
    )
    raise SystemExit(1)


def output_or_exit(result: dict, fmt: str) -> None:
    """Output a result and exit with code 1 if not ok."""
    from mb.formatters import output

    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)


def _micropub_item_url(item: dict) -> str:
    """Extract URL from a Micropub h-entry item or a flat JSON Feed item."""
    # Micropub h-entry format: properties.url[0]
    props = item.get("properties", {})
    url_list = props.get("url", [])
    if url_list:
        return str(url_list[0])
    # Flat format
    return str(item.get("url", ""))


def resolve_post_url(client, post_id: str, fmt: str):
    """Resolve a bare post ID to a full URL for Micropub operations.

    - Full URLs pass through as-is.
    - Bare numeric IDs are resolved via the conversation API (which returns
      items with both ``id`` and ``url`` fields).
    - Other identifiers (slugs) fall back to micropub listing suffix match.

    Returns the URL string, or calls output + SystemExit(1) on failure.
    """
    from mb.formatters import output

    if post_id.startswith("http"):
        return post_id

    # Bare numeric ID — resolve via conversation API
    if post_id.isdigit():
        result = client.get_conversation(int(post_id))
        if not result["ok"]:
            output(result, fmt)
            raise SystemExit(1)
        for item in result["data"].get("items", []):
            if str(item.get("id")) == post_id:
                url = item.get("url", "")
                if url:
                    return url
        output({"ok": False, "error": f"Post {post_id} not found", "code": 404}, fmt)
        raise SystemExit(1)

    # Slug-based identifier — fall back to micropub listing suffix match
    listing = client.micropub_list()
    if not listing["ok"]:
        output(listing, fmt)
        raise SystemExit(1)
    items = listing["data"].get("items", [])
    matched = [i for i in items if _micropub_item_url(i).rstrip("/").endswith(post_id)]
    if not matched:
        output({"ok": False, "error": f"Post {post_id} not found", "code": 404}, fmt)
        raise SystemExit(1)
    return _micropub_item_url(matched[0])


def extract_post_id(value: str) -> int | None:
    """Extract a numeric post ID from raw CLI input, URLs, or agent-format lines."""
    value = value.strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    bracket_match = re.search(r"\[(\d+)\]", value)
    if bracket_match:
        return int(bracket_match.group(1))
    url_match = re.search(r"https?://\S+", value)
    if url_match:
        candidate = url_match.group(0).rstrip(").,!?]")
        last = candidate.rstrip("/").split("/")[-1]
        if last.isdigit():
            return int(last)
    return None


def get_service(ctx: typer.Context, client=None):
    from pathlib import Path

    from mb import config
    from mb.services import MicroblogService

    client = client or get_client(ctx)
    options = ctx.obj or {}
    return MicroblogService(
        client,
        get_profile(ctx),
        client.default_destination,
        "cli",
        Path(options["state_file"])
        if options.get("state_file")
        else config.CONFIG_DIR / "mcp-state.sqlite3",
        media_root=Path(options["media_root"]) if options.get("media_root") else None,
    )


def cli_write(
    ctx: typer.Context, service, action: str, operation_id: str | None, arguments: dict
) -> dict:
    """Start one CLI operation; the shared service persists its claim before dispatch."""
    chosen_id = operation_id if operation_id is not None else f"cli-{uuid4().hex}"
    try:
        result = service.write(action, chosen_id, arguments)
    except Exception:
        # The service reports pre-claim failures as not_applied itself, so anything
        # raised here happened after the claim: dispatch or receipt persistence may
        # have succeeded. Never expose exception details or resend.
        result = {
            "ok": False,
            "error": "write_outcome_unknown",
            "code": 409,
            "outcome": "unknown",
            "operation_id": chosen_id,
        }
    return with_cli_recovery(ctx, service, result, "reply" if action == "post_reply" else "blog")


def with_cli_recovery(ctx: typer.Context, service, result: dict, scope: str | None = None) -> dict:
    """Provide a copyable read-only command for an uncertain receipt."""
    if result.get("outcome") != "unknown" or not result.get("operation_id"):
        return result
    command = ["mb", "--profile", service.profile, "--state-file", str(service.state.path)]
    if service.client.default_destination:
        command += ["--blog", service.client.default_destination]
    command += ["operation-status", result["operation_id"]]
    scope = scope or result.get("receipt_scope")
    if scope:
        command += ["--scope", scope]
    return {
        **result,
        "recovery_command": shlex.join(command),
        "recovery_hint": "The write may have succeeded. Inspect this receipt and the remote result before trying again. "
        "Rerunning a command without --operation-id starts a new operation and may duplicate it.",
    }
