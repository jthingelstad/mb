"""Typer entrypoint; registers all command groups."""

import os
import sys

import typer
import typer.core

from mb import config
from mb.api import MicroblogClient
from mb.commands import blog, checkpoint, conversation, lookup, media, post, timeline, user
from mb.commands import catchup as catchup_cmd
from mb.commands import guide as guide_cmd
from mb.commands import heartbeat as heartbeat_cmd
from mb.commands import inbox as inbox_cmd
from mb.commands import upload as upload_cmd
from mb.formatters import output


class _FlexibleGroup(typer.core.TyperGroup):
    """Group that allows global options (-p, -f, --human, -b) after the subcommand."""

    _VALUED_OPTS = {
        "-p",
        "--profile",
        "-f",
        "--format",
        "-b",
        "--blog",
        "--state-file",
        "--media-root",
    }
    _FLAG_OPTS = {"--human"}
    _VERSION_OPTS = {"--version", "-V"}

    def parse_args(self, ctx, args):
        args = list(args)
        front = []
        rest = []
        i = 0
        while i < len(args):
            if args[i] in self._VALUED_OPTS and i + 1 < len(args):
                front.extend([args[i], args[i + 1]])
                i += 2
            elif args[i].startswith("--") and args[i].split("=", 1)[0] in self._VALUED_OPTS:
                front.append(args[i])
                i += 1
            elif args[i] in self._FLAG_OPTS:
                front.append(args[i])
                i += 1
            else:
                rest.append(args[i])
                i += 1
        # Only a leading --version/-V asks for the version; later it may be content.
        if rest and rest[0] in self._VERSION_OPTS:
            fmt = _requested_format(front)
            _exit_on_invalid_format(fmt)
            version = package_version()
            if fmt == "json":
                output({"ok": True, "data": {"version": version}}, fmt)
            else:
                typer.echo(f"mb {version}")
            ctx.exit(0)
        return super().parse_args(ctx, front + rest)

    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except config.ConfigError as exc:
            fmt = (ctx.obj or {}).get("format", "agent")
            output({"ok": False, "error": str(exc), "code": 400}, fmt)
            raise SystemExit(1) from None


FORMATS = ("agent", "json", "human")


def package_version() -> str:
    """Return the installed distribution version without importing optional extras."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("mb")
    except PackageNotFoundError:
        return "unknown"


def _requested_format(front: list[str]) -> str:
    """Resolve the format from hoisted global options the way the main callback does."""
    fmt = None
    i = 0
    while i < len(front):
        arg = front[i]
        if arg == "--human":
            return "human"
        if arg in {"-f", "--format"} and i + 1 < len(front):
            fmt = front[i + 1]
            i += 2
            continue
        if arg.startswith("--format="):
            fmt = arg.split("=", 1)[1]
        i += 1
    return fmt if fmt is not None else os.environ.get("MB_FORMAT") or "agent"


def _exit_on_invalid_format(fmt: str, source: str = "--format") -> None:
    if fmt not in FORMATS:
        typer.echo(
            f"Error: unknown output format {fmt!r} from {source}; use agent, json or human",
            err=True,
        )
        raise SystemExit(2)


app = typer.Typer(
    cls=_FlexibleGroup, add_completion=False, no_args_is_help=True, rich_markup_mode=None
)
app.add_typer(media.app, name="media", help="Preview and upload reviewed local images")
app.add_typer(post.app, name="post", help="Publishing commands")
app.add_typer(timeline.app, name="timeline", help="Reading/discovery commands")
app.add_typer(user.app, name="user", help="Social graph commands")
app.add_typer(lookup.app, name="lookup", help="Lookup additional data for pipeline inputs")
app.add_typer(blog.app, name="blog", help="Read your own blog")
app.add_typer(
    checkpoint.app, name="checkpoint", help="Manage saved checkpoints for agent workflows"
)

# ── Global options ──────────────────────────────────────────


def get_format(ctx: typer.Context) -> str:
    """Resolve output format from --human flag or --format option."""
    return ctx.obj.get("format", "agent") if ctx.obj else "agent"


def get_profile(ctx: typer.Context) -> str:
    """Resolve the active profile name."""
    return ctx.obj.get("profile", config.DEFAULT_PROFILE) if ctx.obj else config.DEFAULT_PROFILE


def get_client(ctx: typer.Context | None = None) -> MicroblogClient:
    """Build a client from the configured token, or exit with JSON error."""
    profile = get_profile(ctx) if ctx else config.DEFAULT_PROFILE
    token = config.get_token(profile=profile)
    if not token:
        fmt = get_format(ctx) if ctx else "agent"
        output(
            {"ok": False, "error": "No token configured. Run: mb auth <token>", "code": 401}, fmt
        )
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
    fmt: str = typer.Option("agent", "--format", "-f", help="Output format: agent | json | human"),
    human: bool = typer.Option(False, "--human", help="Shortcut for --format human"),
    profile: str = typer.Option("default", "--profile", "-p", help="Config profile to use"),
    blog_name: str = typer.Option(None, "--blog", "-b", help="Blog destination (name or URL)"),
    state_file: str | None = typer.Option(
        None, "--state-file", help="Shared local operation receipts"
    ),
    media_root: str | None = typer.Option(
        None, "--media-root", help="Explicit allowed local image directory"
    ),
    show_version: bool = typer.Option(
        False, "--version", "-V", help="Print the mb version and exit"
    ),
):
    """mb — micro.blog CLI for agents."""
    ctx.ensure_object(dict)
    source = "--format"
    if human:
        fmt = "human"
    else:
        # MB_FORMAT env var as default; explicit --format flag overrides
        fmt_source = ctx.get_parameter_source("fmt")
        explicitly_set = fmt_source is not None and fmt_source.name != "DEFAULT"
        if not explicitly_set:
            env_fmt = os.environ.get("MB_FORMAT")
            if env_fmt:
                fmt = env_fmt
                source = "MB_FORMAT"
    _exit_on_invalid_format(fmt, source)
    ctx.obj["format"] = fmt
    config.validate_name("profile", profile)
    ctx.obj["profile"] = profile
    ctx.obj["state_file"] = state_file
    ctx.obj["media_root"] = media_root
    if blog_name:
        ctx.obj["blog"] = blog_name


# ── Auth commands (top-level) ───────────────────────────────


@app.command()
def auth(
    ctx: typer.Context,
    token: str = typer.Argument(
        ..., help="micro.blog app token, or - to read it from stdin (keeps it out of shell history)"
    ),
    blog_dest: str = typer.Option(None, "--blog", help="Default blog destination for this profile"),
):
    """Store token and verify it works."""
    fmt = get_format(ctx)
    profile = get_profile(ctx)
    if token == "-":
        token = sys.stdin.read().strip()
        if not token:
            output({"ok": False, "error": "No token on stdin", "code": 400}, fmt)
            raise SystemExit(1)
    client = MicroblogClient(token=token)
    result = client.verify_token()
    if result["ok"]:
        username = result["data"].get("username", "")
        # Flexible global option parsing moves --blog into the parent context.
        blog_dest = blog_dest or ctx.obj.get("blog")
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
        output(
            {
                "ok": True,
                "data": {
                    "username": data.get("username", ""),
                    "url": f"https://{data.get('default_site', '')}"
                    if data.get("default_site")
                    else data.get("url", ""),
                    "name": data.get("name") or data.get("full_name", ""),
                    "avatar": data.get("avatar") or data.get("gravatar_url", ""),
                    "profile": get_profile(ctx),
                },
            },
            fmt,
        )
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


@app.command()
def guide(ctx: typer.Context):
    """Show agent-oriented workflow guide for mb commands."""
    guide_cmd.run(fmt=get_format(ctx))


@app.command("following")
def following_alias(
    ctx: typer.Context,
    username: str = typer.Argument(
        None, help="Username to check following list (defaults to current user)"
    ),
):
    """List who you follow."""
    user.following(ctx, username=username)


@app.command("follow")
def follow_alias(
    ctx: typer.Context,
    username: str = typer.Argument(..., help="Username to follow, or '-' to read from stdin"),
):
    """Follow one or more users."""
    user.follow(ctx, username=username)


@app.command("unfollow")
def unfollow_alias(
    ctx: typer.Context,
    username: str = typer.Argument(..., help="Username to unfollow, or '-' to read from stdin"),
):
    """Unfollow one or more users."""
    user.unfollow(ctx, username=username)


@app.command("discover")
def discover_alias(
    ctx: typer.Context,
    collection: str = typer.Option(
        None, "--collection", "-c", help="Discover collection name (e.g. books, music)"
    ),
    list_collections: bool = typer.Option(
        False, "--list", help="List curated discover collections"
    ),
    count: int = typer.Option(20, "--count", "-n", min=1, max=50),
):
    """Show posts from a Micro.blog Discover collection."""
    timeline.discover(ctx, collection=collection, list_collections=list_collections, count=count)


@app.command()
def heartbeat(
    ctx: typer.Context,
    count: int = typer.Option(
        3, "--count", "-n", min=1, max=50, help="Maximum timeline items to include (1-50)"
    ),
    mention_count: int = typer.Option(
        3, "--mention-count", min=0, max=50, help="Maximum mention items to include (0-50)"
    ),
    mentions_only: bool = typer.Option(
        False, "--mentions-only", help="Only include mention/reply activity"
    ),
    no_advance: bool = typer.Option(
        False, "--no-advance", help="Do not advance the heartbeat checkpoint after this run"
    ),
):
    """Return a compact session-start snapshot for an agent. Advances the checkpoint by default."""
    heartbeat_cmd.run(
        ctx,
        count=count,
        mention_count=mention_count,
        mentions_only=mentions_only,
        no_advance=no_advance,
    )


@app.command()
def inbox(
    ctx: typer.Context,
    count: int = typer.Option(10, "--count", "-n", min=1, help="Maximum inbox items to include"),
    reason: list[str] = typer.Option(
        None, "--reason", help="Filter inbox items by reason: mention or thread-reply"
    ),
    fresh_hours: int = typer.Option(
        None, "--fresh-hours", min=1, help="Only include items newer than this many hours"
    ),
    max_age_days: int = typer.Option(
        None, "--max-age-days", min=1, help="Only include items newer than this many days"
    ),
    all_items: bool = typer.Option(
        False, "--all", help="Ignore the saved inbox checkpoint and inspect all recent mentions"
    ),
    advance: bool = typer.Option(
        False, "--advance", help="Save the newest seen inbox item as the inbox checkpoint"
    ),
):
    """Return attention-oriented mention items for an agent."""
    inbox_cmd.run(
        ctx,
        count=count,
        advance=advance,
        reason=reason,
        fresh_hours=fresh_hours,
        max_age_days=max_age_days,
        all_items=all_items,
    )


@app.command()
def catchup(
    ctx: typer.Context,
    count: int = typer.Option(
        20, "--count", "-n", min=1, max=50, help="Maximum timeline items to include (1-50)"
    ),
    advance: bool = typer.Option(
        False, "--advance", help="Save the newest seen post ID as the catchup checkpoint"
    ),
):
    """Return new timeline items since the last catchup checkpoint."""
    catchup_cmd.run(ctx, count=count, advance=advance)


@app.command()
def upload(
    ctx: typer.Context,
    source: str = typer.Argument(..., help="Reviewed relative image under --media-root"),
    alt: str = typer.Option(None, "--alt", help="Alt text for the uploaded image"),
    sha256: str | None = typer.Option(None, "--sha256", help="Input hash from media preview"),
    operation_id: str | None = typer.Option(
        None,
        "--operation-id",
        help="Optional stable retry ID; omitted IDs start a new saved operation",
    ),
):
    """Alias for media upload; requires the reviewed hash and alt text."""
    upload_cmd.run(ctx, source=source, alt=alt, sha256=sha256, operation_id=operation_id)


# ── Conversation (top-level) ───────────────────────────────

app.add_typer(conversation.app, name="conversation", help="Thread fetching")


# ── Poll utility (top-level) ──────────────────────────────


@app.command()
def poll(
    ctx: typer.Context,
    since: int = typer.Option(..., "--since", help="Post ID to poll since"),
    interval: int = typer.Option(
        30, "--interval", min=1, max=3600, help="Seconds between polls (1-3600)"
    ),
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


@app.command("mcp")
def mcp_command(
    ctx: typer.Context,
    consumer: str = typer.Option(
        "default",
        "--consumer",
        help="Name for this client's independent attention checkpoints",
    ),
    read_only: bool = typer.Option(
        False, "--read-only", help="Disable remote writes and checkpoint acknowledgement"
    ),
):
    """Serve optional MCP tools over local stdio. Install mb[mcp] first."""
    from pathlib import Path

    try:
        import anyio

        from mb.mcp_server import serve
        from mb.services import AuthenticationUnavailable, MicroblogService
    except ImportError:
        typer.echo(
            "MCP support is optional. Install it with: brew install jthingelstad/mb/mb "
            "or uv tool install --from git+https://github.com/jthingelstad/mb 'mb[mcp]'",
            err=True,
        )
        raise typer.Exit(1) from None
    profile = get_profile(ctx)
    blog_dest = ctx.obj.get("blog")
    state_file = ctx.obj.get("state_file")
    state_path = Path(state_file) if state_file else config.CONFIG_DIR / "mcp-state.sqlite3"

    def service_factory():
        token = config.get_token(profile=profile)
        if not token:
            raise AuthenticationUnavailable("No token configured")
        return MicroblogService(
            MicroblogClient(token),
            profile,
            blog_dest or config.get_blog(profile=profile),
            consumer,
            state_path,
            read_only,
            media_root=Path(ctx.obj["media_root"]) if ctx.obj.get("media_root") else None,
        )

    anyio.run(serve, service_factory)


@app.command("operation-status")
def operation_status(
    ctx: typer.Context,
    operation_id: str | None = typer.Argument(None),
    latest: bool = typer.Option(
        False, "--latest", help="Inspect the newest receipt in this account/blog"
    ),
    scope: str | None = typer.Option(None, help="Receipt scope: blog or reply"),
    resolve: str | None = typer.Option(
        None,
        "--resolve",
        help="After checking the blog yourself, record applied or not_applied for a "
        "pending/unknown receipt",
    ),
    note: str | None = typer.Option(None, "--note", help="Why the receipt was resolved"),
):
    """Read the shared CLI/MCP durable write receipt."""
    from mb.commands import get_service, output_or_exit, with_cli_recovery

    if latest == (operation_id is not None):
        output_or_exit(
            {
                "ok": False,
                "error": "Provide an operation ID or --latest, but not both",
                "code": 400,
            },
            get_format(ctx),
        )
        return
    if resolve is not None or note is not None:
        refusal = None
        if resolve not in {"applied", "not_applied"}:
            refusal = "Use --resolve applied or --resolve not_applied (--note needs --resolve)"
        elif latest:
            refusal = "Resolve an explicit operation ID, not --latest"
        if refusal:
            output_or_exit({"ok": False, "error": refusal, "code": 400}, get_format(ctx))
            return
        assert operation_id is not None and resolve is not None
        result = get_service(ctx).resolve_operation(operation_id, resolve, scope, note)
        output_or_exit(result, get_format(ctx))
        return
    service = get_service(ctx)
    if latest:
        result = service.latest_operation_status(scope)
    else:
        assert operation_id is not None
        result = service.operation_status(operation_id, scope)
    output_or_exit(with_cli_recovery(ctx, service, result, scope), get_format(ctx))
