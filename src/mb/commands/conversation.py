"""Thread fetching — recursively fetch conversation to root."""

import typer

app = typer.Typer(no_args_is_help=False, invoke_without_command=True)


def _get_client(ctx: typer.Context = None):
    from mb.cli import get_client
    return get_client(ctx)


def _get_format(ctx: typer.Context) -> str:
    from mb.cli import get_format
    return get_format(ctx)


def _build_thread(items: list[dict]) -> list[dict]:
    """Take conversation items and return flat ordered list root→leaf with depth."""
    if not items:
        return []

    # Build a map of id -> item
    by_id: dict[str, dict] = {}
    children: dict[str, list[str]] = {}
    all_ids = set()
    parent_ids = set()

    for item in items:
        item_id = str(item.get("id", ""))
        by_id[item_id] = item
        all_ids.add(item_id)
        # micro.blog conversation API returns items with _microblog.reply_to_id
        mb_data = item.get("_microblog", {})
        parent_id = str(mb_data.get("reply_to_id", "")) if mb_data.get("reply_to_id") else None
        if parent_id:
            parent_ids.add(parent_id)
            children.setdefault(parent_id, []).append(item_id)

    # Find root(s): items that are not replies to anything in this set,
    # or items whose parent is not in the conversation
    roots = []
    for item in items:
        item_id = str(item.get("id", ""))
        mb_data = item.get("_microblog", {})
        parent_id = str(mb_data.get("reply_to_id", "")) if mb_data.get("reply_to_id") else None
        if not parent_id or parent_id not in all_ids:
            roots.append(item_id)

    # DFS to build ordered list with depth
    result = []

    def walk(node_id: str, depth: int):
        if node_id in by_id:
            entry = dict(by_id[node_id])
            entry["depth"] = depth
            result.append(entry)
        for child_id in children.get(node_id, []):
            walk(child_id, depth + 1)

    for root_id in roots:
        walk(root_id, 0)

    return result


@app.callback(invoke_without_command=True)
def conversation(
    ctx: typer.Context,
    post_id: int = typer.Argument(..., help="Post ID to fetch conversation for"),
):
    """Fetch full thread, recursively to root."""
    from mb.formatters import output, strip_html

    fmt = _get_format(ctx)
    client = _get_client()
    result = client.get_conversation(post_id)

    if not result["ok"]:
        output(result, fmt)
        raise SystemExit(1)

    items = result["data"].get("items", [])
    thread = _build_thread(items)

    # Add content_text to each item
    for item in thread:
        if "content_html" in item:
            item["content_text"] = strip_html(item["content_html"]).strip()

    output({"ok": True, "data": {"items": thread}}, fmt)
