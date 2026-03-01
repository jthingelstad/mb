"""Reading/discovery commands."""

import typer

app = typer.Typer(no_args_is_help=False, invoke_without_command=True)


def _get_client():
    from mb.cli import get_client
    return get_client()


def _get_format(ctx: typer.Context) -> str:
    from mb.cli import get_format
    return get_format(ctx)


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
    from mb.formatters import output

    fmt = _get_format(ctx)
    client = _get_client()
    result = client.get_timeline(count=count, since_id=since, before_id=before)
    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)


@app.command()
def mentions(ctx: typer.Context):
    """Show mentions."""
    from mb.formatters import output

    fmt = _get_format(ctx)
    client = _get_client()
    result = client.get_mentions()
    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)


@app.command()
def photos(ctx: typer.Context):
    """Show photo timeline."""
    from mb.formatters import output

    fmt = _get_format(ctx)
    client = _get_client()
    result = client.get_photos()
    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)


@app.command()
def discover(
    ctx: typer.Context,
    collection: str = typer.Option(None, "--collection", "-c", help="Collection name (e.g. books, music)"),
):
    """Show discover timeline."""
    from mb.formatters import output

    fmt = _get_format(ctx)
    client = _get_client()
    result = client.get_discover(collection=collection)
    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)


@app.command()
def check(
    ctx: typer.Context,
    since: int = typer.Option(..., "--since", help="Post ID to check since"),
):
    """Check for new posts since an ID. Returns new_count and poll_interval."""
    from mb.formatters import output

    fmt = _get_format(ctx)
    client = _get_client()
    result = client.check_timeline(since_id=since)
    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)
