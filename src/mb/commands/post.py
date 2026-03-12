"""Publishing commands."""

import sys
from pathlib import Path

import typer

from mb.commands import get_client, get_format, get_username, output_or_exit, resolve_post_url, add_content_text

app = typer.Typer(no_args_is_help=True, rich_markup_mode=None)


def _read_content(content: str) -> str:
    """If content is '-', read from stdin."""
    if content == "-":
        return sys.stdin.read().strip()
    return content


def _parse_file(path: str) -> tuple[str | None, str]:
    """Parse a markdown file. First # heading becomes title, rest is content."""
    try:
        text = Path(path).read_text()
    except FileNotFoundError:
        raise FileNotFoundError(f"File not found: {path}")
    except OSError as e:
        raise OSError(f"Cannot read file: {path} ({e})")
    lines = text.split("\n")
    title = None
    content_lines = []
    for i, line in enumerate(lines):
        if i == 0 and line.startswith("# "):
            title = line[2:].strip()
        else:
            content_lines.append(line)
    content = "\n".join(content_lines).strip()
    return title, content


@app.command()
def new(
    ctx: typer.Context,
    content_arg: str = typer.Argument(None, help="Post content (use '-' for stdin)"),
    content_opt: str = typer.Option(None, "--content", help="Post content (use '-' for stdin)"),
    title: str = typer.Option(None, "--title", "-t", help="Post title"),
    draft: bool = typer.Option(False, "--draft", help="Create as draft"),
    file: str = typer.Option(None, "--file", help="Read content from markdown file"),
    photo: str = typer.Option(None, "--photo", help="Path to photo to upload"),
    alt: str = typer.Option(None, "--alt", help="Alt text for photo"),
    category: list[str] = typer.Option(None, "--category", "-c", help="Categories/tags for the post"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate without posting"),
):
    """Create a new post."""
    from mb.formatters import output

    fmt = get_format(ctx)
    client = get_client(ctx)

    # Resolve content
    provided_sources = sum([
        file is not None,
        content_opt is not None,
        content_arg is not None,
    ])
    if provided_sources > 1:
        output({"ok": False, "error": "Provide exactly one content source: positional content, --content, or --file", "code": 400}, fmt)
        raise SystemExit(1)

    if file:
        try:
            file_title, file_content = _parse_file(file)
        except (FileNotFoundError, OSError) as e:
            output({"ok": False, "error": str(e), "code": 400}, fmt)
            raise SystemExit(1)
        if not title:
            title = file_title
        content = file_content
    elif content_opt is not None:
        content = _read_content(content_opt)
    elif content_arg is not None:
        content = _read_content(content_arg)
    else:
        output({"ok": False, "error": "No content provided. Pass content, --file, or pipe via stdin with '-'", "code": 400}, fmt)
        raise SystemExit(1)

    if not content:
        output({"ok": False, "error": "Content is empty", "code": 400}, fmt)
        raise SystemExit(1)

    if dry_run:
        output({"ok": True, "data": {
            "dry_run": True,
            "title": title,
            "content": content,
            "draft": draft,
            "photo": photo,
            "categories": category,
        }}, fmt)
        return

    # Upload photo if provided
    photo_url = None
    if photo:
        upload = client.micropub_upload_photo(photo, alt=alt)
        if not upload["ok"]:
            output(upload, fmt)
            raise SystemExit(1)
        photo_url = upload["data"]["url"]

    result = client.micropub_create(
        content=content,
        title=title,
        draft=draft,
        photo_url=photo_url,
        categories=category or None,
    )
    output_or_exit(result, fmt)


@app.command("get")
def get_post(
    ctx: typer.Context,
    post_id: str = typer.Argument(..., help="Post ID or URL to fetch"),
):
    """Fetch a single post by ID or URL."""
    from mb.formatters import output

    fmt = get_format(ctx)
    client = get_client(ctx)

    url = resolve_post_url(client, post_id, fmt)
    result = client.micropub_get(url)
    output_or_exit(result, fmt)


@app.command()
def edit(
    ctx: typer.Context,
    post_id: str = typer.Argument(..., help="Post ID or URL to edit"),
    content: str = typer.Option(None, "--content", help="New content (use '-' for stdin)"),
    title: str = typer.Option(None, "--title", "-t", help="New title"),
    category: list[str] = typer.Option(None, "--category", "-c", help="Replace categories"),
):
    """Edit an existing post."""
    from mb.formatters import output

    fmt = get_format(ctx)
    client = get_client(ctx)

    if content == "-":
        content = sys.stdin.read().strip()

    if content is None and title is None and category is None:
        output({"ok": False, "error": "Nothing to update — provide --content, --title, or --category", "code": 400}, fmt)
        raise SystemExit(1)

    url = resolve_post_url(client, post_id, fmt)
    result = client.micropub_update(
        url,
        content=content,
        title=title,
        categories=category or None,
    )
    output_or_exit(result, fmt)


def _extract_post_id(post_id: str) -> int | None:
    """Extract a numeric post ID from a bare ID or micro.blog URL.

    Supports:
      - Bare numeric ID: "85444185"
      - micro.blog conversation URL: "https://micro.blog/username/85444185"

    Returns None if the ID cannot be extracted.
    """
    if post_id.isdigit():
        return int(post_id)
    if post_id.startswith("http"):
        # micro.blog URLs end with /username/id
        last = post_id.rstrip("/").split("/")[-1]
        if last.isdigit():
            return int(last)
    return None


@app.command()
def reply(
    ctx: typer.Context,
    post_id: str = typer.Argument(..., help="Post ID or URL to reply to"),
    content: str = typer.Argument(..., help="Reply content (use '-' for stdin)"),
):
    """Reply to a post via the native micro.blog API."""
    from mb.formatters import output
    from mb.commands import _extract_author_username

    fmt = get_format(ctx)
    client = get_client(ctx)
    content = _read_content(content)

    if not content:
        output({"ok": False, "error": "Content is empty", "code": 400}, fmt)
        raise SystemExit(1)

    numeric_id = _extract_post_id(post_id)
    if numeric_id is None:
        output({"ok": False, "error": f"Cannot extract numeric post ID from: {post_id}", "code": 400}, fmt)
        raise SystemExit(1)

    # Look up the post to find the author's username
    conv = client.get_conversation(numeric_id)
    if not conv["ok"]:
        output(conv, fmt)
        raise SystemExit(1)

    username = None
    for item in conv["data"].get("items", []):
        if str(item.get("id")) == str(numeric_id):
            username = _extract_author_username(item.get("author", {}))
            break

    if not username:
        output({"ok": False, "error": f"Post {post_id} not found in conversation", "code": 404}, fmt)
        raise SystemExit(1)

    # Prepend @username if not already present
    if not content.lstrip().startswith(f"@{username}"):
        content = f"@{username} {content}"

    result = client.post_reply(numeric_id, content)
    output_or_exit(result, fmt)


@app.command()
def delete(
    ctx: typer.Context,
    post_id: str = typer.Argument(..., help="Post ID or URL to delete"),
):
    """Delete a post."""
    from mb.formatters import output

    fmt = get_format(ctx)
    client = get_client(ctx)

    url = resolve_post_url(client, post_id, fmt)
    result = client.micropub_delete(url)
    output_or_exit(result, fmt)


@app.command("list")
def list_posts(
    ctx: typer.Context,
    drafts: bool = typer.Option(False, "--drafts", help="List only drafts"),
):
    """List your posts."""
    fmt = get_format(ctx)
    client = get_client(ctx)
    result = client.micropub_list(drafts=drafts)
    if result["ok"]:
        # Normalize Micropub h-entry items to JSON Feed format for formatters
        items = result["data"].get("items", [])
        if items and "properties" in items[0]:
            username = get_username(ctx)
            normalized = client._normalize_micropub_items(items, owner=username)
            result["data"]["items"] = normalized
        add_content_text(result["data"])
    output_or_exit(result, fmt)
