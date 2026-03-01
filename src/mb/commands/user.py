"""Social graph commands."""

import typer

from mb.commands import get_client, get_format, output_or_exit

app = typer.Typer(no_args_is_help=True)


@app.command()
def show(ctx: typer.Context, username: str = typer.Argument(..., help="Username to look up")):
    """Show user profile."""
    output_or_exit(get_client(ctx).get_user(username), get_format(ctx))


@app.command()
def following(ctx: typer.Context, username: str = typer.Argument(..., help="Username to check following list")):
    """List who a user is following."""
    output_or_exit(get_client(ctx).get_following(username), get_format(ctx))


@app.command("discover")
def discover_user(ctx: typer.Context, username: str = typer.Argument(..., help="Username to discover")):
    """Discover a user's posts."""
    output_or_exit(get_client(ctx).get_discover_user(username), get_format(ctx))


@app.command()
def follow(ctx: typer.Context, username: str = typer.Argument(..., help="Username to follow")):
    """Follow a user."""
    output_or_exit(get_client(ctx).follow(username), get_format(ctx))


@app.command()
def unfollow(ctx: typer.Context, username: str = typer.Argument(..., help="Username to unfollow")):
    """Unfollow a user."""
    output_or_exit(get_client(ctx).unfollow(username), get_format(ctx))


@app.command("is-following")
def is_following(ctx: typer.Context, username: str = typer.Argument(..., help="Username to check")):
    """Check if you are following a user."""
    output_or_exit(get_client(ctx).is_following(username), get_format(ctx))


@app.command()
def mute(ctx: typer.Context, value: str = typer.Argument(..., help="Username or keyword to mute")):
    """Mute a user or keyword."""
    output_or_exit(get_client(ctx).mute(value), get_format(ctx))


@app.command()
def muting(ctx: typer.Context):
    """List muted users/keywords."""
    output_or_exit(get_client(ctx).get_muting(), get_format(ctx))


@app.command()
def unmute(ctx: typer.Context, mute_id: int = typer.Argument(..., help="Mute ID to remove")):
    """Remove a mute."""
    output_or_exit(get_client(ctx).unmute(mute_id), get_format(ctx))


@app.command()
def block(ctx: typer.Context, username: str = typer.Argument(..., help="Username to block")):
    """Block a user."""
    output_or_exit(get_client(ctx).block(username), get_format(ctx))


@app.command()
def blocking(ctx: typer.Context):
    """List blocked users."""
    output_or_exit(get_client(ctx).get_blocking(), get_format(ctx))


@app.command()
def unblock(ctx: typer.Context, block_id: int = typer.Argument(..., help="Block ID to remove")):
    """Remove a block."""
    output_or_exit(get_client(ctx).unblock(block_id), get_format(ctx))
