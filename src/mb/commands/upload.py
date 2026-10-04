"""Media upload commands."""

import mimetypes
from pathlib import Path
from urllib.parse import urlparse

import httpx
import typer

from mb.commands import get_client, get_format, get_service, output_or_exit


def _download_image(url: str) -> tuple[str, bytes, str | None] | dict:
    """Download an image from a remote URL."""
    try:
        with httpx.Client(follow_redirects=True, timeout=30.0) as client:
            resp = client.get(url)
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"Unable to fetch image URL: {exc}", "code": 400}

    if resp.status_code >= 400:
        return {
            "ok": False,
            "error": f"Image URL returned HTTP {resp.status_code}",
            "code": resp.status_code,
        }

    content_type = resp.headers.get("Content-Type", "").split(";")[0].strip() or None
    if content_type and not content_type.startswith("image/"):
        return {"ok": False, "error": f"Remote URL is not an image: {content_type}", "code": 400}

    parsed = urlparse(url)
    filename = Path(parsed.path).name or "upload"
    if "." not in filename:
        extension = mimetypes.guess_extension(content_type or "") or ".img"
        filename = f"{filename}{extension}"
    return filename, resp.content, content_type


def run(
    ctx: typer.Context,
    source: str,
    alt: str | None = None,
):
    """Upload a local image file or a remote image URL."""
    client = get_client(ctx)
    fmt = get_format(ctx)
    identity = get_service(ctx, client).identity()
    if not identity["ok"]:
        output_or_exit(identity, fmt)
        return
    client.default_destination = identity["data"]["blog"]

    if source.startswith("http://") or source.startswith("https://"):
        downloaded = _download_image(source)
        if isinstance(downloaded, dict):
            output_or_exit(downloaded, fmt)
            return
        filename, content, content_type = downloaded
        from mb.media import ImageInputError, normalize_image

        try:
            metadata, content = normalize_image(content, filename)
        except ImageInputError as exc:
            output_or_exit({"ok": False, "error": str(exc), "code": 400}, fmt)
            return
        result = client.micropub_upload_bytes(
            metadata["filename"], content, alt=alt, content_type=metadata["mime_type"]
        )
    else:
        result = client.micropub_upload_photo(source, alt=alt)

    if result.get("ok"):
        result["data"]["source"] = source
        result["data"]["kind"] = "upload"
    output_or_exit(result, fmt)
