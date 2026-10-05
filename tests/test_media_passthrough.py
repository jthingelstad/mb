"""Images upload exactly as stored; the CLI reads any path, MCP stays in --media-root."""

import hashlib
import json

import pytest

from mb.media import ImageInputError, load_image, load_local_image, resolve_media_root
from tests.test_cli_write_safety import Harness

PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic png"
JPEG = b"\xff\xd8\xff\xe1" + b"Exif\x00\x00 synthetic camera metadata stays"
GIF = b"GIF89a" + b"synthetic gif"
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 synthetic"


@pytest.mark.parametrize(
    "name,raw,mime_type",
    [
        ("photo.jpg", JPEG, "image/jpeg"),
        ("photo.JPEG", JPEG, "image/jpeg"),
        ("image.png", PNG, "image/png"),
        ("anim.gif", GIF, "image/gif"),
        ("old.gif", b"GIF87a rest", "image/gif"),
        ("pic.webp", WEBP, "image/webp"),
    ],
)
def test_supported_images_pass_through_unchanged(tmp_path, name, raw, mime_type):
    (tmp_path / name).write_bytes(raw)
    for metadata, content in (
        load_local_image(str(tmp_path / name)),
        load_image(tmp_path, name),
    ):
        assert content == raw
        assert metadata["sha256"] == hashlib.sha256(raw).hexdigest()
        assert metadata["byte_count"] == len(raw) and metadata["mime_type"] == mime_type
        assert metadata["filename"] == name
        assert set(metadata) == {"file", "filename", "sha256", "byte_count", "mime_type"}


@pytest.mark.parametrize(
    "name,raw,message",
    [
        ("photo.jpg", PNG, "photo.jpg contains PNG data, but its extension says JPEG"),
        ("image.png", JPEG, "contains JPEG data, but its extension says PNG"),
        ("pic.webp", b"RIFF\x00\x00\x00\x00WAVE", "contains no recognized image data"),
        ("anim.gif", b"GIF90a", "contains no recognized image data"),
        ("photo.heic", JPEG, "Supported images are JPEG"),
        ("notes.txt", b"text", "Supported images are JPEG"),
        ("empty.png", b"", "non-empty regular file"),
    ],
)
def test_extension_must_match_signature(tmp_path, name, raw, message):
    (tmp_path / name).write_bytes(raw)
    with pytest.raises(ImageInputError, match=message):
        load_local_image(str(tmp_path / name))


def test_local_loader_refusals(tmp_path):
    (tmp_path / "dir.png").mkdir()
    for file, message in [
        (str(tmp_path / "missing.png"), "not found"),
        (str(tmp_path / "dir.png"), "regular file"),
        ("bad\0name.png", "NUL byte"),
        ("https://example.com/a.png", "does not fetch remote images"),
    ]:
        with pytest.raises(ImageInputError, match=message):
            load_local_image(file)


def test_oversized_image_is_refused(tmp_path):
    from mb import media

    (tmp_path / "big.png").write_bytes(PNG + b"\0" * 64)
    original = media.MAX_BYTES
    media.MAX_BYTES = 32
    try:
        with pytest.raises(ImageInputError, match="20 MiB"):
            load_local_image(str(tmp_path / "big.png"))
    finally:
        media.MAX_BYTES = original


# ── media root (MCP and explicit CLI root) ─────────────────


def test_symlinked_root_is_allowed_but_child_symlinks_are_not(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "image.png").write_bytes(PNG)
    outside = tmp_path / "outside.png"
    outside.write_bytes(PNG)
    (real / "escape.png").symlink_to(outside)
    (real / "sub").symlink_to(tmp_path, target_is_directory=True)
    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(real, target_is_directory=True)
    root = resolve_media_root(str(linked_root))
    assert root == real.resolve()
    assert load_image(root, "image.png")[1] == PNG
    assert load_image(linked_root, "image.png")[1] == PNG
    with pytest.raises(ImageInputError, match="crosses a symlink"):
        load_image(root, "escape.png")
    with pytest.raises(ImageInputError, match="crosses a symlink"):
        load_image(root, "sub/outside.png")
    for file in ["../outside.png", str(outside), "sub/../image.png"]:
        with pytest.raises(ImageInputError, match="relative image path"):
            load_image(root, file)
    with pytest.raises(ImageInputError, match="NUL byte"):
        load_image(root, "image\0.png")
    with pytest.raises(ImageInputError, match="not found under the media root"):
        load_image(root, "absent.png")


def test_missing_media_root_has_its_own_message(tmp_path):
    with pytest.raises(ImageInputError, match="Media root is unavailable or not a directory"):
        load_image(tmp_path / "absent", "image.png")


@pytest.mark.parametrize("value,message", [("relative/dir", "absolute"), ("/a\0b", "NUL")])
def test_media_root_must_be_absolute(value, message):
    with pytest.raises(ImageInputError, match=message):
        resolve_media_root(value)


def test_cli_rejects_relative_media_root_before_any_work():
    from typer.testing import CliRunner

    from mb.cli import app

    result = CliRunner().invoke(
        app, ["-f", "json", "--media-root", "reviewed", "media", "preview", "a.png", "--alt", "A"]
    )
    assert result.exit_code == 2
    data = json.loads(result.stdout)
    assert data["code"] == 400 and "absolute" in data["error"]


# ── CLI upload of any local path ───────────────────────────


@pytest.mark.parametrize("verb", [["media", "upload"], ["upload"]])
def test_cli_uploads_any_local_path_without_media_root_or_hash(tmp_path, verb):
    elsewhere = tmp_path / "Pictures"
    elsewhere.mkdir()
    (elsewhere / "photo.jpg").write_bytes(JPEG)
    harness = Harness(tmp_path)
    harness.media_root = None
    result, data = harness.invoke([*verb, str(elsewhere / "photo.jpg"), "--alt", "A photo"])
    assert result.exit_code == 0, data
    assert data["outcome"] == "applied" and len(harness.writes) == 1
    upload = harness.writes[0]
    assert JPEG in upload.content and b'filename="photo.jpg"' in upload.content
    assert b"image/jpeg" in upload.content
    assert data["data"]["sha256"] == hashlib.sha256(JPEG).hexdigest()


def test_cli_preview_any_path_then_upload_with_hash_guard(tmp_path):
    image = tmp_path / "photo.gif"
    image.write_bytes(GIF)
    harness = Harness(tmp_path)
    harness.media_root = None
    _, preview = harness.invoke(["media", "preview", str(image), "--alt", "Animated"])
    assert preview["ok"] and preview["data"]["mime_type"] == "image/gif"
    assert preview["data"]["destination"] == "https://agent.micro.blog/"
    assert not harness.writes
    image.write_bytes(GIF + b"edited")
    _, changed = harness.invoke(
        ["media", "upload", str(image), "--alt", "Animated", "--sha256", preview["data"]["sha256"]]
    )
    assert changed["code"] == 409 and changed["outcome"] == "not_applied"
    assert not harness.writes


def test_cli_upload_refuses_mismatched_file_before_claim(tmp_path):
    (tmp_path / "fake.png").write_bytes(JPEG)
    harness = Harness(tmp_path)
    harness.media_root = None
    _, data = harness.invoke(["media", "upload", str(tmp_path / "fake.png"), "--alt", "Fake"])
    assert data["outcome"] == "not_applied" and "extension says PNG" in data["error"]
    assert not harness.writes and not (tmp_path / "receipts.sqlite").exists()


# ── MCP stays contained ────────────────────────────────────


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_mcp_media_tools_stay_inside_media_root(tmp_path):
    types = pytest.importorskip("mcp.types")
    from mb.mcp_server import Adapter
    from tests.test_bounded_capabilities import BLOG, transport_service

    root = tmp_path / "root"
    root.mkdir()
    (root / "image.png").write_bytes(PNG)
    outside = tmp_path / "outside.png"
    outside.write_bytes(PNG)
    service = transport_service(tmp_path, lambda request: None, media_root=root)
    adapter = Adapter(lambda: service)

    async def call(name, arguments):
        params = types.CallToolRequestParams(name=name, arguments=arguments)
        return (await adapter.call_tool(None, params)).structured_content

    preview = await call("media_preview", {"file": "image.png", "alt": "Blue"})
    assert preview["ok"] and preview["data"]["destination"] == BLOG
    assert {"file", "filename", "mime_type", "byte_count", "sha256", "alt"} <= set(preview["data"])
    refused = await call("media_preview", {"file": str(outside), "alt": "Blue"})
    assert refused["ok"] is False and "relative image path" in refused["error"]
    unhashed = await call(
        "media_upload", {"file": "image.png", "alt": "Blue", "operation_id": "no-hash"}
    )
    assert unhashed["code"] == 400 and "sha256" in unhashed["error"]
    service.media_root = None
    disabled = await call("media_preview", {"file": "image.png", "alt": "Blue"})
    assert "--media-root" in disabled["error"]
