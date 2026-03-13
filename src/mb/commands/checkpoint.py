"""Named checkpoint management commands."""

import typer

from mb import config
from mb.commands import get_format, get_profile, output_or_exit

app = typer.Typer(no_args_is_help=True, rich_markup_mode=None)


def _checkpoint_payload(name: str, checkpoint: int | None) -> dict:
    """Build a standard checkpoint payload."""
    return {
        "kind": "checkpoint",
        "name": name,
        "checkpoint": checkpoint,
    }


@app.command("list")
def list_checkpoints(ctx: typer.Context):
    """List all saved checkpoints for the active profile."""
    fmt = get_format(ctx)
    profile = get_profile(ctx)
    checkpoints = config.list_named_checkpoints(profile=profile)
    output_or_exit({
        "ok": True,
        "data": {
            "kind": "checkpoints",
            "profile": profile,
            "checkpoints": checkpoints,
        },
    }, fmt)


@app.command("get")
def get_checkpoint(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Checkpoint name: timeline, heartbeat, inbox, catchup, or another saved name"),
):
    """Read one saved checkpoint by name."""
    fmt = get_format(ctx)
    profile = get_profile(ctx)
    checkpoint = config.get_named_checkpoint(name, profile=profile)
    if checkpoint is None:
        output_or_exit({"ok": False, "error": f"No checkpoint saved for {name}", "code": 404}, fmt)
        return
    output_or_exit({"ok": True, "data": _checkpoint_payload(name, checkpoint)}, fmt)


@app.command("set")
def set_checkpoint(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Checkpoint name to save"),
    checkpoint_id: int = typer.Argument(..., help="Post ID to save"),
):
    """Save one named checkpoint."""
    fmt = get_format(ctx)
    profile = get_profile(ctx)
    config.save_named_checkpoint(name, checkpoint_id, profile=profile)
    output_or_exit({"ok": True, "data": _checkpoint_payload(name, checkpoint_id)}, fmt)


@app.command("clear")
def clear_checkpoint(
    ctx: typer.Context,
    name: str = typer.Argument(None, help="Checkpoint name to clear"),
    all_checkpoints: bool = typer.Option(False, "--all", help="Clear every saved checkpoint for the active profile"),
):
    """Clear one checkpoint or all checkpoints for the active profile."""
    fmt = get_format(ctx)
    profile = get_profile(ctx)

    if all_checkpoints:
        removed = config.clear_all_named_checkpoints(profile=profile)
        output_or_exit({
            "ok": True,
            "data": {
                "kind": "checkpoints",
                "profile": profile,
                "cleared": removed,
                "checkpoints": config.list_named_checkpoints(profile=profile),
            },
        }, fmt)
        return

    if not name:
        output_or_exit({"ok": False, "error": "Provide a checkpoint name or pass --all", "code": 400}, fmt)
        return

    cleared = config.clear_named_checkpoint(name, profile=profile)
    if not cleared:
        output_or_exit({"ok": False, "error": f"No checkpoint saved for {name}", "code": 404}, fmt)
        return
    output_or_exit({
        "ok": True,
        "data": {
            **_checkpoint_payload(name, None),
            "cleared": True,
        },
    }, fmt)
