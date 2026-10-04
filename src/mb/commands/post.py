"""Publishing commands."""

import sys
from pathlib import Path

import typer

from mb.commands import (
    add_content_text,
    extract_post_id,
    get_client,
    get_format,
    get_service,
    get_username,
    output_or_exit,
    resolve_post_url,
)

app = typer.Typer(no_args_is_help=True, rich_markup_mode=None)
SHORT_POST_LIMIT = 300


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


def _resolve_new_post_content(
    content_arg: str | None, content_opt: str | None, file: str | None
) -> tuple[str | None, str]:
    """Resolve content inputs for a new post command."""
    provided_sources = sum(
        [
            file is not None,
            content_opt is not None,
            content_arg is not None,
        ]
    )
    if provided_sources > 1:
        raise ValueError(
            "Provide exactly one content source: positional content, --content, or --file"
        )

    if file:
        file_title, file_content = _parse_file(file)
        return file_title, file_content
    if content_opt is not None:
        return None, _read_content(content_opt)
    if content_arg is not None:
        return None, _read_content(content_arg)
    raise ValueError("No content provided. Pass content, --file, or pipe via stdin with '-'")


def _validate_photo_sources(photo: str | None, photo_url: str | None) -> None:
    """Ensure only one photo source is provided."""
    if photo and photo_url:
        raise ValueError("Provide only one photo source: --photo or --photo-url")


@app.command()
def new(
    ctx: typer.Context,
    content_arg: str | None = typer.Argument(None, help="Post content (use '-' for stdin)"),
    content_opt: str | None = typer.Option(
        None, "--content", help="Post content (use '-' for stdin)"
    ),
    title: str | None = typer.Option(None, "--title", "-t", help="Post title"),
    draft: bool = typer.Option(False, "--draft", help="Create as draft"),
    file: str | None = typer.Option(None, "--file", help="Read content from markdown file"),
    photo: str | None = typer.Option(None, "--photo", help="Path to photo to upload"),
    photo_url: str | None = typer.Option(
        None, "--photo-url", help="Existing uploaded photo URL to attach"
    ),
    alt: str | None = typer.Option(None, "--alt", help="Alt text for photo"),
    category: list[str] | None = typer.Option(
        None, "--category", "-c", help="Categories/tags for the post"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate without posting"),
    operation_id: str | None = typer.Option(None, "--operation-id", help="Stable write receipt ID"),
):
    """Create a new post."""
    from mb.formatters import output

    fmt = get_format(ctx)
    client = get_client(ctx)

    try:
        file_title, content = _resolve_new_post_content(content_arg, content_opt, file)
    except (ValueError, FileNotFoundError, OSError) as e:
        output({"ok": False, "error": str(e), "code": 400}, fmt)
        raise SystemExit(1)
    if not title:
        title = file_title

    from mb.services import preview_post

    validation = preview_post(content, photo_url=photo_url)
    if not validation["ok"]:
        output(validation, fmt)
        raise SystemExit(1)

    try:
        _validate_photo_sources(photo, photo_url)
    except ValueError as e:
        output({"ok": False, "error": str(e), "code": 400}, fmt)
        raise SystemExit(1)

    if operation_id and photo:
        output(
            {
                "ok": False,
                "error": "Receipt writes require an existing --photo-url; use media preview/upload first",
                "code": 400,
            },
            fmt,
        )
        raise SystemExit(1)
    if alt is not None and not (photo or photo_url):
        output({"ok": False, "error": "Alt text requires a photo", "code": 400}, fmt)
        raise SystemExit(1)

    if dry_run:
        output(
            {
                "ok": True,
                "data": {
                    "dry_run": True,
                    "title": title,
                    "content": content,
                    "draft": draft,
                    "photo": photo or photo_url,
                    "photo_alt": alt,
                    "categories": category,
                },
            },
            fmt,
        )
        return

    # Upload photo if provided
    if photo:
        identity = get_service(ctx, client).identity()
        if not identity["ok"]:
            output_or_exit(identity, fmt)
            return
        client.default_destination = identity["data"]["blog"]
        upload = client.micropub_upload_photo(photo, alt=alt)
        if not upload["ok"]:
            output(upload, fmt)
            raise SystemExit(1)
        photo_url = upload["data"]["url"]

    from mb.services import create_post

    arguments = dict(
        content=content,
        title=title,
        draft=draft,
        photo_url=photo_url,
        photo_alt=alt,
        categories=category or None,
    )
    result = (
        get_service(ctx).write("post_create", operation_id, arguments)
        if operation_id
        else create_post(client, **arguments)
    )
    output_or_exit(result, fmt)


@app.command("short")
def short(
    ctx: typer.Context,
    content_arg: str = typer.Argument(None, help="Short post content (use '-' for stdin)"),
    content_opt: str = typer.Option(
        None, "--content", help="Short post content (use '-' for stdin)"
    ),
    draft: bool = typer.Option(False, "--draft", help="Create as draft"),
    file: str = typer.Option(None, "--file", help="Read short post content from markdown file"),
    photo: str = typer.Option(None, "--photo", help="Path to photo to upload"),
    photo_url: str = typer.Option(
        None, "--photo-url", help="Existing uploaded photo URL to attach"
    ),
    alt: str = typer.Option(None, "--alt", help="Alt text for photo"),
    category: list[str] = typer.Option(
        None, "--category", "-c", help="Categories/tags for the post"
    ),
    strict_300: bool = typer.Option(
        False, "--strict-300", help=f"Fail if content exceeds {SHORT_POST_LIMIT} characters"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate without posting"),
    operation_id: str | None = typer.Option(None, "--operation-id", help="Stable write receipt ID"),
):
    """Create a short-form post without a title."""
    from mb.formatters import output

    fmt = get_format(ctx)
    client = get_client(ctx)

    try:
        file_title, content = _resolve_new_post_content(content_arg, content_opt, file)
    except (ValueError, FileNotFoundError, OSError) as e:
        output({"ok": False, "error": str(e), "code": 400}, fmt)
        raise SystemExit(1)

    if file_title:
        content = f"# {file_title}\n\n{content}".strip()

    from mb.services import preview_post

    validation = preview_post(content, photo_url=photo_url)
    if not validation["ok"]:
        output(validation, fmt)
        raise SystemExit(1)

    try:
        _validate_photo_sources(photo, photo_url)
    except ValueError as e:
        output({"ok": False, "error": str(e), "code": 400}, fmt)
        raise SystemExit(1)

    char_count = len(content)
    warnings = []
    if char_count > SHORT_POST_LIMIT:
        if strict_300:
            output(
                {
                    "ok": False,
                    "error": f"Short posts must be {SHORT_POST_LIMIT} characters or fewer with --strict-300",
                    "code": 400,
                },
                fmt,
            )
            raise SystemExit(1)
        warnings.append(f"content exceeds {SHORT_POST_LIMIT} characters")

    if operation_id and photo:
        output(
            {
                "ok": False,
                "error": "Receipt writes require an existing --photo-url; use media preview/upload first",
                "code": 400,
            },
            fmt,
        )
        raise SystemExit(1)
    if alt is not None and not (photo or photo_url):
        output({"ok": False, "error": "Alt text requires a photo", "code": 400}, fmt)
        raise SystemExit(1)

    if dry_run:
        output(
            {
                "ok": True,
                "data": {
                    "dry_run": True,
                    "short": True,
                    "content": content,
                    "char_count": char_count,
                    "draft": draft,
                    "photo": photo or photo_url,
                    "photo_alt": alt,
                    "categories": category,
                    "warnings": warnings,
                },
            },
            fmt,
        )
        return

    if photo:
        identity = get_service(ctx, client).identity()
        if not identity["ok"]:
            output_or_exit(identity, fmt)
            return
        client.default_destination = identity["data"]["blog"]
        upload = client.micropub_upload_photo(photo, alt=alt)
        if not upload["ok"]:
            output(upload, fmt)
            raise SystemExit(1)
        photo_url = upload["data"]["url"]

    from mb.services import create_post

    arguments = dict(
        content=content,
        draft=draft,
        photo_url=photo_url,
        photo_alt=alt,
        categories=category or None,
    )
    result = (
        get_service(ctx).write("post_create", operation_id, arguments)
        if operation_id
        else create_post(client, **arguments)
    )
    if result.get("ok"):
        result["data"]["short"] = True
        result["data"]["char_count"] = char_count
        if warnings:
            result["data"]["warnings"] = warnings
    output_or_exit(result, fmt)


@app.command("get")
def get_post(
    ctx: typer.Context,
    post_id: str = typer.Argument(..., help="Post ID or URL to fetch"),
):
    """Fetch a single post by ID or URL."""

    fmt = get_format(ctx)
    client = get_client(ctx)

    url = resolve_post_url(client, post_id, fmt)
    from mb.services import read_source

    result = read_source(client, url)
    output_or_exit(result, fmt)


@app.command()
def edit(
    ctx: typer.Context,
    post_id: str = typer.Argument(..., help="Post ID or URL to edit"),
    content: str = typer.Option(None, "--content", help="New content (use '-' for stdin)"),
    title: str = typer.Option(None, "--title", "-t", help="New title"),
    category: list[str] = typer.Option(None, "--category", "-c", help="Replace categories"),
    operation_id: str | None = typer.Option(None, "--operation-id", help="Stable write receipt ID"),
):
    """Edit an existing post."""
    from mb.formatters import output

    fmt = get_format(ctx)
    client = get_client(ctx)

    if content == "-":
        content = sys.stdin.read().strip()

    if content is None and title is None and category is None:
        output(
            {
                "ok": False,
                "error": "Nothing to update — provide --content, --title, or --category",
                "code": 400,
            },
            fmt,
        )
        raise SystemExit(1)

    if operation_id:
        output_or_exit(
            get_service(ctx).write(
                "post_edit",
                operation_id,
                dict(identifier=post_id, content=content, title=title, categories=category),
            ),
            fmt,
        )
        return
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
    return extract_post_id(post_id)


@app.command()
def reply(
    ctx: typer.Context,
    post_id: str = typer.Argument(..., help="Post ID or URL to reply to"),
    content: str = typer.Argument(..., help="Reply content (use '-' for stdin)"),
    operation_id: str | None = typer.Option(None, "--operation-id", help="Stable write receipt ID"),
):
    """Reply to a post via the native micro.blog API."""
    from mb.formatters import output

    fmt = get_format(ctx)
    client = get_client(ctx)
    content = _read_content(content)

    if not content:
        output({"ok": False, "error": "Content is empty", "code": 400}, fmt)
        raise SystemExit(1)

    numeric_id = _extract_post_id(post_id)
    if numeric_id is None:
        output(
            {"ok": False, "error": f"Cannot extract numeric post ID from: {post_id}", "code": 400},
            fmt,
        )
        raise SystemExit(1)

    from mb.services import reply_post

    result = (
        get_service(ctx).write(
            "post_reply", operation_id, dict(post_id=str(numeric_id), content=content)
        )
        if operation_id
        else reply_post(client, numeric_id, content)
    )
    output_or_exit(result, fmt)


@app.command()
def delete(
    ctx: typer.Context,
    post_id: str = typer.Argument(..., help="Post ID or URL to delete"),
    operation_id: str | None = typer.Option(None, "--operation-id", help="Stable write receipt ID"),
):
    """Delete a post."""

    fmt = get_format(ctx)
    client = get_client(ctx)

    if operation_id:
        output_or_exit(
            get_service(ctx).write("post_delete", operation_id, dict(identifier=post_id)), fmt
        )
        return
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


@app.command("publish")
def publish(
    ctx: typer.Context,
    identifier: str = typer.Argument(..., help="Existing draft URL or numeric ID"),
    source_hash: str = typer.Option(..., "--source-hash", help="Reviewed post get source hash"),
    operation_id: str = typer.Option(..., "--operation-id", help="Stable publish receipt ID"),
):
    """Publish an unchanged, reviewed draft at its existing URL."""
    output_or_exit(
        get_service(ctx).write(
            "post_publish", operation_id, dict(identifier=identifier, source_hash=source_hash)
        ),
        get_format(ctx),
    )


@app.command("replies")
def replies(ctx: typer.Context, count: int = typer.Option(10, "--count", "-n", min=1, max=50)):
    """Read recent replies made by the authenticated account."""
    output_or_exit(get_service(ctx).replies(count=count), get_format(ctx))
