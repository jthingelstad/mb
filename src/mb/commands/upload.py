"""Compatibility spelling for the receipt-aware media upload."""

import typer

from mb.commands import cli_write, get_format, get_service, output_or_exit


def run(
    ctx: typer.Context,
    source: str,
    alt: str | None = None,
    sha256: str | None = None,
    operation_id: str | None = None,
):
    """Upload one local image unchanged; remote URLs are never fetched."""
    if source.startswith(("http://", "https://")):
        output_or_exit(
            {
                "ok": False,
                "error": "MB does not fetch remote images. Save the image locally, then run "
                "mb media upload PATH --alt TEXT, or post with --photo-url for a hosted image.",
                "code": 400,
                "outcome": "not_applied",
            },
            get_format(ctx),
        )
        return
    output_or_exit(
        cli_write(
            ctx,
            get_service(ctx),
            "media_upload",
            operation_id,
            dict(file=source, alt=alt or "", sha256=sha256 or ""),
        ),
        get_format(ctx),
    )
