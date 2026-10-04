"""Shared two-stage, receipt-aware local image workflow."""

import typer

from mb.commands import get_format, get_service, output_or_exit

app = typer.Typer(no_args_is_help=True, rich_markup_mode=None)


@app.command("preview")
def preview(
    ctx: typer.Context, file: str = typer.Argument(...), alt: str = typer.Option(..., "--alt")
):
    """Review a relative image under --media-root without uploading."""
    output_or_exit(get_service(ctx).media_preview(file, alt), get_format(ctx))


@app.command("upload")
def upload(
    ctx: typer.Context,
    file: str = typer.Argument(...),
    alt: str = typer.Option(..., "--alt"),
    sha256: str = typer.Option(..., "--sha256"),
    operation_id: str = typer.Option(..., "--operation-id"),
):
    """Upload exactly the reviewed image with a durable outcome receipt."""
    output_or_exit(
        get_service(ctx).write(
            "media_upload", operation_id, dict(file=file, alt=alt, sha256=sha256)
        ),
        get_format(ctx),
    )
