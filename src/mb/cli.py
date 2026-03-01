"""Typer entrypoint; registers all command groups."""

import sys
from typing import Annotated, Optional

import typer

from mb import config
from mb.api import MicroblogClient
from mb.commands import conversation, post, timeline, user
from mb.formatters import output

app = typer.Typer(add_completion=False, no_args_is_help=True)
app.add_typer(post.app, name="post", help="Publishing commands")
app.add_typer(timeline.app, name="timeline", help="Reading/discovery commands")
app.add_typer(user.app, name="user", help="Social graph commands")
app.registered_commands  # force registration

# ── Global options ──────────────────────────────────────────

Format = Annotated[str, typer.Option("--format", "-f", help="Output format: json | human | agent")]


def get_format(ctx: typer.Context) -> str:
    """Resolve output format from --human flag or --format option."""
    return ctx.obj.get("format", "json") if ctx.obj else "json"


def get_client() -> MicroblogClient:
    """Build a client from the configured token, or exit with JSON error."""
    token = config.get_token()
    if not token:
        output({"ok": False, "error": "No token configured. Run: mb auth <token>", "code": 401})
        raise SystemExit(1)
    return MicroblogClient(token=token)


@app.callback()
def main(
    ctx: typer.Context,
    fmt: str = typer.Option("json", "--format", "-f", help="Output format: json | human | agent"),
    human: bool = typer.Option(False, "--human", help="Shortcut for --format human"),
):
    """mb — micro.blog CLI for agents."""
    ctx.ensure_object(dict)
    if human:
        fmt = "human"
    ctx.obj["format"] = fmt


# ── Auth commands (top-level) ───────────────────────────────

@app.command()
def auth(
    ctx: typer.Context,
    token: str = typer.Argument(..., help="micro.blog app token"),
):
    """Store token and verify it works."""
    fmt = get_format(ctx)
    client = MicroblogClient(token=token)
    result = client.verify_token()
    if result["ok"]:
        username = result["data"].get("username", "")
        config.save_config(token=token, username=username)
        output({"ok": True, "data": {"username": username, "message": "Token saved"}}, fmt)
    else:
        output(result, fmt)
        raise SystemExit(1)


@app.command()
def whoami(ctx: typer.Context):
    """Return username and blog URL as JSON."""
    fmt = get_format(ctx)
    client = get_client()
    result = client.verify_token()
    if result["ok"]:
        data = result["data"]
        output({"ok": True, "data": {
            "username": data.get("username", ""),
            "url": data.get("url", ""),
            "name": data.get("name", ""),
            "avatar": data.get("avatar", ""),
        }}, fmt)
    else:
        output(result, fmt)
        raise SystemExit(1)


# ── Conversation (top-level) ───────────────────────────────

app.add_typer(conversation.app, name="conversation", help="Thread fetching")


# ── Poll utility (top-level) ──────────────────────────────

@app.command()
def poll(
    ctx: typer.Context,
    since: int = typer.Option(..., "--since", help="Post ID to poll since"),
    interval: int = typer.Option(30, "--interval", help="Seconds between polls"),
):
    """Emit JSON events to stdout; ctrl-c to stop."""
    import json
    import time

    client = get_client()
    current_since = since
    try:
        while True:
            result = client.check_timeline(since_id=current_since)
            if result["ok"]:
                data = result["data"]
                event = {
                    "ok": True,
                    "data": {
                        "new_count": data.get("count", 0),
                        "check_seconds": data.get("check_seconds", interval),
                    },
                }
                json.dump(event, sys.stdout)
                sys.stdout.write("\n")
                sys.stdout.flush()
                # If there are new posts, fetch them
                count = data.get("count", 0)
                if count > 0:
                    tl = client.get_timeline(count=count, since_id=current_since)
                    if tl["ok"]:
                        items = tl["data"].get("items", [])
                        if items:
                            # Update since_id to the newest post
                            current_since = items[0].get("id", current_since)
                            event = {"ok": True, "data": {"posts": items}}
                            json.dump(event, sys.stdout)
                            sys.stdout.write("\n")
                            sys.stdout.flush()
                poll_interval = data.get("check_seconds", interval)
            else:
                json.dump(result, sys.stdout)
                sys.stdout.write("\n")
                sys.stdout.flush()
                poll_interval = interval
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        pass
