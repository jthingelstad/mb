"""Social graph commands."""

import typer

app = typer.Typer(no_args_is_help=True)


def _get_client():
    from mb.cli import get_client
    return get_client()


def _get_format(ctx: typer.Context) -> str:
    from mb.cli import get_format
    return get_format(ctx)


@app.command()
def show(
    ctx: typer.Context,
    username: str = typer.Argument(..., help="Username to look up"),
):
    """Show user profile."""
    from mb.formatters import output

    fmt = _get_format(ctx)
    client = _get_client()
    result = client.get_user(username)
    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)


@app.command()
def following(
    ctx: typer.Context,
    username: str = typer.Argument(..., help="Username to check following list"),
):
    """List who a user is following."""
    from mb.formatters import output

    fmt = _get_format(ctx)
    client = _get_client()
    result = client.get_following(username)
    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)


@app.command("discover")
def discover_user(
    ctx: typer.Context,
    username: str = typer.Argument(..., help="Username to discover"),
):
    """Discover a user's posts."""
    from mb.formatters import output

    fmt = _get_format(ctx)
    client = _get_client()
    result = client.get_discover_user(username)
    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)


@app.command()
def follow(
    ctx: typer.Context,
    username: str = typer.Argument(..., help="Username to follow"),
):
    """Follow a user."""
    from mb.formatters import output

    fmt = _get_format(ctx)
    client = _get_client()
    result = client.follow(username)
    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)


@app.command()
def unfollow(
    ctx: typer.Context,
    username: str = typer.Argument(..., help="Username to unfollow"),
):
    """Unfollow a user."""
    from mb.formatters import output

    fmt = _get_format(ctx)
    client = _get_client()
    result = client.unfollow(username)
    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)


@app.command("is-following")
def is_following(
    ctx: typer.Context,
    username: str = typer.Argument(..., help="Username to check"),
):
    """Check if you are following a user."""
    from mb.formatters import output

    fmt = _get_format(ctx)
    client = _get_client()
    result = client.is_following(username)
    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)


@app.command()
def mute(
    ctx: typer.Context,
    value: str = typer.Argument(..., help="Username or keyword to mute"),
):
    """Mute a user or keyword."""
    from mb.formatters import output

    fmt = _get_format(ctx)
    client = _get_client()
    result = client.mute(value)
    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)


@app.command()
def muting(ctx: typer.Context):
    """List muted users/keywords."""
    from mb.formatters import output

    fmt = _get_format(ctx)
    client = _get_client()
    result = client.get_muting()
    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)


@app.command()
def unmute(
    ctx: typer.Context,
    mute_id: int = typer.Argument(..., help="Mute ID to remove"),
):
    """Remove a mute."""
    from mb.formatters import output

    fmt = _get_format(ctx)
    client = _get_client()
    result = client.unmute(mute_id)
    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)


@app.command()
def block(
    ctx: typer.Context,
    username: str = typer.Argument(..., help="Username to block"),
):
    """Block a user."""
    from mb.formatters import output

    fmt = _get_format(ctx)
    client = _get_client()
    result = client.block(username)
    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)


@app.command()
def blocking(ctx: typer.Context):
    """List blocked users."""
    from mb.formatters import output

    fmt = _get_format(ctx)
    client = _get_client()
    result = client.get_blocking()
    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)


@app.command()
def unblock(
    ctx: typer.Context,
    block_id: int = typer.Argument(..., help="Block ID to remove"),
):
    """Remove a block."""
    from mb.formatters import output

    fmt = _get_format(ctx)
    client = _get_client()
    result = client.unblock(block_id)
    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)
