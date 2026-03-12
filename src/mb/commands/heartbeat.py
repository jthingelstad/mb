"""Compact session-start snapshot for agents."""

import typer

from mb import config
from mb.commands import add_content_text, get_client, get_format, get_profile, output_or_exit


def _item_id(item: dict) -> int | None:
    """Return an item's numeric ID if possible."""
    try:
        return int(item.get("id"))
    except (TypeError, ValueError):
        return None


def _filter_items_since(items: list[dict], since_id: int | None) -> list[dict]:
    """Keep only items newer than a checkpoint ID."""
    if since_id is None:
        return items
    filtered = []
    for item in items:
        item_id = _item_id(item)
        if item_id is not None and item_id > since_id:
            filtered.append(item)
    return filtered


def _latest_seen_id(*groups: list[dict]) -> int | None:
    """Return the newest numeric post ID across all groups."""
    newest = None
    for group in groups:
        for item in group:
            item_id = _item_id(item)
            if item_id is None:
                continue
            if newest is None or item_id > newest:
                newest = item_id
    return newest


def run(
    ctx: typer.Context,
    count: int = 3,
    mention_count: int = 3,
    mentions_only: bool = False,
    advance: bool = False,
):
    """Build a compact heartbeat summary from current identity and recent activity."""
    client = get_client(ctx)
    fmt = get_format(ctx)
    profile = get_profile(ctx)
    checkpoint = config.get_named_checkpoint("heartbeat", profile=profile)

    identity = client.verify_token()
    if not identity["ok"]:
        output_or_exit(identity, fmt)
        return

    latest_timeline = client.get_timeline(count=1)
    if not latest_timeline["ok"]:
        output_or_exit(latest_timeline, fmt)
        return
    add_content_text(latest_timeline["data"])
    latest_timeline_items = latest_timeline["data"].get("items", [])

    if mentions_only:
        timeline_items = []
        timeline_total = 0
    elif checkpoint is None:
        timeline_result = latest_timeline if count == 1 else client.get_timeline(count=count)
        if not timeline_result["ok"]:
            output_or_exit(timeline_result, fmt)
            return
        add_content_text(timeline_result["data"])
        timeline_items = timeline_result["data"].get("items", [])[:count]
        timeline_total = len(timeline_items)
    else:
        check = client.check_timeline(since_id=checkpoint)
        if not check["ok"]:
            output_or_exit(check, fmt)
            return
        timeline_total = int(check["data"].get("count", 0))
        timeline_result = client.get_timeline(count=max(count, 1), since_id=checkpoint)
        if not timeline_result["ok"]:
            output_or_exit(timeline_result, fmt)
            return
        add_content_text(timeline_result["data"])
        timeline_items = timeline_result["data"].get("items", [])[:count]

    mentions_result = client.get_mentions()
    if not mentions_result["ok"]:
        output_or_exit(mentions_result, fmt)
        return
    add_content_text(mentions_result["data"])
    mention_window = _filter_items_since(mentions_result["data"].get("items", []), checkpoint)
    mention_total = len(mention_window)
    mention_items = mention_window[:mention_count]

    latest_seen = _latest_seen_id(latest_timeline_items, timeline_items, mention_window)
    advanced = False
    if advance and latest_seen is not None:
        config.save_named_checkpoint("heartbeat", latest_seen, profile=profile)
        advanced = True

    account = identity["data"]
    output_or_exit({
        "ok": True,
        "data": {
            "kind": "heartbeat",
            "username": account.get("username", ""),
            "url": f"https://{account.get('default_site', '')}" if account.get("default_site") else account.get("url", ""),
            "profile": profile,
            "mode": "since-checkpoint" if checkpoint is not None else "bootstrap",
            "checkpoint": checkpoint,
            "latest_id": latest_seen,
            "advanced": advanced,
            "new_timeline_count": timeline_total,
            "new_mentions_count": mention_total,
            "timeline": timeline_items,
            "mentions": mention_items,
        },
    }, fmt)
