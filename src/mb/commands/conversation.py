"""Thread fetching — recursively fetch conversation to root."""

import typer

from mb.commands import get_client, get_format, add_content_text

app = typer.Typer(no_args_is_help=False, invoke_without_command=True)


def _build_thread(items: list[dict]) -> list[dict]:
    """Take conversation items and return flat ordered list root->leaf with depth."""
    if not items:
        return []

    by_id: dict[str, dict] = {}
    children: dict[str, list[str]] = {}
    all_ids = set()

    for item in items:
        item_id = str(item.get("id", ""))
        by_id[item_id] = item
        all_ids.add(item_id)
        mb_data = item.get("_microblog", {})
        parent_id = str(mb_data.get("reply_to_id", "")) if mb_data.get("reply_to_id") else None
        if parent_id:
            children.setdefault(parent_id, []).append(item_id)

    roots = []
    for item in items:
        item_id = str(item.get("id", ""))
        mb_data = item.get("_microblog", {})
        parent_id = str(mb_data.get("reply_to_id", "")) if mb_data.get("reply_to_id") else None
        if not parent_id or parent_id not in all_ids:
            roots.append(item_id)

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
    from mb.formatters import output

    fmt = get_format(ctx)
    client = get_client(ctx)
    result = client.get_conversation(post_id)

    if not result["ok"]:
        output(result, fmt)
        raise SystemExit(1)

    items = result["data"].get("items", [])
    thread = _build_thread(items)
    thread_data = {"items": thread}
    add_content_text(thread_data)

    output({"ok": True, "data": thread_data}, fmt)
