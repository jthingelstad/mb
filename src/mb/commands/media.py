"""Receipt-aware local image workflow; images are uploaded exactly as stored."""

import typer

from mb.commands import cli_write, get_format, get_service, output_or_exit

app = typer.Typer(no_args_is_help=True, rich_markup_mode=None)


@app.command("preview")
def preview(
    ctx: typer.Context,
    file: str = typer.Argument(..., help="Local image path (relative to --media-root if set)"),
    alt: str = typer.Option(..., "--alt"),
):
    """Show what would be uploaded (type, size, sha256, destination) without uploading."""
    output_or_exit(get_service(ctx).media_preview(file, alt), get_format(ctx))


@app.command("upload")
def upload(
    ctx: typer.Context,
    file: str = typer.Argument(..., help="Local image path (relative to --media-root if set)"),
    alt: str = typer.Option(..., "--alt"),
    sha256: str | None = typer.Option(
        None, "--sha256", help="Optional hash from media preview; refuses a changed file"
    ),
    operation_id: str | None = typer.Option(
        None,
        "--operation-id",
        help="Optional stable retry ID; omitted IDs start a new saved operation",
    ),
):
    """Upload the image bytes unchanged with a durable outcome receipt."""
    output_or_exit(
        cli_write(
            ctx,
            get_service(ctx),
            "media_upload",
            operation_id,
            dict(file=file, alt=alt, sha256=sha256 or ""),
        ),
        get_format(ctx),
    )
