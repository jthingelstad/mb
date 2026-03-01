"""Reading/discovery commands."""

import typer

from mb.commands import get_client, get_format, output_or_exit, add_content_text

app = typer.Typer(no_args_is_help=False, invoke_without_command=True)


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
):
    """Show discover timeline."""
    fmt = get_format(ctx)
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
