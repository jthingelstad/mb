"""Attention-oriented mention triage for agents."""

from datetime import datetime, timezone

import typer

from mb import config
from mb.commands import add_content_text, get_client, get_format, get_profile, output_or_exit


def _item_id(item: dict) -> int | None:
    """Return an item's numeric ID if possible."""
    try:
        return int(item.get("id"))
    except (TypeError, ValueError):
        return None


def _items_since(items: list[dict], checkpoint: int | None) -> list[dict]:
    """Keep only items newer than a checkpoint ID."""
    if checkpoint is None:
        return items
    filtered = []
    for item in items:
        item_id = _item_id(item)
        if item_id is not None and item_id > checkpoint:
            filtered.append(item)
    return filtered


def _classify_item(client, username: str, item: dict) -> dict:
    """Classify one mention item with minimal conversation context."""
    item_id = _item_id(item)
    entry = {
        "reason": "mention",
        "thread_has_self_post": False,
        "thread_count": 0,
        "item": item,
    }
    if item_id is None:
        return entry

    conversation = client.get_conversation(item_id)
    if not conversation["ok"]:
        entry["conversation_error"] = conversation.get("error")
        return entry

    thread = conversation["data"].get("items", [])
    thread_data = {"items": thread}
    add_content_text(thread_data)
    entry["thread_count"] = len(thread)
    entry["thread_has_self_post"] = any(
        candidate.get("author", {}).get("_microblog", {}).get("username") == username
        and str(candidate.get("id")) != str(item_id)
        for candidate in thread
    )
    if entry["thread_has_self_post"]:
        entry["reason"] = "thread-reply"
    return entry


def _parse_timestamp(timestamp: str | None) -> datetime | None:
    """Parse an ISO timestamp into an aware datetime."""
    if not timestamp:
        return None
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None


def _item_matches_age(item: dict, fresh_hours: int | None, max_age_days: int | None) -> bool:
    """Return whether an inbox item passes recency filters."""
    if fresh_hours is None and max_age_days is None:
        return True
    published = _parse_timestamp(item.get("date_published"))
    if published is None:
        return False
    age = datetime.now(timezone.utc) - published.astimezone(timezone.utc)
    if fresh_hours is not None and age.total_seconds() > fresh_hours * 3600:
        return False
    if max_age_days is not None and age.total_seconds() > max_age_days * 86400:
        return False
    return True


def run(
    ctx: typer.Context,
    count: int = 10,
    advance: bool = False,
    reason: list[str] | None = None,
    fresh_hours: int | None = None,
    max_age_days: int | None = None,
    all_items: bool = False,
):
    """Return attention-oriented items from recent mentions."""
    client = get_client(ctx)
    fmt = get_format(ctx)
    profile = get_profile(ctx)
    checkpoint = None if all_items else config.get_named_checkpoint("inbox", profile=profile)

    requested_reasons = [item for item in (reason or []) if item]
    allowed_reasons = {"mention", "thread-reply"}
    invalid_reasons = [item for item in requested_reasons if item not in allowed_reasons]
    if invalid_reasons:
        output_or_exit({
            "ok": False,
            "error": f"Unknown inbox reason filter: {', '.join(invalid_reasons)}",
            "code": 400,
        }, fmt)
        return

    filters_active = bool(requested_reasons or fresh_hours is not None or max_age_days is not None)
    if advance and filters_active:
        output_or_exit({
            "ok": False,
            "error": "Cannot combine --advance with selective inbox filters; review filtered results first, then rerun inbox without filters to advance the cursor.",
            "code": 400,
        }, fmt)
        return

    identity = client.verify_token()
    if not identity["ok"]:
        output_or_exit(identity, fmt)
        return
    username = identity["data"].get("username", "")

    mentions = client.get_mentions()
    if not mentions["ok"]:
        output_or_exit(mentions, fmt)
        return

    add_content_text(mentions["data"])
    window = _items_since(mentions["data"].get("items", []), checkpoint)
    age_filtered = [
        item for item in window
        if _item_matches_age(item, fresh_hours=fresh_hours, max_age_days=max_age_days)
    ]
    if requested_reasons:
        classified_items = [_classify_item(client, username, item) for item in age_filtered]
        filtered_items = [item for item in classified_items if item.get("reason") in requested_reasons]
        items = filtered_items[:count]
        filtered_count = len(filtered_items)
    else:
        sample = age_filtered[:count]
        items = [_classify_item(client, username, item) for item in sample]
        filtered_count = len(age_filtered)
    latest_id = _item_id(window[0]) if window else checkpoint
    advanced = False
    if advance and latest_id is not None:
        config.save_named_checkpoint("inbox", latest_id, profile=profile)
        advanced = True

    output_or_exit({
        "ok": True,
        "data": {
            "kind": "inbox",
            "username": username,
            "mode": "since-checkpoint" if checkpoint is not None else "bootstrap",
            "checkpoint": checkpoint,
            "latest_id": latest_id,
            "advanced": advanced,
            "window_count": len(window),
            "new_count": filtered_count,
            "truncated": filtered_count > len(items),
            "filters": {
                "reason": requested_reasons,
                "fresh_hours": fresh_hours,
                "max_age_days": max_age_days,
                "all": all_items,
            },
            "items": items,
        },
    }, fmt)
