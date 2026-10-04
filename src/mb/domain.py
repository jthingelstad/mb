"""Shared post normalization, thread ordering and mention classification."""


def add_content_text(data: dict) -> None:
    """Add content_text (stripped HTML) to all items in a response."""
    from mb.formatters import strip_html

    for item in data.get("items", []):
        if "content_html" in item:
            item["content_text"] = strip_html(item["content_html"]).strip()


def _extract_author_username(author: dict) -> str:
    """Extract username from an author object."""
    mb = author.get("_microblog")
    if isinstance(mb, dict) and mb.get("username"):
        return mb["username"]
    url = author.get("url", "")
    if url:
        parts = url.rstrip("/").split("/")
        if parts:
            return parts[-1]
    return author.get("name", "")


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


def _item_id(item: dict) -> int | None:
    """Return an item's numeric ID if possible."""
    value = item.get("id")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
