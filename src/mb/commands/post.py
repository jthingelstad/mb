"""Publishing commands."""

import sys
from pathlib import Path

import typer

app = typer.Typer(no_args_is_help=True)


def _get_client():
    from mb.cli import get_client
    return get_client()


def _get_format(ctx: typer.Context) -> str:
    from mb.cli import get_format
    return get_format(ctx)


def _read_content(content: str) -> str:
    """If content is '-', read from stdin."""
    if content == "-":
        return sys.stdin.read().strip()
    return content


def _parse_file(path: str) -> tuple[str | None, str]:
    """Parse a markdown file. First # heading becomes title, rest is content."""
    text = Path(path).read_text()
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
    content: str = typer.Argument(None, help="Post content (use '-' for stdin)"),
    title: str = typer.Option(None, "--title", "-t", help="Post title"),
    draft: bool = typer.Option(False, "--draft", help="Create as draft"),
    file: str = typer.Option(None, "--file", help="Read content from markdown file"),
    photo: str = typer.Option(None, "--photo", help="Path to photo to upload"),
    alt: str = typer.Option(None, "--alt", help="Alt text for photo"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate without posting"),
):
    """Create a new post."""
    from mb.formatters import output

    fmt = _get_format(ctx)
    client = _get_client()

    # Resolve content
    if file:
        file_title, file_content = _parse_file(file)
        if not title:
            title = file_title
        content = file_content
    elif content:
        content = _read_content(content)
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
    )
    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)


@app.command()
def reply(
    ctx: typer.Context,
    post_id: str = typer.Argument(..., help="Post ID or URL to reply to"),
    content: str = typer.Argument(..., help="Reply content (use '-' for stdin)"),
):
    """Reply to a post."""
    from mb.formatters import output

    fmt = _get_format(ctx)
    client = _get_client()
    content = _read_content(content)

    if not content:
        output({"ok": False, "error": "Content is empty", "code": 400}, fmt)
        raise SystemExit(1)

    # If post_id looks like a bare ID, construct the URL
    reply_to = post_id
    if not post_id.startswith("http"):
        reply_to = f"https://micro.blog/{post_id}"

    result = client.micropub_create(content=content, reply_to=reply_to)
    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)


@app.command()
def delete(
    ctx: typer.Context,
    post_id: str = typer.Argument(..., help="Post ID or URL to delete"),
):
    """Delete a post."""
    from mb.formatters import output

    fmt = _get_format(ctx)
    client = _get_client()

    url = post_id
    if not post_id.startswith("http"):
        # Need to resolve the post URL — list posts and find it
        listing = client.micropub_list()
        if not listing["ok"]:
            output(listing, fmt)
            raise SystemExit(1)
        items = listing["data"].get("items", [])
        matched = [i for i in items if str(i.get("url", "")).rstrip("/").endswith(post_id)]
        if not matched:
            output({"ok": False, "error": f"Post {post_id} not found", "code": 404}, fmt)
            raise SystemExit(1)
        url = matched[0]["url"]

    result = client.micropub_delete(url)
    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)


@app.command("list")
def list_posts(
    ctx: typer.Context,
    drafts: bool = typer.Option(False, "--drafts", help="List only drafts"),
):
    """List your posts."""
    from mb.formatters import output

    fmt = _get_format(ctx)
    client = _get_client()
    result = client.micropub_list(drafts=drafts)
    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)
