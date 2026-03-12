"""Lookup commands for enriching existing records in a pipeline."""

from concurrent.futures import ThreadPoolExecutor
import sys

import typer

from mb.api import MicroblogClient
from mb.commands import get_client, get_format, output_or_exit
from mb.commands.user import _days_since, _normalize_username, _read_usernames_from_stdin
from mb.formatters import strip_html

app = typer.Typer(no_args_is_help=True, rich_markup_mode=None)


def _resolve_usernames(usernames: list[str] | None) -> list[str]:
    """Resolve usernames from args or stdin and deduplicate them."""
    if usernames:
        if len(usernames) == 1 and usernames[0] == "-":
            if sys.stdin.isatty():
                return []
            raw = _read_usernames_from_stdin()
        else:
            raw = [_normalize_username(username) for username in usernames]
    else:
        if sys.stdin.isatty():
            return []
        raw = _read_usernames_from_stdin()

    deduped = []
    seen = set()
    for item in raw:
        if not item or item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _fetch_user_lookup(token: str, base_url: str, username: str, include_last_post: bool,
                       include_days_since: bool) -> dict:
    """Fetch lookup data for one user."""
    client = MicroblogClient(token=token, base_url=base_url)
    try:
        profile = client.get_user(username)
    finally:
        client.close()

    if not profile["ok"]:
        return {
            "ok": False,
            "username": username,
            "error": profile.get("error"),
            "code": profile.get("code"),
        }

    items = profile["data"].get("items", [])
    latest = items[0] if items else {}
    last_post_date = latest.get("date_published") if latest else None

    record = {
        "ok": True,
        "username": username,
    }
    if include_last_post:
        record["last_post_date"] = last_post_date
        record["last_post_id"] = latest.get("id")
        record["last_post_url"] = latest.get("url")
        record["last_post_content_text"] = strip_html(latest.get("content_html", "")).strip() if latest else None
    if include_days_since:
        record["inactive_days"] = _days_since(last_post_date)
    return record


@app.command("users")
def users(
    ctx: typer.Context,
    usernames: list[str] = typer.Argument(None, help="Usernames to look up; omit to read from stdin"),
    last_post: bool = typer.Option(False, "--last-post", help="Include the most recent post"),
    days_since_posting: bool = typer.Option(False, "--days-since-posting", help="Include days since the most recent post"),
    concurrency: int = typer.Option(8, "--concurrency", min=1, max=32, help="Maximum concurrent lookups"),
):
    """Look up additional data about users from stdin or explicit usernames."""
    from mb.formatters import output

    fmt = get_format(ctx)
    if not last_post and not days_since_posting:
        output({"ok": False, "error": "Choose at least one lookup: --last-post or --days-since-posting", "code": 400}, fmt)
        raise SystemExit(1)

    resolved = _resolve_usernames(usernames)
    if not resolved:
        output({"ok": False, "error": "No usernames provided. Pass usernames or pipe them on stdin.", "code": 400}, fmt)
        raise SystemExit(1)

    client = get_client(ctx)
    workers = min(concurrency, len(resolved))
    results_by_username = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _fetch_user_lookup,
                client.token,
                client.base_url,
                username,
                last_post,
                days_since_posting,
            ): username
            for username in resolved
        }
        for future, username in futures.items():
            results_by_username[username] = future.result()

    users = []
    errors = []
    for username in resolved:
        item = results_by_username[username]
        if item.get("ok"):
            entry = {"username": username}
            for key in (
                "inactive_days",
                "last_post_date",
                "last_post_id",
                "last_post_url",
                "last_post_content_text",
            ):
                if key in item:
                    entry[key] = item.get(key)
            users.append(entry)
        else:
            errors.append({
                "username": username,
                "error": item.get("error"),
                "code": item.get("code"),
            })

    output_or_exit({
        "ok": True,
        "data": {
            "users": users,
            "errors": errors,
            "criteria": {
                "last_post": last_post,
                "days_since_posting": days_since_posting,
            },
        },
    }, fmt)
