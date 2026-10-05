"""Live smoke test against a dedicated micro.blog test account. Never run it on a real blog.

Reads the token from MB_TEST_TOKEN and works in a throwaway HOME, so it never sees or
changes the operator's own configuration. It:

1. signs in with the guided `mb auth` in a pseudo-terminal, as a person would;
2. runs CLI reads (whoami, blogs, timeline, post list, doctor) from the saved profile;
3. calls every MCP read tool over stdio in read-only mode and validates each result
   against the tool's published output schema;
4. creates a draft on the test blog, edits it, publishes it and deletes it through MCP,
   deleting the post even when a step fails.

MB_TEST_BLOG optionally names the blog when the test account has several.
"""

import json
import os
import pty
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import termios
import time
from datetime import UTC, datetime
from pathlib import Path

import anyio
import jsonschema
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

TOKEN = os.environ.get("MB_TEST_TOKEN", "").strip()
BLOG = os.environ.get("MB_TEST_BLOG", "").strip() or None
MB = shutil.which("mb")
HOME = Path(tempfile.mkdtemp(prefix="mb-live-smoke-"))
RUN = os.environ.get("GITHUB_RUN_ID") or datetime.now(UTC).strftime("%Y%m%d%H%M%S")
ENV = {
    key: value
    for key, value in os.environ.items()
    if not key.startswith("MB_") and key not in {"HOME", "XDG_CONFIG_HOME"}
} | {"HOME": str(HOME)}

failures: list[str] = []


def step(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'} {name}{': ' + detail if detail else ''}", flush=True)
    if not ok:
        failures.append(name)


def guided_auth() -> None:
    """Drive bare `mb auth` through a pseudo-terminal: hidden token, then the blog prompt."""
    args = [MB, "auth"] + (["--blog", BLOG] if BLOG else [])
    pid, fd = pty.fork()
    if pid == 0:
        os.execve(MB, args, ENV)
    output = b""
    sent_token = False
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.5)
        if not ready:
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        output += chunk
        if not sent_token and b"Token (input hidden)" in output:
            # The prompt prints before echo is switched off; type only once it is.
            while termios.tcgetattr(fd)[3] & termios.ECHO and time.monotonic() < deadline:
                time.sleep(0.05)
            os.write(fd, TOKEN.encode() + b"\r")
            sent_token = True
        elif sent_token and chunk.rstrip().endswith(b"]:"):
            os.write(fd, b"\r")  # accept the offered default blog
    if time.monotonic() >= deadline:
        os.kill(pid, signal.SIGKILL)  # e.g. a rejected token re-prompts forever
    _, status = os.waitpid(pid, 0)
    code = os.waitstatus_to_exitcode(status)
    text = output.decode(errors="replace")
    config = HOME / ".config" / "mb" / "config.toml"
    step("guided auth exits 0", code == 0, f"exit {code}")
    step("guided auth never echoes the token", TOKEN not in text)
    step("guided auth links the token page", "micro.blog/account/apps" in text)
    step(
        "guided auth writes a 0600 config",
        config.exists() and config.stat().st_mode & 0o777 == 0o600,
    )


def cli(*args: str) -> dict:
    """Run one CLI command as JSON from the saved profile, never with MB_TOKEN."""
    proc = subprocess.run(
        [MB, "-f", "json", *args], env=ENV, capture_output=True, text=True, timeout=120
    )
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        result = {"ok": False, "error": proc.stdout[-500:] + proc.stderr[-500:]}
    ok = proc.returncode == 0 and result.get("ok") is True and result.get("schema_version") == 1
    step(f"cli {' '.join(args)}", ok, "" if ok else str(result.get("error", ""))[:300])
    return result


def server(*extra: str) -> StdioServerParameters:
    args = ["mcp", "--consumer", "live-smoke", *extra]
    return StdioServerParameters(command=MB, args=args, env=ENV)


async def call(session: ClientSession, schemas: dict, tool: str, args: dict | None = None) -> dict:
    result = await session.call_tool(tool, args or {})
    content = result.structured_content or {}
    problem = ""
    try:
        jsonschema.validate(content, schemas[tool])
    except jsonschema.ValidationError as exc:
        problem = f"schema: {exc.message}"
    if not problem and content.get("ok") is not True:
        problem = f"{content.get('code')} {content.get('error')}"
    step(f"mcp {tool}", not problem, problem[:300])
    return content


async def mcp_reads() -> None:
    async with stdio_client(server("--read-only")) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=60) as session:
            await session.initialize()
            tools = await session.list_tools()
            schemas = {t.name: t.output_schema for t in tools.tools}
            step("mcp lists 23 tools", len(schemas) == 23, str(len(schemas)))
            identity = await call(session, schemas, "identity")
            username = (identity.get("data") or {}).get("username", "")
            timeline = await call(session, schemas, "timeline", {"count": 5})
            await call(session, schemas, "timeline", {"count": 2, "verbose": True})
            await call(session, schemas, "heartbeat")
            await call(session, schemas, "inbox")
            await call(session, schemas, "catchup")
            await call(session, schemas, "discover", {"count": 5})
            await call(session, schemas, "replies", {"count": 5})
            if username:
                await call(session, schemas, "profile_get", {"username": username, "count": 3})
            await call(session, schemas, "blog_posts", {"count": 3})
            await call(session, schemas, "blog_search", {"query": "the", "count": 3})
            await call(session, schemas, "blog_categories")
            items = (timeline.get("data") or {}).get("items") or []
            if items:
                await call(session, schemas, "conversation", {"post_id": str(items[0]["id"])})
            await call(
                session, schemas, "post_preview", {"content": f"mb live smoke preview {RUN}"}
            )


async def mcp_write_cycle() -> None:
    """Draft, edit, publish and delete one post on the test blog; always clean up."""
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    async with stdio_client(server()) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=60) as session:
            await session.initialize()
            tools = await session.list_tools()
            schemas = {t.name: t.output_schema for t in tools.tools}
            created = await call(
                session,
                schemas,
                "post_create",
                {
                    "content": f"mb live smoke {RUN} draft ({stamp}). This test post is deleted "
                    "within a minute.",
                    "draft": True,
                    "operation_id": f"smoke-{RUN}-create",
                },
            )
            url = (created.get("data") or {}).get("url")
            step("draft has a url", bool(url))
            if not url:
                return
            try:
                draft = await call(session, schemas, "post_get", {"identifier": url})
                status = (draft.get("data") or {}).get("properties", {}).get("post-status")
                step("new post is a draft", status == ["draft"], str(status))
                await call(
                    session,
                    schemas,
                    "post_edit",
                    {
                        "identifier": url,
                        "content": f"mb live smoke {RUN} edited ({stamp}). This test post is "
                        "deleted within a minute.",
                        "operation_id": f"smoke-{RUN}-edit",
                    },
                )
                edited = await call(session, schemas, "post_get", {"identifier": url})
                data = edited.get("data") or {}
                content = " ".join(data.get("properties", {}).get("content") or [])
                step("edit is visible", "edited" in content)
                await call(
                    session,
                    schemas,
                    "post_publish",
                    {
                        "identifier": url,
                        "source_hash": data.get("source_hash", ""),
                        "operation_id": f"smoke-{RUN}-publish",
                    },
                )
                published = await call(session, schemas, "post_get", {"identifier": url})
                status = (published.get("data") or {}).get("properties", {}).get("post-status")
                step("published post is live", status == ["published"], str(status))
            finally:
                await call(
                    session,
                    schemas,
                    "post_delete",
                    {"identifier": url, "operation_id": f"smoke-{RUN}-delete"},
                )
                gone = await session.call_tool("post_get", {"identifier": url})
                step("deleted post is gone", (gone.structured_content or {}).get("ok") is False)
            await call(
                session, schemas, "operation_status", {"operation_id": f"smoke-{RUN}-delete"}
            )


def main() -> int:
    if not TOKEN:
        print("MB_TEST_TOKEN is not set; this test needs a dedicated test account.")
        return 2
    if not MB:
        print("mb is not on PATH")
        return 2
    try:
        guided_auth()
        if failures:
            print("\nSign-in failed; skipping the remaining checks.")
            return 1
        cli("whoami")
        cli("blogs")
        cli("timeline", "--count", "3")
        cli("post", "list")
        doctor = cli("doctor")
        step("doctor healthy", (doctor.get("data") or {}).get("healthy") is True)
        anyio.run(mcp_reads)
        anyio.run(mcp_write_cycle)
    finally:
        shutil.rmtree(HOME, ignore_errors=True)
    print(f"\n{len(failures)} failed" if failures else "\nall live checks passed")
    for name in failures:
        print(f"  - {name}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
