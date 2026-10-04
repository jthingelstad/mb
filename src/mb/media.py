"""Bounded raster-image access. MCP exposes only an explicitly allowed directory."""

import hashlib
import io
import os
import stat
import warnings
from pathlib import Path

from PIL import Image, ImageOps

MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 40_000_000
FORMATS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}


class ImageInputError(ValueError):
    pass


def load_image(root: Path | None, file: str) -> tuple[dict, bytes]:
    """Open relative regular files without following child symlinks, then decode/re-encode."""
    path = Path(file)
    if root is None:
        raise ImageInputError(
            "Local images are disabled; start with an explicit --media-root directory"
        )
    if path.is_absolute() or not path.parts or any(p in {"..", "."} for p in path.parts):
        raise ImageInputError("Use a relative image path within the allowed media directory")
    expected = FORMATS.get(path.suffix.lower())
    if expected is None:
        raise ImageInputError("Supported local images are static JPEG, PNG and WebP")
    fd = None
    try:
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in path.parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        image_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(image_fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_BYTES:
                raise ImageInputError("Image must be a regular file of at most 20 MiB")
            raw = stream.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ImageInputError("Image exceeds 20 MiB")
    except OSError:
        raise ImageInputError(
            "Image is unavailable or crosses a symlink outside the allowed directory"
        ) from None
    finally:
        if fd is not None:
            os.close(fd)
    return normalize_image(raw, file)


def normalize_image(raw: bytes, file: str) -> tuple[dict, bytes]:
    path = Path(file)
    expected = FORMATS.get(path.suffix.lower())
    if expected is None or not 0 < len(raw) <= MAX_BYTES:
        raise ImageInputError(
            "Supported local images are static JPEG, PNG and WebP of at most 20 MiB"
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format != expected or image.width * image.height > MAX_PIXELS:
                    raise ImageInputError(
                        "Image format does not match its extension or exceeds 40 megapixels"
                    )
                if getattr(image, "n_frames", 1) != 1:
                    raise ImageInputError("Animated images are not supported in this candidate")
                image.load()
                oriented = ImageOps.exif_transpose(image)
                # Fresh pixels omit EXIF, comments, text chunks and any appended payload.
                clean = Image.new("RGB" if expected == "JPEG" else "RGBA", oriented.size)
                clean.paste(oriented.convert(clean.mode))
                encoded = io.BytesIO()
                output_format = "JPEG" if expected == "JPEG" else "PNG"
                clean.save(
                    encoded,
                    format=output_format,
                    **({"quality": 95} if output_format == "JPEG" else {}),
                )
                content = encoded.getvalue()
                if len(content) > MAX_BYTES:
                    raise ImageInputError("Normalized image exceeds 20 MiB")
                suffix = ".jpg" if output_format == "JPEG" else ".png"
                return {
                    "file": file,
                    "filename": path.stem + suffix,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "upload_sha256": hashlib.sha256(content).hexdigest(),
                    "byte_count": len(content),
                    "width": clean.width,
                    "height": clean.height,
                    "mime_type": "image/jpeg" if output_format == "JPEG" else "image/png",
                    "metadata_removed": True,
                }, content
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageInputError("Image is invalid, oversized or unsupported") from None
