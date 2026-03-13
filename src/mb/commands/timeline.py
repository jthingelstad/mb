"""Reading/discovery commands."""

import typer

from mb.commands import get_client, get_format, get_profile, output_or_exit, add_content_text
from mb.discover_collections import get_discover_collection, list_discover_collections

app = typer.Typer(no_args_is_help=False, invoke_without_command=True, rich_markup_mode=None)


@app.callback(invoke_without_command=True)
def timeline_default(
    ctx: typer.Context,
    count: int = typer.Option(20, "--count", "-n", help="Number of posts"),
    since: int = typer.Option(None, "--since", help="Return posts after this ID"),
    before: int = typer.Option(None, "--before", help="Return posts before this ID"),
):
    """Following timeline (default 20 posts)."""
    if ctx.invoked_subcommand is not None:
        return

    fmt = get_format(ctx)
    client = get_client(ctx)
    result = client.get_timeline(count=count, since_id=since, before_id=before)
    if result["ok"]:
        add_content_text(result["data"])
    output_or_exit(result, fmt)


@app.command()
def mentions(ctx: typer.Context):
    """Show mentions."""
    fmt = get_format(ctx)
    client = get_client(ctx)
    result = client.get_mentions()
    if result["ok"]:
        add_content_text(result["data"])
    output_or_exit(result, fmt)


@app.command()
def photos(ctx: typer.Context):
    """Show photo timeline."""
    fmt = get_format(ctx)
    client = get_client(ctx)
    result = client.get_photos()
    if result["ok"]:
        add_content_text(result["data"])
    output_or_exit(result, fmt)


@app.command()
def discover(
    ctx: typer.Context,
    collection: str = typer.Option(None, "--collection", "-c", help="Collection name (e.g. books, music)"),
    list_collections: bool = typer.Option(False, "--list", help="List curated discover collections"),
):
    """Show discover timeline."""
    fmt = get_format(ctx)
    if list_collections:
        output_or_exit({"ok": True, "data": {"kind": "discover_collections", "collections": list_discover_collections()}}, fmt)
        return
    if collection and not get_discover_collection(collection):
        from mb.formatters import output
        output({"ok": False, "error": f"Unknown discover collection: {collection}. Use --list to see curated options.", "code": 400}, fmt)
        raise SystemExit(1)
    client = get_client(ctx)
    result = client.get_discover(collection=collection)
    if result["ok"]:
        add_content_text(result["data"])
    output_or_exit(result, fmt)


@app.command()
def check(
    ctx: typer.Context,
    since: int = typer.Option(..., "--since", help="Post ID to check since"),
):
    """Check for new posts since an ID. Returns new_count and poll_interval."""
    fmt = get_format(ctx)
    client = get_client(ctx)
    result = client.check_timeline(since_id=since)
    output_or_exit(result, fmt)


@app.command()
def checkpoint(
    ctx: typer.Context,
    post_id: int = typer.Argument(None, help="Post ID to save as checkpoint"),
):
    """Read or save a timeline checkpoint ID.

    With no argument, prints the saved checkpoint. With an ID, saves it.
    """
    from mb import config
    from mb.formatters import output

    fmt = get_format(ctx)
    profile = get_profile(ctx)

    if post_id is None:
        saved = config.get_checkpoint(profile=profile)
        if saved is None:
            output({"ok": False, "error": "No checkpoint saved", "code": 404}, fmt)
            raise SystemExit(1)
        output({"ok": True, "data": {"checkpoint": saved}}, fmt)
    else:
        config.save_checkpoint(post_id, profile=profile)
        output({"ok": True, "data": {"checkpoint": post_id}}, fmt)
