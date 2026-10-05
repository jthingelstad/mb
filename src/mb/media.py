"""Local image access. Uploads send the user's bytes unchanged; MCP reads only under --media-root."""

import errno
import hashlib
import os
import stat
from pathlib import Path

MAX_BYTES = 20 * 1024 * 1024
FORMATS = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
_NAMES = {"image/jpeg": "JPEG", "image/png": "PNG", "image/gif": "GIF", "image/webp": "WebP"}
SUPPORTED = "Supported images are JPEG (.jpg, .jpeg), PNG, GIF and WebP files"


class ImageInputError(ValueError):
    pass


def resolve_media_root(value: str) -> Path:
    """Resolve an explicit media root once, so the root itself may be a symlink."""
    if "\0" in value:
        raise ImageInputError("--media-root contains a NUL byte")
    if not os.path.isabs(value):
        raise ImageInputError("--media-root must be an absolute directory path")
    return Path(os.path.realpath(value))


def sniff(raw: bytes) -> str | None:
    """Return the image MIME type that the leading bytes identify, if any."""
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw[:6] in {b"GIF87a", b"GIF89a"}:
        return "image/gif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


def _mime_type(file: str) -> str:
    if "\0" in file:
        raise ImageInputError("Image path contains a NUL byte")
    if file.lower().startswith(("http://", "https://")):
        raise ImageInputError("MB does not fetch remote images; save the image locally first")
    mime_type = FORMATS.get(Path(file).suffix.lower())
    if mime_type is None:
        raise ImageInputError(SUPPORTED)
    return mime_type


def _read_regular(fd: int) -> bytes:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_BYTES:
        os.close(fd)
        raise ImageInputError("Image must be a non-empty regular file of at most 20 MiB")
    with os.fdopen(fd, "rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ImageInputError("Image exceeds 20 MiB")
    return raw


def _describe(file: str, mime_type: str, raw: bytes) -> tuple[dict, bytes]:
    found = sniff(raw)
    if found != mime_type:
        actual = f"{_NAMES[found]} data" if found else "no recognized image data"
        raise ImageInputError(
            f"{Path(file).name} contains {actual}, but its extension says "
            f"{_NAMES[mime_type]}; the extension must match the file contents"
        )
    return {
        "file": file,
        "filename": Path(file).name,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "byte_count": len(raw),
        "mime_type": mime_type,
    }, raw


def load_local_image(file: str) -> tuple[dict, bytes]:
    """Read any local image path the CLI user named, exactly as stored."""
    mime_type = _mime_type(file)
    try:
        fd = os.open(file, os.O_RDONLY | os.O_NONBLOCK)
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            raise ImageInputError("Image file not found") from None
        raise ImageInputError("Image file is not readable") from None
    return _describe(file, mime_type, _read_regular(fd))


def load_image(root: Path | None, file: str) -> tuple[dict, bytes]:
    """Open a relative regular file under the media root without following child symlinks."""
    path = Path(file)
    if root is None:
        raise ImageInputError(
            "Local images are disabled; start with an explicit --media-root directory"
        )
    if "\0" in file:
        raise ImageInputError("Image path contains a NUL byte")
    if path.is_absolute() or not path.parts or any(p in {"..", "."} for p in path.parts):
        raise ImageInputError("Use a relative image path within the allowed media directory")
    mime_type = _mime_type(file)
    try:
        # The root was resolved once at startup and may itself be a symlink.
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        raise ImageInputError("Media root is unavailable or not a directory") from None
    try:
        for part in path.parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        image_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            raise ImageInputError("Image not found under the media root") from None
        if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise ImageInputError(
                "Image path crosses a symlink or non-directory inside the media root"
            ) from None
        raise ImageInputError("Image under the media root is not readable") from None
    finally:
        os.close(fd)
    return _describe(file, mime_type, _read_regular(image_fd))
