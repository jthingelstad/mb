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
    if not isinstance(items, list):
        raise ValueError("Invalid conversation items")
    by_id: dict[str, dict] = {}
    children: dict[str, list[str]] = {}
    parents: dict[str, str | None] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Invalid conversation item")
        identifier = item.get("id")
        if (
            isinstance(identifier, bool)
            or not isinstance(identifier, (str, int))
            or not str(identifier)
        ):
            raise ValueError("Missing conversation ID")
        item_id = str(identifier)
        if item_id in by_id:
            raise ValueError("Duplicate conversation ID")
        mb_data = item.get("_microblog", {})
        if not isinstance(mb_data, dict):
            raise ValueError("Invalid conversation extension")
        parent = mb_data.get("reply_to_id")
        if parent is not None and (isinstance(parent, bool) or not isinstance(parent, (str, int))):
            raise ValueError("Invalid conversation parent")
        parent_id = str(parent) if parent else None
        by_id[item_id] = item
        parents[item_id] = parent_id
        if parent_id:
            children.setdefault(parent_id, []).append(item_id)

    roots = [identifier for identifier, parent in parents.items() if parent not in by_id]
    result = []
    visited = set()
    # Iterative preorder preserves feed sibling order without a recursion limit.
    stack = [(identifier, 0) for identifier in reversed(roots)]
    while stack:
        identifier, depth = stack.pop()
        if identifier in visited:
            raise ValueError("Cyclic conversation")
        visited.add(identifier)
        result.append({**by_id[identifier], "depth": depth})
        stack.extend((child, depth + 1) for child in reversed(children.get(identifier, [])))
    if len(visited) != len(by_id):
        raise ValueError("Cyclic conversation")
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
