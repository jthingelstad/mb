"""Shared helpers for command modules."""

import typer


def get_client(ctx: typer.Context = None):
    from mb.cli import get_client as _get_client
    return _get_client(ctx)


def get_format(ctx: typer.Context) -> str:
    from mb.cli import get_format as _get_format
    return _get_format(ctx)


def get_profile(ctx: typer.Context) -> str:
    from mb.cli import get_profile as _get_profile
    return _get_profile(ctx)


def get_username(ctx: typer.Context) -> str:
    """Resolve the current username from config or by verifying the token."""
    from mb import config
    from mb.formatters import output

    profile = get_profile(ctx)
    username = config.get_username(profile=profile)
    if username:
        return username

    client = get_client(ctx)
    result = client.verify_token()
    if result["ok"]:
        return result["data"].get("username", "")

    fmt = get_format(ctx)
    output({"ok": False, "error": "Cannot determine username. Run: mb auth <token>", "code": 401}, fmt)
    raise SystemExit(1)


def output_or_exit(result: dict, fmt: str) -> None:
    """Output a result and exit with code 1 if not ok."""
    from mb.formatters import output
    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)


def add_content_text(data: dict) -> None:
    """Add content_text (stripped HTML) to all items in a response."""
    from mb.formatters import strip_html
    for item in data.get("items", []):
        if "content_html" in item:
            item["content_text"] = strip_html(item["content_html"]).strip()


def _micropub_item_url(item: dict) -> str:
    """Extract URL from a Micropub h-entry item or a flat JSON Feed item."""
    # Micropub h-entry format: properties.url[0]
    props = item.get("properties", {})
    url_list = props.get("url", [])
    if url_list:
        return str(url_list[0])
    # Flat format
    return str(item.get("url", ""))


def resolve_post_url(client, post_id: str, fmt: str):
    """Resolve a bare post ID to a full URL for Micropub operations.

    - Full URLs pass through as-is.
    - Bare numeric IDs are resolved via the conversation API (which returns
      items with both ``id`` and ``url`` fields).
    - Other identifiers (slugs) fall back to micropub listing suffix match.

    Returns the URL string, or calls output + SystemExit(1) on failure.
    """
    from mb.formatters import output

    if post_id.startswith("http"):
        return post_id

    # Bare numeric ID — resolve via conversation API
    if post_id.isdigit():
        result = client.get_conversation(int(post_id))
        if not result["ok"]:
            output(result, fmt)
            raise SystemExit(1)
        for item in result["data"].get("items", []):
            if str(item.get("id")) == post_id:
                url = item.get("url", "")
                if url:
                    return url
        output({"ok": False, "error": f"Post {post_id} not found", "code": 404}, fmt)
        raise SystemExit(1)

    # Slug-based identifier — fall back to micropub listing suffix match
    listing = client.micropub_list()
    if not listing["ok"]:
        output(listing, fmt)
        raise SystemExit(1)
    items = listing["data"].get("items", [])
    matched = [
        i for i in items
        if _micropub_item_url(i).rstrip("/").endswith(post_id)
    ]
    if not matched:
        output({"ok": False, "error": f"Post {post_id} not found", "code": 404}, fmt)
        raise SystemExit(1)
    return _micropub_item_url(matched[0])



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
