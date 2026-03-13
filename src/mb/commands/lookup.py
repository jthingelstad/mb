"""Lookup commands for enriching existing records in a pipeline."""

from concurrent.futures import ThreadPoolExecutor
import re
import sys

import typer

from mb.api import MicroblogClient
from mb.commands import add_content_text, extract_post_id, get_client, get_format, output_or_exit
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


def _normalize_post_identifier(value: str) -> str:
    """Normalize a post identifier from raw CLI or stdin input."""
    value = value.strip()
    post_id = extract_post_id(value)
    if post_id is not None:
        return str(post_id)
    url_match = re.search(r"https?://\S+", value)
    if url_match:
        return url_match.group(0).rstrip(").,!?]")
    return value


def _read_post_identifiers_from_stdin() -> list[str]:
    """Read newline-delimited post identifiers from stdin."""
    identifiers = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        normalized = _normalize_post_identifier(line)
        if extract_post_id(normalized) is not None or normalized.startswith(("http://", "https://")):
            identifiers.append(normalized)
    return identifiers


def _resolve_post_identifiers(identifiers: list[str] | None) -> list[str]:
    """Resolve post identifiers from args or stdin and deduplicate them."""
    if identifiers:
        if len(identifiers) == 1 and identifiers[0] == "-":
            if sys.stdin.isatty():
                return []
            raw = _read_post_identifiers_from_stdin()
        else:
            raw = [_normalize_post_identifier(identifier) for identifier in identifiers]
    else:
        if sys.stdin.isatty():
            return []
        raw = _read_post_identifiers_from_stdin()

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


def _lookup_post_record(client: MicroblogClient, identifier: str) -> dict:
    """Fetch a post record and optional conversation data."""
    post_id = extract_post_id(identifier)
    if post_id is not None:
        conversation = client.get_conversation(post_id)
        if not conversation["ok"]:
            return {
                "ok": False,
                "identifier": identifier,
                "error": conversation.get("error"),
                "code": conversation.get("code"),
            }
        thread_data = {"items": conversation["data"].get("items", [])}
        add_content_text(thread_data)
        for item in thread_data["items"]:
            if str(item.get("id")) == str(post_id):
                return {
                    "ok": True,
                    "identifier": identifier,
                    "item": item,
                    "conversation_items": thread_data["items"],
                }
        return {"ok": False, "identifier": identifier, "error": "Post not found in conversation", "code": 404}

    if identifier.startswith("http://") or identifier.startswith("https://"):
        source = client.micropub_get(identifier)
        if not source["ok"]:
            return {
                "ok": False,
                "identifier": identifier,
                "error": source.get("error"),
                "code": source.get("code"),
            }
        normalized = client._normalize_micropub_items([source["data"]])
        if not normalized:
            return {"ok": False, "identifier": identifier, "error": "Post not found", "code": 404}
        add_content_text({"items": normalized})
        item = normalized[0]
        if not item.get("url"):
            item["url"] = identifier
        return {
            "ok": True,
            "identifier": identifier,
            "item": item,
            "conversation_items": [],
        }

    return {"ok": False, "identifier": identifier, "error": f"Unsupported post identifier: {identifier}", "code": 400}


def _fetch_post_lookup(token: str, base_url: str, identifier: str,
                       include_post: bool, include_conversation: bool) -> dict:
    """Fetch lookup data for one post."""
    client = MicroblogClient(token=token, base_url=base_url)
    try:
        record = _lookup_post_record(client, identifier)
    finally:
        client.close()

    if not record["ok"]:
        return record

    item = record["item"]
    result = {
        "ok": True,
        "identifier": identifier,
        "id": item.get("id"),
        "url": item.get("url"),
        "date_published": item.get("date_published"),
        "author_username": item.get("author", {}).get("_microblog", {}).get("username"),
    }
    if include_post:
        result["content_text"] = item.get("content_text") or strip_html(item.get("content_html", "")).strip()
    if include_conversation:
        result["conversation_items"] = record["conversation_items"]
        result["conversation_count"] = len(record["conversation_items"])
    return result


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


@app.command("posts")
def posts(
    ctx: typer.Context,
    identifiers: list[str] = typer.Argument(None, help="Post IDs or URLs to look up; omit to read from stdin"),
    post: bool = typer.Option(False, "--post", help="Include the matched post content"),
    conversation: bool = typer.Option(False, "--conversation", help="Include the full conversation thread"),
    concurrency: int = typer.Option(8, "--concurrency", min=1, max=32, help="Maximum concurrent lookups"),
):
    """Look up post and conversation data from stdin or explicit identifiers."""
    from mb.formatters import output

    fmt = get_format(ctx)
    if not post and not conversation:
        output({"ok": False, "error": "Choose at least one lookup: --post or --conversation", "code": 400}, fmt)
        raise SystemExit(1)

    resolved = _resolve_post_identifiers(identifiers)
    if not resolved:
        output({"ok": False, "error": "No post identifiers provided. Pass IDs/URLs or pipe them on stdin.", "code": 400}, fmt)
        raise SystemExit(1)

    client = get_client(ctx)
    workers = min(concurrency, len(resolved))
    results_by_identifier = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _fetch_post_lookup,
                client.token,
                client.base_url,
                identifier,
                post,
                conversation,
            ): identifier
            for identifier in resolved
        }
        for future, identifier in futures.items():
            results_by_identifier[identifier] = future.result()

    posts_data = []
    errors = []
    for identifier in resolved:
        item = results_by_identifier[identifier]
        if item.get("ok"):
            entry = {
                "identifier": identifier,
                "id": item.get("id"),
                "url": item.get("url"),
                "date_published": item.get("date_published"),
                "author_username": item.get("author_username"),
            }
            if "content_text" in item:
                entry["content_text"] = item.get("content_text")
            if "conversation_items" in item:
                entry["conversation_items"] = item.get("conversation_items")
                entry["conversation_count"] = item.get("conversation_count")
            posts_data.append(entry)
        else:
            errors.append({
                "identifier": identifier,
                "error": item.get("error"),
                "code": item.get("code"),
            })

    output_or_exit({
        "ok": True,
        "data": {
            "kind": "lookup_posts",
            "posts": posts_data,
            "errors": errors,
            "criteria": {
                "post": post,
                "conversation": conversation,
            },
        },
    }, fmt)
