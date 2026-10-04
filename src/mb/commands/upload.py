"""Compatibility spelling for the reviewed, receipt-aware media workflow."""

from pathlib import Path

import typer

from mb.commands import get_format, get_service, output_or_exit


def run(
    ctx: typer.Context,
    source: str,
    alt: str | None = None,
    sha256: str | None = None,
    operation_id: str | None = None,
):
    """Upload only a reviewed relative image; legacy implicit fetching is removed."""
    if source.startswith(("http://", "https://")) or Path(source).is_absolute():
        output_or_exit(
            {
                "ok": False,
                "error": "Legacy path/URL upload was removed in 2.0. Save the image under an "
                "explicit --media-root, run media preview with its relative path and --alt, "
                "then media upload with the reviewed --sha256 and stable --operation-id. "
                "MB does not fetch remote images.",
                "code": 400,
                "outcome": "not_applied",
            },
            get_format(ctx),
        )
        return
    output_or_exit(
        get_service(ctx).write(
            "media_upload",
            operation_id or "",
            dict(file=source, alt=alt or "", sha256=sha256 or ""),
        ),
        get_format(ctx),
    )
