"""Shared helpers for command modules."""

import typer


def get_client(ctx: typer.Context = None):
    from mb.cli import get_client as _get_client
    return _get_client(ctx)


def get_format(ctx: typer.Context) -> str:
    from mb.cli import get_format as _get_format
    return _get_format(ctx)


def get_profile(ctx: typer.Context) -> str:
    from mb.cli import get_profile as _get_profile
    return _get_profile(ctx)


def get_username(ctx: typer.Context) -> str:
    """Resolve the current username from config or by verifying the token."""
    from mb import config
    from mb.formatters import output

    profile = get_profile(ctx)
    username = config.get_username(profile=profile)
    if username:
        return username

    client = get_client(ctx)
    result = client.verify_token()
    if result["ok"]:
        return result["data"].get("username", "")

    fmt = get_format(ctx)
    output({"ok": False, "error": "Cannot determine username. Run: mb auth <token>", "code": 401}, fmt)
    raise SystemExit(1)


def output_or_exit(result: dict, fmt: str) -> None:
    """Output a result and exit with code 1 if not ok."""
    from mb.formatters import output
    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)


def add_content_text(data: dict) -> None:
    """Add content_text (stripped HTML) to all items in a response."""
    from mb.formatters import strip_html
    for item in data.get("items", []):
        if "content_html" in item:
            item["content_text"] = strip_html(item["content_html"]).strip()
