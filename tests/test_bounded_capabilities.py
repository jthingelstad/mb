"""API contracts and shared bounded workflows; never external writes."""

import json
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx
import pytest
from typer.testing import CliRunner

from mb.api import MicroblogClient
from mb.cli import app
from mb.media import ImageInputError, load_image
from mb.services import MicroblogService, source_hash
from tests.test_mcp_review import make_service

BLOG = "https://agent.micro.blog/"
URL = BLOG + "post.html"


def image_bytes():
    """Synthetic PNG bytes; uploads never decode images, only check the signature."""
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR synthetic"


def transport_service(tmp_path, handler, **options):
    def response(request):
        if request.url.path == "/account/verify":
            return httpx.Response(200, json={"username": "agent"})
        if request.url.path == "/micropub" and request.url.params.get("q") == "config":
            return httpx.Response(
                200,
                json={
                    "destination": [{"uid": BLOG}],
                    "media-endpoint": "https://micro.blog/micropub/media",
                },
            )
        return handler(request)

    client = MicroblogClient("synthetic")
    client._client.close()
    client._client = httpx.Client(
        base_url="https://micro.blog",
        transport=httpx.MockTransport(response),
        headers={"Authorization": "Bearer synthetic"},
    )
    return MicroblogService(client, "default", BLOG, "test", tmp_path / "state.sqlite", **options)


def test_photo_and_moderation_contracts(tmp_path):
    requests = []

    def response(request):
        requests.append(request)
        return (
            httpx.Response(201, headers={"Location": URL})
            if request.url.path == "/micropub"
            else httpx.Response(200, json={})
        )

    service = transport_service(tmp_path, response)
    assert service.write(
        "post_create",
        "photo-post",
        dict(content="Photo", photo_url=BLOG + "uploads/image.png", photo_alt="Blue square"),
    )["ok"]
    form = parse_qs(requests[0].content.decode())
    assert form["mp-photo-alt"] == ["Blue square"]
    assert form["mp-destination"] == [BLOG]
    service.client.mute("spoiler", keyword=True)
    service.client.unmute(123)
    service.client.unblock(456)
    assert parse_qs(requests[1].content.decode()) == {"keyword": ["spoiler"]}
    assert [(r.method, r.url.path) for r in requests[2:]] == [
        ("DELETE", "/users/muting/123"),
        ("DELETE", "/users/blocking/456"),
    ]


def test_server_search_destination_and_honest_coverage(tmp_path):
    requests = []

    def response(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "items": [
                    {"properties": {"url": [URL], "content": ["MATCH"], "category": ["photos"]}}
                ]
                * 3
            },
        )

    service = transport_service(tmp_path, response)
    result = service.blog_search("MATCH", count=1, category="photos")
    assert requests[0].url.params == httpx.QueryParams(
        {"q": "source", "mp-destination": BLOG, "filter": "MATCH"}
    )
    assert result["data"]["truncated"] and not result["data"]["coverage_complete"]
    assert len(result["data"]["items"]) == 1
    assert result["data"]["scope"] == "selected-blog"
    assert not service.state.path.exists()
    assert not service.blog_search(" ")["ok"]


@pytest.mark.parametrize(
    "method,args,path",
    [
        ("discover", {"count": 1}, "/posts/discover"),
        ("profile_get", {"username": "other", "count": 1}, "/posts/other"),
        ("replies", {"count": 1}, "/posts/replies"),
    ],
)
def test_social_reads_remain_account_scoped(tmp_path, method, args, path):
    requests = []

    def response(request):
        requests.append(request)
        return httpx.Response(200, json={"title": "Profile", "items": [{"id": 2}, {"id": 1}]})

    service = transport_service(tmp_path, response)
    result = getattr(service, method)(**args)
    assert requests[0].url.path == path and requests[0].url.params == httpx.QueryParams(
        {"count": 2}
    )
    assert result["data"]["scope"] == "account" and result["data"]["truncated"]
    assert result["data"]["items"][0]["id"] == "2"
    assert result["data"]["title"] == "Profile"
    assert not service.state.path.exists()


def test_url_conversation_uses_fixed_endpoint_and_honest_missing(tmp_path):
    requests = []

    def response(request):
        requests.append(request)
        return httpx.Response(404)

    service = transport_service(tmp_path, response)
    result = service.conversation("https://external.example/post")
    assert requests[0].url.host == "micro.blog" and requests[0].url.path == "/conversation.js"
    assert dict(requests[0].url.params) == {
        "url": "https://external.example/post",
        "format": "jsonfeed",
    }
    assert result["ok"] and result["data"]["not_found"] and result["data"]["items"] == []
    assert not service.conversation("file:///etc/passwd")["ok"]


def test_draft_publish_preserves_payload_and_retry_after_status_changed(tmp_path):
    source = {
        "type": ["h-entry"],
        "properties": {
            "content": ["Original"],
            "category": ["photos"],
            "photo": [BLOG + "image.png"],
            "post-status": ["draft"],
        },
    }
    requests = []

    def response(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=source)
        payload = json.loads(request.content)
        assert payload == {
            "action": "update",
            "url": URL,
            "replace": {"post-status": ["published"]},
            "mp-destination": BLOG,
        }
        source["properties"]["post-status"] = ["published"]
        return httpx.Response(204)

    service = transport_service(tmp_path, response)
    reviewed = service.post_get(URL)["data"]
    assert reviewed["source_hash"] == source_hash(source)
    args = dict(identifier=URL, source_hash=reviewed["source_hash"])
    assert service.write("post_publish", "publish-draft", args)["data"]["url"] == URL
    assert service.write("post_publish", "publish-draft", args)["outcome"] == "applied"
    assert len([r for r in requests if r.method == "POST"]) == 1
    assert source["properties"]["content"] == ["Original"]


@pytest.mark.parametrize(
    "status,hash_value,code",
    [(["published"], "correct", 409), (["draft"], "0" * 64, 409), (["draft"], "invalid", 400)],
)
def test_publish_refusal_paths_never_write(tmp_path, status, hash_value, code):
    service, client = make_service(tmp_path)
    source = {"properties": {"post-status": status, "content": ["Reviewed"]}}
    client.micropub_get.return_value = {"ok": True, "data": source}
    result = service.write(
        "post_publish",
        "publish",
        dict(
            identifier=URL,
            source_hash=source_hash(source) if hash_value == "correct" else hash_value,
        ),
    )
    assert result["code"] == code
    client.micropub_publish.assert_not_called()
    assert not service.state.path.exists()


def test_image_preview_upload_then_post_and_retry_without_file(tmp_path):
    file = tmp_path / "image.png"
    raw = image_bytes() + b"\x00EXIF-like trailing bytes stay"
    file.write_bytes(raw)
    requests = []

    def response(request):
        requests.append(request)
        if request.url.path == "/micropub/media":
            # The user's bytes are sent unchanged: no re-encoding or metadata stripping.
            assert raw in request.content and b'filename="image.png"' in request.content
            assert b"mp-destination" in request.content and BLOG.encode() in request.content
            assert b"image/png" in request.content
            return httpx.Response(202, headers={"Location": BLOG + "uploads/image.png"})
        return httpx.Response(201, headers={"Location": URL})

    service = transport_service(tmp_path, response, media_root=tmp_path)
    preview = service.media_preview("image.png", "Blue rectangle")["data"]
    assert preview["byte_count"] == len(raw) and preview["filename"] == "image.png"
    assert preview["mime_type"] == "image/png" and preview["destination"] == BLOG
    assert "width" not in preview and "upload_sha256" not in preview
    assert requests == [] and not service.state.path.exists()
    args = dict(file="image.png", alt="Blue rectangle", sha256=preview["sha256"])
    uploaded = service.write("media_upload", "image-upload", args)
    assert uploaded["outcome"] == "applied" and uploaded["data"]["processing_pending"]
    file.unlink()
    retry = service.write("media_upload", "image-upload", args)
    assert retry["data"]["url"] == uploaded["data"]["url"] and retry["data"]["processing_pending"]
    post = dict(content="Photo", photo_url=retry["data"]["url"], photo_alt=args["alt"])
    assert service.preview(**post)["data"]["photo_alt"] == args["alt"]
    assert service.write("post_create", "image-post", post)["ok"]
    form = parse_qs(requests[1].content.decode())
    assert form["photo"] == [retry["data"]["url"]] and form["mp-photo-alt"] == [args["alt"]]
    assert len(requests) == 2
    assert b"Blue rectangle" not in service.state.path.read_bytes()


@pytest.mark.parametrize(
    "file",
    ["../secret.png", "/tmp/secret.png", "secret.txt", "linked.png", "linked/image.png", "bad.png"],
)
def test_image_access_boundary(tmp_path, file):
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir(exist_ok=True)
    (outside / "image.png").write_bytes(image_bytes())
    (tmp_path / "linked.png").symlink_to(outside / "image.png")
    (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
    (tmp_path / "bad.png").write_text("not an image")
    with pytest.raises(ImageInputError):
        load_image(tmp_path, file)


def test_image_changed_read_only_and_unknown_never_resend(tmp_path):
    (tmp_path / "image.png").write_bytes(image_bytes())
    requests = []

    def response(request):
        requests.append(request)
        raise httpx.ReadTimeout("lost receipt", request=request)

    service = transport_service(tmp_path, response, media_root=tmp_path)
    args = dict(
        file="image.png",
        alt="Blue",
        sha256=service.media_preview("image.png", "Blue")["data"]["sha256"],
    )
    assert service.write("media_upload", "changed", {**args, "sha256": "0" * 64})["code"] == 409
    assert service.write("media_upload", "lost", args)["outcome"] == "unknown"
    assert service.write("media_upload", "lost", args)["outcome"] == "unknown"
    assert len(requests) == 1
    service.read_only = True
    assert service.write("media_upload", "readonly", args)["code"] == 403
    service.media_root = None
    assert service.media_preview("image.png", "Blue")["code"] == 400


def test_cli_receipt_matches_mcp_defaults(tmp_path):
    service, client = make_service(tmp_path)
    client.micropub_create.return_value = {"ok": True, "data": {"url": URL}}
    runner = CliRunner()
    with (
        patch("mb.commands.post.get_client", return_value=client),
        patch("mb.commands.post.get_service", return_value=service),
    ):
        result = runner.invoke(
            app, ["--format", "json", "post", "new", "Same payload", "--operation-id", "shared"]
        )
    assert result.exit_code == 0, result.output
    assert (
        service.write(
            "post_create",
            "shared",
            dict(
                content="Same payload",
                title=None,
                draft=False,
                photo_url=None,
                photo_alt=None,
                categories=None,
            ),
        )["outcome"]
        == "applied"
    )
    client.micropub_create.assert_called_once()
    status = service.operation_status("shared")
    assert status["data"]["url"] == URL


@pytest.mark.parametrize(
    "status,body,location", [(202, "", ""), (202, '{"error":"failed"}', URL), (200, "", URL)]
)
def test_ambiguous_upload_response_is_unknown(tmp_path, status, body, location):
    service = transport_service(
        tmp_path,
        lambda r: httpx.Response(status, text=body, headers={"Location": location}),
        media_root=tmp_path,
    )
    (tmp_path / "image.png").write_bytes(image_bytes())
    args = dict(
        file="image.png",
        alt="Blue",
        sha256=service.media_preview("image.png", "Blue")["data"]["sha256"],
    )
    assert service.write("media_upload", "ambiguous", args)["outcome"] == "unknown"
    assert service.write("media_upload", "ambiguous", args)["outcome"] == "unknown"


def test_cli_image_preview_upload_post_publish_and_read_scope(tmp_path):
    source = {"properties": {"post-status": ["draft"], "content": ["Photo"]}}
    requests = []

    def response(request):
        requests.append(request)
        if request.url.path == "/micropub/media":
            return httpx.Response(202, headers={"Location": BLOG + "uploads/image.png"})
        if request.method == "GET":
            if "url" in request.url.params:
                return httpx.Response(200, json=source)
            if request.url.params.get("q") == "category":
                return httpx.Response(200, json={"categories": ["photos"]})
            return httpx.Response(200, json={"items": [{"id": 1}]})
        return httpx.Response(204)

    service = transport_service(tmp_path, response, media_root=tmp_path)
    (tmp_path / "image.png").write_bytes(image_bytes())
    runner = CliRunner()
    with (
        patch("mb.commands.get_service", return_value=service),
        patch("mb.commands.media.get_service", return_value=service),
        patch("mb.commands.post.get_service", return_value=service),
        patch("mb.commands.post.get_client", return_value=service.client),
        patch("mb.commands.blog.get_service", return_value=service),
    ):
        preview = runner.invoke(
            app, ["media", "preview", "image.png", "--alt", "Blue", "--format", "json"]
        )
        assert preview.exit_code == 0, preview.output
        digest = json.loads(preview.output)["data"]["sha256"]
        uploaded = runner.invoke(
            app,
            [
                "media",
                "upload",
                "image.png",
                "--alt",
                "Blue",
                "--sha256",
                digest,
                "--operation-id",
                "cli-image",
                "--format",
                "json",
            ],
        )
        assert uploaded.exit_code == 0, uploaded.output
        publication = runner.invoke(
            app,
            [
                "post",
                "publish",
                URL,
                "--source-hash",
                source_hash(source),
                "--operation-id",
                "cli-publish",
                "--format",
                "json",
            ],
        )
        assert publication.exit_code == 0, publication.output
        status = runner.invoke(app, ["operation-status", "cli-publish", "--format", "json"])
        assert status.exit_code == 0 and json.loads(status.output)["outcome"] == "applied"
        read = runner.invoke(app, ["post", "replies", "--count", "1", "--format", "json"])
        assert json.loads(read.output)["data"]["scope"] == "account"
        categories = runner.invoke(app, ["blog", "categories", "--format", "json"])
        assert json.loads(categories.output)["data"]["identity"]["blog"] == BLOG
    assert len([r for r in requests if r.method == "POST"]) == 2


@pytest.mark.parametrize(
    "status,body,scope_error",
    [
        (403, "Token missing required scope", True),
        (403, "Access denied", False),
        (401, "Unauthorized", False),
    ],
)
def test_url_conversation_denial_is_actionable_and_never_changes_access_mode(
    tmp_path, status, body, scope_error
):
    requests = []

    def response(request):
        requests.append(request)
        return httpx.Response(status, text=body)

    service = transport_service(tmp_path, response)
    result = service.conversation("https://public.example/post")
    assert not result["ok"] and result["code"] == status
    assert "data" not in result
    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == "Bearer synthetic"
    assert requests[0].headers["Accept"] == "application/json"
    assert requests[0].url.path == "/conversation.js"
    if scope_error:
        assert result["reason"] == "insufficient_scope"
        assert "review Micro.blog read permissions" in result["error"]
        assert "native conversation ID" in result["error"]
    else:
        assert "reason" not in result
    assert not service.state.path.exists()


@pytest.mark.parametrize("fmt", ["agent", "json"])
def test_cli_url_scope_error_preserves_refusal_and_guidance(tmp_path, fmt):
    service = transport_service(
        tmp_path, lambda r: httpx.Response(403, text="Token missing required scope")
    )
    with patch("mb.commands.conversation.get_client", return_value=service.client):
        result = CliRunner().invoke(
            app, ["conversation", "https://public.example/post", "--format", fmt]
        )
    assert result.exit_code == 1
    if fmt == "json":
        envelope = json.loads(result.output)
        assert envelope["code"] == 403 and envelope["reason"] == "insufficient_scope"
        assert "data" not in envelope
    assert "review Micro.blog read permissions" in result.output
