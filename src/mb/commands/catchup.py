"""Bounded timeline catch-up for agents."""

import typer

from mb import config
from mb.commands import add_content_text, get_client, get_format, get_profile, output_or_exit


def _item_id(item: dict) -> int | None:
    """Return an item's numeric ID if possible."""
    try:
        return int(item.get("id"))
    except (TypeError, ValueError):
        return None


def run(
    ctx: typer.Context,
    count: int = 20,
    advance: bool = False,
):
    """Return new timeline items since the last catchup checkpoint."""
    client = get_client(ctx)
    fmt = get_format(ctx)
    profile = get_profile(ctx)
    checkpoint = config.get_named_checkpoint("catchup", profile=profile)

    if checkpoint is None:
        result = client.get_timeline(count=count)
        mode = "bootstrap"
        total_new = None
    else:
        result = client.get_timeline(count=count, since_id=checkpoint)
        check = client.check_timeline(since_id=checkpoint)
        if not check["ok"]:
            output_or_exit(check, fmt)
            return
        mode = "since-checkpoint"
        total_new = int(check["data"].get("count", 0))

    if not result["ok"]:
        output_or_exit(result, fmt)
        return

    add_content_text(result["data"])
    items = result["data"].get("items", [])[:count]
    latest_id = _item_id(items[0]) if items else checkpoint
    truncated = total_new is not None and total_new > len(items)
    advanced = False
    if advance and latest_id is not None:
        config.save_named_checkpoint("catchup", latest_id, profile=profile)
        advanced = True

    output_or_exit({
        "ok": True,
        "data": {
            "kind": "catchup",
            "mode": mode,
            "checkpoint": checkpoint,
            "latest_id": latest_id,
            "advanced": advanced,
            "new_count": total_new if total_new is not None else len(items),
            "truncated": truncated,
            "items": items,
        },
    }, fmt)
