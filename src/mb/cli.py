"""Typer entrypoint; registers all command groups."""

import os
import sys
from typing import Annotated, Optional

import typer

from mb import config
from mb.api import MicroblogClient
from mb.commands import blog, conversation, memory, post, timeline, user
from mb.formatters import output

app = typer.Typer(add_completion=False, no_args_is_help=True)
app.add_typer(post.app, name="post", help="Publishing commands")
app.add_typer(timeline.app, name="timeline", help="Reading/discovery commands")
app.add_typer(user.app, name="user", help="Social graph commands")
app.add_typer(blog.app, name="blog", help="Read your own blog")
app.add_typer(memory.app, name="memory", help="Agent long-term memory")

# ── Global options ──────────────────────────────────────────


def get_format(ctx: typer.Context) -> str:
    """Resolve output format from --human flag or --format option."""
    return ctx.obj.get("format", "json") if ctx.obj else "json"


def get_profile(ctx: typer.Context) -> str:
    """Resolve the active profile name."""
    return ctx.obj.get("profile", config.DEFAULT_PROFILE) if ctx.obj else config.DEFAULT_PROFILE


def get_client(ctx: typer.Context | None = None) -> MicroblogClient:
    """Build a client from the configured token, or exit with JSON error."""
    profile = get_profile(ctx) if ctx else config.DEFAULT_PROFILE
    token = config.get_token(profile=profile)
    if not token:
        output({"ok": False, "error": "No token configured. Run: mb auth <token>", "code": 401})
        raise SystemExit(1)
    blog_dest = None
    if ctx and ctx.obj:
        blog_dest = ctx.obj.get("blog")
    if not blog_dest:
        blog_dest = config.get_blog(profile=profile)
    client = MicroblogClient(token=token)
    client.default_destination = blog_dest
    return client


@app.callback()
def main(
    ctx: typer.Context,
    fmt: str = typer.Option("json", "--format", "-f", help="Output format: json | human | agent"),
    human: bool = typer.Option(False, "--human", help="Shortcut for --format human"),
    profile: str = typer.Option("default", "--profile", "-p", help="Config profile to use"),
    blog_name: str = typer.Option(None, "--blog", "-b", help="Blog destination (name or URL)"),
):
    """mb — micro.blog CLI for agents."""
    ctx.ensure_object(dict)
    if human:
        fmt = "human"
    else:
        # MB_FORMAT env var as default; explicit --format flag overrides
        import click
        fmt_source = ctx.get_parameter_source("fmt")
        explicitly_set = fmt_source is not None and fmt_source != click.core.ParameterSource.DEFAULT
        if not explicitly_set:
            env_fmt = os.environ.get("MB_FORMAT")
            if env_fmt:
                fmt = env_fmt
    ctx.obj["format"] = fmt
    ctx.obj["profile"] = profile
    if blog_name:
        ctx.obj["blog"] = blog_name


# ── Auth commands (top-level) ───────────────────────────────

@app.command()
def auth(
    ctx: typer.Context,
    token: str = typer.Argument(..., help="micro.blog app token"),
    blog_dest: str = typer.Option(None, "--blog", help="Default blog destination for this profile"),
):
    """Store token and verify it works."""
    fmt = get_format(ctx)
    profile = get_profile(ctx)
    client = MicroblogClient(token=token)
    result = client.verify_token()
    if result["ok"]:
        username = result["data"].get("username", "")
        config.save_config(token=token, username=username, blog=blog_dest, profile=profile)
        data = {"username": username, "message": "Token saved", "profile": profile}
        if blog_dest:
            data["blog"] = blog_dest
        output({"ok": True, "data": data}, fmt)
    else:
        output(result, fmt)
        raise SystemExit(1)


@app.command()
def whoami(ctx: typer.Context):
    """Return username and blog URL as JSON."""
    fmt = get_format(ctx)
    client = get_client(ctx)
    result = client.verify_token()
    if result["ok"]:
        data = result["data"]
        output({"ok": True, "data": {
            "username": data.get("username", ""),
            "url": f"https://{data.get('default_site', '')}" if data.get("default_site") else data.get("url", ""),
            "name": data.get("name") or data.get("full_name", ""),
            "avatar": data.get("avatar") or data.get("gravatar_url", ""),
            "profile": get_profile(ctx),
        }}, fmt)
    else:
        output(result, fmt)
        raise SystemExit(1)


@app.command()
def profiles(ctx: typer.Context):
    """List all configured profiles."""
    fmt = get_format(ctx)
    result = config.list_profiles()
    output({"ok": True, "data": {"profiles": result}}, fmt)


@app.command()
def blogs(ctx: typer.Context):
    """List available blogs for the current token."""
    fmt = get_format(ctx)
    client = get_client(ctx)
    result = client.micropub_get_config()
    if result["ok"]:
        destinations = result["data"].get("destination", [])
        output({"ok": True, "data": {"blogs": destinations}}, fmt)
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

    client = get_client(ctx)
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
