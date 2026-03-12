"""Social graph commands."""

import re
import sys
from datetime import datetime, timezone

import typer

from mb.commands import get_client, get_format, get_username, output_or_exit

app = typer.Typer(no_args_is_help=True, rich_markup_mode=None)


def _normalize_username(value: str) -> str:
    """Normalize a username from raw CLI or stdin input."""
    value = value.strip()
    match = re.search(r"@([A-Za-z0-9_-]+)", value)
    if match:
        return match.group(1)
    token = value.split()[0] if value.split() else ""
    return token.lstrip("@")


def _read_usernames_from_stdin() -> list[str]:
    """Read newline-delimited usernames from stdin."""
    usernames = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        usernames.append(_normalize_username(line))
    return usernames


def _parse_timestamp(timestamp: str | None) -> datetime | None:
    """Parse an ISO timestamp from the API."""
    if not timestamp:
        return None
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _days_since(timestamp: str | None) -> int | None:
    """Return whole days since an ISO timestamp."""
    dt = _parse_timestamp(timestamp)
    if dt is None:
        return None
    delta = datetime.now(timezone.utc) - dt
    return max(0, int(delta.total_seconds() // 86400))


def _resolve_batch_usernames(username: str) -> list[str]:
    """Resolve a username argument or stdin batch input."""
    raw = _read_usernames_from_stdin() if username == "-" else [_normalize_username(username)]
    deduped = []
    seen = set()
    for item in raw:
        if not item or item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _run_batch_action(ctx: typer.Context, username: str, action_name: str, action_fn) -> None:
    """Run follow/unfollow actions against one or many usernames."""
    from mb.formatters import output

    fmt = get_format(ctx)
    client = get_client(ctx)
    usernames = _resolve_batch_usernames(username)
    if not usernames:
        output({"ok": False, "error": "No usernames provided on stdin", "code": 400}, fmt)
        raise SystemExit(1)

    if len(usernames) == 1:
        output_or_exit(action_fn(client, usernames[0]), fmt)
        return

    results = []
    error_count = 0
    for name in usernames:
        result = action_fn(client, name)
        results.append({
            "username": name,
            "ok": result.get("ok", False),
            "error": result.get("error"),
            "code": result.get("code"),
        })
        if not result.get("ok"):
            error_count += 1

    response = {
        "ok": error_count == 0,
        "data": {
            "action": action_name,
            "count": len(results),
            "ok_count": len(results) - error_count,
            "error_count": error_count,
            "results": results,
        },
    }
    if error_count:
        response["error"] = f"{error_count} {action_name} operation(s) failed"
        response["code"] = 400
    output(response, fmt)
    if error_count:
        raise SystemExit(1)


@app.command()
def show(ctx: typer.Context, username: str = typer.Argument(..., help="Username to look up")):
    """Show user profile."""
    output_or_exit(get_client(ctx).get_user(username), get_format(ctx))


@app.command()
def following(
    ctx: typer.Context,
    username: str = typer.Argument(None, help="Username to check following list (defaults to current user)"),
    inactive_days: int = typer.Option(None, "--inactive-days", "--filter-days", min=0, help="Only show accounts inactive for at least this many days"),
):
    """List who a user is following."""
    fmt = get_format(ctx)
    client = get_client(ctx)
    target_username = username or get_username(ctx)
    result = client.get_following(target_username)
    if result["ok"] and inactive_days is not None:
        filtered = []
        for entry in result["data"]:
            if not isinstance(entry, dict) or not entry.get("username"):
                continue
            profile = client.get_user(entry["username"])
            if not profile["ok"]:
                output_or_exit(profile, fmt)
            items = profile["data"].get("items", [])
            last_post_date = items[0].get("date_published") if items else None
            age_days = _days_since(last_post_date)
            enriched = dict(entry)
            enriched["last_post_date"] = last_post_date
            enriched["inactive_days"] = age_days
            enriched["has_posts"] = bool(items)
            enriched["is_inactive"] = age_days is None or age_days >= inactive_days
            if enriched["is_inactive"]:
                filtered.append(enriched)
        result = {"ok": True, "data": filtered}
    output_or_exit(result, fmt)


@app.command("discover")
def discover_user(ctx: typer.Context, username: str = typer.Argument(None, help="Username to discover from (defaults to current user)")):
    """List accounts someone follows that you do not."""
    target_username = username or get_username(ctx)
    output_or_exit(get_client(ctx).get_user_discover(target_username), get_format(ctx))


@app.command()
def follow(ctx: typer.Context, username: str = typer.Argument(..., help="Username to follow")):
    """Follow a user."""
    _run_batch_action(ctx, username, "follow", lambda client, value: client.follow(value))


@app.command()
def unfollow(ctx: typer.Context, username: str = typer.Argument(..., help="Username to unfollow")):
    """Unfollow a user."""
    _run_batch_action(ctx, username, "unfollow", lambda client, value: client.unfollow(value))


@app.command("is-following")
def is_following(ctx: typer.Context, username: str = typer.Argument(..., help="Username to check")):
    """Check if you are following a user."""
    output_or_exit(get_client(ctx).is_following(username), get_format(ctx))


@app.command()
def mute(ctx: typer.Context, value: str = typer.Argument(..., help="Username or keyword to mute")):
    """Mute a user or keyword."""
    output_or_exit(get_client(ctx).mute(value), get_format(ctx))


@app.command()
def muting(ctx: typer.Context):
    """List muted users/keywords."""
    output_or_exit(get_client(ctx).get_muting(), get_format(ctx))


@app.command()
def unmute(ctx: typer.Context, mute_id: int = typer.Argument(..., help="Mute ID to remove")):
    """Remove a mute."""
    output_or_exit(get_client(ctx).unmute(mute_id), get_format(ctx))


@app.command()
def block(ctx: typer.Context, username: str = typer.Argument(..., help="Username to block")):
    """Block a user."""
    output_or_exit(get_client(ctx).block(username), get_format(ctx))


@app.command()
def blocking(ctx: typer.Context):
    """List blocked users."""
    output_or_exit(get_client(ctx).get_blocking(), get_format(ctx))


@app.command()
def unblock(ctx: typer.Context, block_id: int = typer.Argument(..., help="Block ID to remove")):
    """Remove a block."""
    output_or_exit(get_client(ctx).unblock(block_id), get_format(ctx))
