"""Codex-style MCP stdio lifecycle against a synthetic Micro.blog backend."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def anyio_backend():
    return "asyncio"


def parameters(tmp_path, *extra):
    return StdioServerParameters(
        command=sys.executable,
        args=[
            str(ROOT / "tests/mcp_fixture.py"),
            "mcp",
            "--consumer",
            "dot",
            "--state-file",
            str(tmp_path / "state.sqlite"),
            *extra,
        ],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src"), "MB_TEST_DIR": str(tmp_path)},
    )


@pytest.mark.anyio
async def test_stdio_complete_agent_session(tmp_path):
    async with stdio_client(parameters(tmp_path)) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=10) as session:
            initialization = await session.initialize()
            assert initialization.server_info.name == "mb"
            tools = (await session.list_tools()).tools
            assert len(tools) == 23
            assert all(tool.output_schema for tool in tools)
            delete = next(tool for tool in tools if tool.name == "post_delete")
            assert delete.annotations.destructive_hint is True
            assert delete.annotations.read_only_hint is False

            async def call(name, args=None):
                result = await session.call_tool(name, args or {})
                assert result.structured_content == json.loads(result.content[0].text)
                return result

            identity = (await call("identity")).structured_content["data"]
            assert identity["username"] == "agent"
            assert identity["blog"] == "https://agent.example/"
            assert len((await session.list_resources()).resources) == 3
            guide = await session.read_resource("mb://guide")
            assert "deliberate skip" in guide.contents[0].text
            resource_identity = await session.read_resource("mb://identity")
            assert json.loads(resource_identity.contents[0].text)["data"] == identity
            assert (await session.read_resource("mb://discover-collections")).contents
            assert (await call("heartbeat")).structured_content["data"]["mentions"]
            assert (await call("inbox")).structured_content["data"]["items"][0][
                "reason"
            ] == "mention"
            assert (await call("conversation", {"post_id": "8"})).structured_content["data"][
                "items"
            ][0]["id"] == "8"
            cursor = None
            seen = []
            for _ in range(10):
                args = {"count": 3, **({"cursor": cursor} if cursor else {})}
                page = (await call("catchup", args)).structured_content["data"]
                seen += [item["id"] for item in page["items"]]
                assert page["advanced"] is False
                cursor = page["next_cursor"]
                if not cursor:
                    break
            assert seen == [str(i) for i in range(8, 0, -1)]
            assert (
                await call("checkpoint_ack", {"receipt": page["ack_receipt"]})
            ).structured_content["ok"]
            preview = (
                await call("post_preview", {"content": "Public project observation"})
            ).structured_content
            assert preview["data"]["dry_run"]
            created = (
                await call(
                    "post_create",
                    {"content": "Public project observation", "operation_id": "session-post"},
                )
            ).structured_content
            assert created["outcome"] == "applied"
            url = created["data"]["url"]
            readback = (await call("post_get", {"identifier": url})).structured_content
            assert readback["data"]["properties"]["content"] == ["Public project observation"]
            assert (await call("blog_posts")).structured_content["data"]["items"]
            assert (
                await call(
                    "post_edit",
                    {"identifier": url, "content": "Edited", "operation_id": "session-edit"},
                )
            ).structured_content["ok"]
            assert (
                await call(
                    "post_reply",
                    {"post_id": "8", "content": "Thanks", "operation_id": "session-reply"},
                )
            ).structured_content["ok"]
            assert (
                await call("post_delete", {"identifier": url, "operation_id": "session-delete"})
            ).structured_content["ok"]
            # Retry succeeds even though its source no longer exists.
            assert (
                await call("post_delete", {"identifier": url, "operation_id": "session-delete"})
            ).structured_content["ok"]
            assert (
                await call("operation_status", {"operation_id": "session-post"})
            ).structured_content["outcome"] == "applied"
            invalid = await call(
                "post_create", {"content": "PRIVATE", "operation_id": "x", "token": "SECRET"}
            )
            assert invalid.is_error
            assert "SECRET" not in str(invalid)


@pytest.mark.anyio
async def test_stdio_read_only(tmp_path):
    async with stdio_client(parameters(tmp_path, "--read-only")) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "post_create", {"content": "hello", "operation_id": "denied"}
            )
            assert result.is_error and result.structured_content["code"] == 403
            result = await session.call_tool("checkpoint_ack", {"receipt": "bogus"})
            assert result.structured_content["code"] == 403
            assert not (tmp_path / "state.sqlite").exists()


def test_stdout_is_protocol_only(tmp_path):
    config = parameters(tmp_path)
    env = {**os.environ, **config.env}
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2026-07-28",
                "capabilities": {},
                "clientInfo": {"name": "codex-test", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    result = subprocess.run(
        [config.command, *config.args],
        input="\n".join(json.dumps(r) for r in requests) + "\n",
        text=True,
        capture_output=True,
        env=env,
        cwd=ROOT,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    lines = [json.loads(line) for line in result.stdout.splitlines()]
    assert lines and all(line["jsonrpc"] == "2.0" for line in lines)
    assert "synthetic-never-a-real-token" not in result.stdout + result.stderr
    assert "Traceback" not in result.stderr


def test_cli_help_does_not_import_optional_mcp():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from typer.testing import CliRunner; from mb.cli import app; r=CliRunner().invoke(app,['--help']); assert r.exit_code==0; assert 'mcp' in r.stdout; assert 'mcp.server' not in sys.modules",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        timeout=10,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.anyio
async def test_receipt_storage_failure_is_explicitly_uncertain(tmp_path):
    from unittest.mock import Mock

    from mcp import types

    from mb.api import MicroblogClient
    from mb.mcp_server import Adapter
    from mb.services import MicroblogService

    client = Mock(spec=MicroblogClient)
    client.token = "synthetic-SECRET"
    client.verify_token.return_value = {"ok": True, "data": {"username": "agent"}}
    client.micropub_get_config.return_value = {
        "ok": True,
        "data": {"destination": [{"uid": "https://agent.example/"}]},
    }
    client.micropub_create.return_value = {
        "ok": True,
        "data": {"url": "https://agent.example/post"},
    }
    service = MicroblogService(client, "default", None, "dot", tmp_path / "state.sqlite")
    service.state.finish = Mock(side_effect=OSError("SECRET disk detail"))
    adapter = Adapter(lambda: service)
    result = await adapter.call_tool(
        None,
        types.CallToolRequestParams(
            name="post_create", arguments={"content": "hello", "operation_id": "storage-failure"}
        ),
    )
    assert result.is_error
    assert result.structured_content["outcome"] == "unknown"
    assert result.structured_content["operation_id"] == "storage-failure"
    assert "SECRET" not in str(result)
    retry = await adapter.call_tool(
        None,
        types.CallToolRequestParams(
            name="post_create", arguments={"content": "hello", "operation_id": "storage-failure"}
        ),
    )
    assert retry.structured_content["outcome"] == "unknown"
    client.micropub_create.assert_called_once()


@pytest.mark.anyio
async def test_missing_auth_allows_discovery_and_returns_actionable_error(tmp_path):
    params = parameters(tmp_path)
    params.env["MB_TEST_MISSING_AUTH"] = "1"
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            assert len((await session.list_tools()).tools) == 23
            assert (await session.read_resource("mb://guide")).contents
            result = await session.call_tool("identity", {})
            assert result.is_error
            assert result.structured_content["code"] == 401
            assert "host environment" in result.structured_content["error"]
            assert not (tmp_path / "state.sqlite").exists()


@pytest.mark.anyio
async def test_stdio_local_image_draft_workflow_and_new_reads(tmp_path):
    raw = b"\x89PNG\r\n\x1a\n" + b"synthetic image bytes"
    (tmp_path / "image.png").write_bytes(raw)
    async with stdio_client(parameters(tmp_path, "--media-root", str(tmp_path))) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=10) as session:
            await session.initialize()

            async def call(name, arguments):
                result = await session.call_tool(name, arguments)
                assert not result.is_error, result
                return result.structured_content

            for name, args in [
                ("discover", {"count": 1}),
                ("profile_get", {"username": "agent", "count": 1}),
                ("replies", {"count": 1}),
                ("conversation", {"post_id": "https://external.example/post"}),
            ]:
                assert (await call(name, args))["data"]["scope"] == "account"
            image = (await call("media_preview", {"file": "image.png", "alt": "Blue rectangle"}))[
                "data"
            ]
            assert image["byte_count"] == len(raw) and image["mime_type"] == "image/png"
            assert not (tmp_path / "state.sqlite").exists()
            args = {
                "file": "image.png",
                "alt": image["alt"],
                "sha256": image["sha256"],
                "operation_id": "sdk-image",
            }
            uploaded = await call("media_upload", args)
            assert uploaded["data"]["processing_pending"]
            assert (await call("media_upload", args))["data"]["url"] == uploaded["data"]["url"]
            payload = {
                "content": "Image draft",
                "photo_url": uploaded["data"]["url"],
                "photo_alt": image["alt"],
                "draft": True,
            }
            assert (await call("post_preview", payload))["data"]["photo_alt"] == image["alt"]
            created = await call("post_create", {**payload, "operation_id": "sdk-draft"})
            source = (await call("post_get", {"identifier": created["data"]["url"]}))["data"]
            assert source["properties"]["mp-photo-alt"] == [image["alt"]]
            publish = {
                "identifier": created["data"]["url"],
                "source_hash": source["source_hash"],
                "operation_id": "sdk-publish",
            }
            assert (await call("post_publish", publish))["outcome"] == "applied"
            assert (await call("post_publish", publish))["outcome"] == "applied"
            assert (await call("blog_search", {"query": "Image", "count": 1}))["data"][
                "scope"
            ] == "selected-blog"
            assert (await call("blog_categories", {}))["data"]["categories"] == ["photos"]
            result = await session.call_tool(
                "media_preview", {"file": "../secret.png", "alt": "Bad"}
            )
            assert result.is_error


@pytest.mark.anyio
async def test_stdio_concurrent_retries_and_scoped_receipt_lookup(tmp_path):
    import anyio

    async with stdio_client(parameters(tmp_path)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            results = []

            async def create():
                results.append(
                    await session.call_tool(
                        "post_create", {"content": "Fixture only", "operation_id": "shared-id"}
                    )
                )

            async with anyio.create_task_group() as group:
                for _ in range(4):
                    group.start_soon(create)
            assert all(r.structured_content["outcome"] == "applied" for r in results)
            assert len({r.structured_content["data"]["url"] for r in results}) == 1
            reply = await session.call_tool(
                "post_reply",
                {"post_id": "8", "content": "Fixture reply", "operation_id": "shared-id"},
            )
            assert reply.structured_content["outcome"] == "applied"
            ambiguous = await session.call_tool("operation_status", {"operation_id": "shared-id"})
            assert (
                ambiguous.is_error
                and ambiguous.structured_content["reason"] == "ambiguous_operation"
            )
            blog = await session.call_tool(
                "operation_status", {"operation_id": "shared-id", "scope": "blog"}
            )
            reply = await session.call_tool(
                "operation_status", {"operation_id": "shared-id", "scope": "reply"}
            )
            assert blog.structured_content["data"]["url"] == "https://agent.example/post"
            assert reply.structured_content["data"]["id"] == "9"
            bad = await session.call_tool(
                "operation_status", {"operation_id": "shared-id", "scope": "account"}
            )
            assert bad.is_error and bad.structured_content["code"] == 400


@pytest.mark.anyio
async def test_stdio_opaque_attention_advance_retry_and_legacy_refusal(tmp_path):
    import sqlite3
    from contextlib import closing

    import anyio

    params = parameters(tmp_path)
    params.env["MB_TEST_OPAQUE_FEED"] = "1"
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(name, args):
                response = await session.call_tool(name, args)
                assert response.structured_content == json.loads(response.content[0].text)
                return response.structured_content

            async def catchup():
                values, cursor = [], None
                for _ in range(8):
                    page = (
                        await call(
                            "catchup", {"count": 2, **({"cursor": cursor} if cursor else {})}
                        )
                    )["data"]
                    values.extend(i["id"] for i in page["items"])
                    cursor = page["next_cursor"]
                    if not cursor:
                        return values, page
                pytest.fail("Fixture did not exhaust")

            values, page = await catchup()
            assert values == ["9", "3", "7", "2", "8", "1"]
            assert page["checkpoint_status"] == "empty" and page["coverage_complete"]
            assert (await call("checkpoint_ack", {"receipt": page["ack_receipt"]}))["data"][
                "checkpoint"
            ] == "9"
            # This write runs entirely inside the synthetic subprocess backend.
            assert (
                await call(
                    "post_create", {"content": "Fixture only", "operation_id": "opaque-fixture"}
                )
            )["ok"]
            values, page = await catchup()
            assert values == ["4"] and page["checkpoint_status"] == "native-order-v1"
            results = []

            async def ack():
                results.append(await call("checkpoint_ack", {"receipt": page["ack_receipt"]}))

            async with anyio.create_task_group() as group:
                group.start_soon(ack)
                group.start_soon(ack)
            assert all(
                r["data"]["checkpoint"] == "4" and r["data"]["revision"] == 2 for r in results
            )
            assert sorted(r["data"]["already_applied"] for r in results) == [False, True]
            with closing(sqlite3.connect(tmp_path / "state.sqlite")) as db, db:
                db.execute("UPDATE cursors SET value='9',revision=3")  # RC2-style old writer.
            values, legacy = await catchup()
            assert values == ["4"] and legacy["checkpoint_review_required"]
            assert not legacy["coverage_complete"] and legacy["ack_receipt"] is None
            stale = await call("checkpoint_ack", {"receipt": page["ack_receipt"]})
            assert stale["reason"] == "checkpoint_review_required"
