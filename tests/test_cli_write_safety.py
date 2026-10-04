"""Real CLI routing and durable retry behavior with synthetic HTTP only."""

import json
from contextlib import ExitStack
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx
import pytest
from typer.testing import CliRunner

from mb.api import MicroblogClient
from mb.cli import app
from mb.services import MicroblogService
from tests.test_bounded_capabilities import image_bytes

BLOG = "https://agent.micro.blog/"
SECOND = "https://second.micro.blog/"
URL = BLOG + "post.html"


class Harness:
    def __init__(self, tmp_path, outcome="success"):
        self.path = tmp_path
        self.requests = []
        self.outcome = outcome
        self.unavailable = False

    @property
    def writes(self):
        return [r for r in self.requests if r.method == "POST" and r.url.path != "/account/verify"]

    def invoke(self, args, profile="default", blog=BLOG, username="agent"):
        def respond(request):
            self.requests.append(request)
            if request.url.path == "/account/verify":
                return httpx.Response(200, json={"username": username})
            if request.url.params.get("q") == "config":
                return httpx.Response(
                    200,
                    json={
                        "destination": [{"uid": BLOG}, {"uid": SECOND}],
                        "media-endpoint": "https://micro.blog/micropub/media",
                    },
                )
            if request.method == "GET":
                if self.unavailable:
                    return httpx.Response(404)
                if request.url.path == "/posts/conversation":
                    return httpx.Response(
                        200,
                        json={
                            "items": [
                                {
                                    "id": "12",
                                    "url": URL,
                                    "author": {"url": "https://micro.blog/other"},
                                }
                            ]
                        },
                    )
                return httpx.Response(
                    200, json={"type": ["h-entry"], "properties": {"content": ["old"]}}
                )
            if self.outcome == "timeout":
                raise httpx.ReadTimeout("synthetic", request=request)
            if self.outcome == "server":
                return httpx.Response(503)
            if self.outcome == "malformed":
                return httpx.Response(201)  # No confirmed Location.
            if request.url.path == "/posts/reply":
                return httpx.Response(200, json={"id": "13"})
            if request.url.path.endswith("/media"):
                return httpx.Response(201, headers={"Location": BLOG + "uploads/image.png"})
            if request.headers.get("Content-Type", "").startswith("application/json"):
                return httpx.Response(204)
            return httpx.Response(201, headers={"Location": blog + "created.html"})

        client = MicroblogClient("synthetic")
        client._client.close()
        client._client = httpx.Client(
            base_url="https://micro.blog", transport=httpx.MockTransport(respond)
        )
        service = MicroblogService(
            client, profile, blog, "cli", self.path / "receipts.sqlite", media_root=self.path
        )
        with ExitStack() as stack:
            stack.enter_context(client)
            stack.enter_context(patch("mb.commands.post.get_client", return_value=client))
            for module in ("post", "media", "upload"):
                stack.enter_context(
                    patch(f"mb.commands.{module}.get_service", return_value=service)
                )
            stack.enter_context(patch("mb.commands.get_service", return_value=service))
            result = CliRunner().invoke(app, ["--format", "json", *args])
        assert not result.exception or isinstance(result.exception, SystemExit), result.exception
        return result, json.loads(result.output)


@pytest.mark.parametrize(
    "args",
    [
        ["post", "new", "Hello"],
        ["post", "short", "Hello"],
        ["post", "reply", "12", "Hello"],
        ["post", "edit", URL, "--content", "Hello"],
        ["post", "delete", URL],
        ["upload", "image.png", "--alt", "Blue"],
    ],
)
def test_all_implicit_writes_refuse_before_http(tmp_path, args):
    harness = Harness(tmp_path)
    result, data = harness.invoke(args)
    assert result.exit_code == 1 and data["outcome"] == "not_applied"
    assert "--operation-id" in data["error"] and "reuse" in data["error"]
    assert harness.requests == []
    assert not (tmp_path / "receipts.sqlite").exists()


@pytest.mark.parametrize(
    "args",
    [
        ["post", "new", "Hello"],
        ["post", "short", "Hello"],
        ["post", "reply", "12", "Hello"],
        ["post", "edit", "12", "--content", "Hello"],
        ["post", "delete", "12"],
    ],
)
def test_repeated_command_returns_receipt_without_resolving_deleted_source(tmp_path, args):
    harness = Harness(tmp_path)
    command = [*args, "--operation-id", "task-12"]
    first, data = harness.invoke(command)
    assert first.exit_code == 0, data
    assert data["outcome"] == "applied" and len(harness.writes) == 1
    harness.unavailable = True
    retried, receipt = harness.invoke(command, profile="alias")
    assert retried.exit_code == 0, receipt
    assert receipt["operation_id"] == "task-12" and receipt["outcome"] == "applied"
    assert len(harness.writes) == 1
    _, conflict = harness.invoke(
        [*args, "--operation-id", "task-12"]
        if args[1] == "delete"
        else [*args[:-1], "Changed", "--operation-id", "task-12"]
    )
    if args[1] != "delete":
        assert conflict["code"] == 409 and len(harness.writes) == 1


@pytest.mark.parametrize("outcome", ["timeout", "server", "malformed"])
def test_ambiguous_create_is_never_resent(tmp_path, outcome):
    harness = Harness(tmp_path, outcome)
    args = ["post", "new", "Hello", "--operation-id", "uncertain"]
    _, data = harness.invoke(args)
    assert not data["ok"] and data["outcome"] == "unknown"
    _, receipt = harness.invoke(args)
    assert receipt["outcome"] == "unknown" and len(harness.writes) == 1
    _, status = harness.invoke(["operation-status", "uncertain"])
    assert status["outcome"] == "unknown" and len(harness.writes) == 1


@pytest.mark.parametrize("verb", ["edit", "delete"])
def test_selected_blog_guard_refuses_foreign_cli_target(tmp_path, verb):
    harness = Harness(tmp_path)
    args = ["post", verb, URL, "--operation-id", "wrong-blog"]
    if verb == "edit":
        args += ["--content", "Hello"]
    _, data = harness.invoke(args, blog=SECOND)
    assert data["code"] == 403 and not harness.writes
    assert all(r.url.params.get("q") != "source" for r in harness.requests)
    assert not (tmp_path / "receipts.sqlite").exists()


def test_cli_receipts_share_aliases_but_isolate_account_and_blog(tmp_path):
    harness = Harness(tmp_path)
    args = ["post", "new", "Hello", "--operation-id", "same-task"]
    for profile, blog, username in [
        ("a", BLOG, "agent"),
        ("alias", BLOG, "agent"),
        ("b", SECOND, "agent"),
        ("other", BLOG, "other"),
    ]:
        result, data = harness.invoke(args, profile, blog, username)
        assert result.exit_code == 0, data
    assert len(harness.writes) == 3
    assert [parse_qs(r.content.decode())["mp-destination"][0] for r in harness.writes] == [
        BLOG,
        SECOND,
        BLOG,
    ]


def test_native_reply_receipt_shared_across_selected_blog_profiles(tmp_path):
    harness = Harness(tmp_path)
    args = ["post", "reply", "12", "Hello", "--operation-id", "reply-task"]
    assert harness.invoke(args)[0].exit_code == 0
    assert harness.invoke(args, profile="second", blog=SECOND)[0].exit_code == 0
    assert len(harness.writes) == 1


@pytest.mark.parametrize("verb", ["new", "short"])
@pytest.mark.parametrize("with_id", [False, True])
def test_combined_photo_rejected_without_upload_or_post(tmp_path, verb, with_id):
    harness = Harness(tmp_path)
    args = ["post", verb, "Caption", "--photo", "image.png", "--alt", "Blue"]
    if with_id:
        args += ["--operation-id", "photo-task"]
    _, data = harness.invoke(args)
    assert data["outcome"] == "not_applied" and "media preview/upload" in data["error"]
    assert harness.requests == []


def test_upload_alias_and_explicit_media_share_receipt_even_without_file(tmp_path):
    harness = Harness(tmp_path)
    image = tmp_path / "image.png"
    image.write_bytes(image_bytes())
    _, preview = harness.invoke(["media", "preview", "image.png", "--alt", "Blue"])
    args = [
        "image.png",
        "--alt",
        "Blue",
        "--sha256",
        preview["data"]["sha256"],
        "--operation-id",
        "upload-task",
    ]
    result, uploaded = harness.invoke(["upload", *args])
    assert result.exit_code == 0, uploaded
    image.unlink()
    result, receipt = harness.invoke(["media", "upload", *args])
    assert result.exit_code == 0 and receipt["data"]["url"] == uploaded["data"]["url"]
    assert len(harness.writes) == 1


@pytest.mark.parametrize("verb", ["new", "short"])
def test_dry_run_without_id_still_has_no_network_or_receipt(tmp_path, verb):
    harness = Harness(tmp_path)
    result, data = harness.invoke(["post", verb, "Hello", "--dry-run"])
    assert result.exit_code == 0 and data["data"]["dry_run"]
    assert harness.requests == [] and not (tmp_path / "receipts.sqlite").exists()


@pytest.mark.parametrize("verb", ["edit", "delete", "reply"])
def test_ambiguous_other_post_writes_keep_one_dispatch(tmp_path, verb):
    harness = Harness(tmp_path, "timeout")
    args = ["post", verb, "12"]
    if verb == "edit":
        args += ["--content", "Hello"]
    elif verb == "reply":
        args += ["Hello"]
    args += ["--operation-id", "uncertain-target"]
    _, first = harness.invoke(args)
    assert first["outcome"] == "unknown"
    harness.unavailable = True
    _, second = harness.invoke(args)
    assert second["outcome"] == "unknown" and len(harness.writes) == 1


def test_upload_receipt_survives_uncertain_post_without_reupload(tmp_path):
    harness = Harness(tmp_path)
    image = tmp_path / "image.png"
    image.write_bytes(image_bytes())
    _, preview = harness.invoke(["media", "preview", "image.png", "--alt", "Blue"])
    upload_args = [
        "upload",
        "image.png",
        "--alt",
        "Blue",
        "--sha256",
        preview["data"]["sha256"],
        "--operation-id",
        "image-upload",
    ]
    _, uploaded = harness.invoke(upload_args)
    harness.outcome = "timeout"
    post_args = [
        "post",
        "new",
        "Caption",
        "--photo-url",
        uploaded["data"]["url"],
        "--alt",
        "Blue",
        "--operation-id",
        "image-post",
    ]
    _, failed = harness.invoke(post_args)
    assert failed["outcome"] == "unknown"
    image.unlink()
    _, receipt = harness.invoke(upload_args)
    assert receipt["ok"] and receipt["data"]["url"] == uploaded["data"]["url"]
    _, retried = harness.invoke(post_args)
    assert retried["outcome"] == "unknown" and len(harness.writes) == 2
    assert parse_qs(harness.writes[1].content.decode())["mp-photo-alt"] == ["Blue"]


def test_uncertain_upload_receipt_survives_file_removal(tmp_path):
    harness = Harness(tmp_path, "timeout")
    image = tmp_path / "image.png"
    image.write_bytes(image_bytes())
    _, preview = harness.invoke(["media", "preview", "image.png", "--alt", "Blue"])
    args = [
        "upload",
        "image.png",
        "--alt",
        "Blue",
        "--sha256",
        preview["data"]["sha256"],
        "--operation-id",
        "uncertain-upload",
    ]
    _, first = harness.invoke(args)
    assert first["outcome"] == "unknown"
    image.unlink()
    _, second = harness.invoke(args)
    assert second["outcome"] == "unknown" and len(harness.writes) == 1


def test_cli_scoped_status_refuses_receipt_collision(tmp_path):
    harness = Harness(tmp_path)
    assert harness.invoke(["post", "new", "Hello", "--operation-id", "shared"])[1]["ok"]
    assert harness.invoke(["post", "reply", "12", "Hello", "--operation-id", "shared"])[1]["ok"]
    result, ambiguous = harness.invoke(["operation-status", "shared"])
    assert result.exit_code == 1 and ambiguous["reason"] == "ambiguous_operation"
    assert (
        harness.invoke(["operation-status", "shared", "--scope", "reply"])[1]["data"]["id"] == "13"
    )
    assert (
        harness.invoke(["operation-status", "shared", "--scope", "blog"])[1]["data"]["url"]
        == BLOG + "created.html"
    )
