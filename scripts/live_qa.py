"""Full live QA against the dedicated micro.blog test account. Never run it on a real blog.

Runs the live smoke checks, then exercises the rest of the CLI and MCP surface:

- every read command, in json, agent and human formats, plus the stdin pipelines;
- refusal paths: bad arguments, unknown users and posts, URLs off the blog,
  reused operation IDs, stale source hashes and read-only MCP writes;
- local state: checkpoints, heartbeat/inbox/catchup advancing and checkpoint_ack;
- the CLI post lifecycle on the test blog: dry run, titled draft with a category,
  idempotent retry, edit, publish (and refusal to publish twice), edit after
  publishing, direct posts and short posts, delete and receipts;
- profiles: a second profile signed in through `mb auth -`.

Every post it creates starts with the smoke marker and is deleted, and a final sweep
removes anything a failed run left behind. Social writes (follow, mute, block, reply)
and media uploads are not exercised.
"""

import json
import signal
import subprocess
import sys
import time

import anyio
from live_smoke import (
    ENV,
    HOME,
    MARKER,
    MB,
    RUN,
    TOKEN,
    call,
    cli,
    failures,
    guided_auth,
    mcp_reads,
    mcp_write_cycle,
    server,
    smoke_posts,
    step,
)
from mcp import ClientSession
from mcp.client.stdio import stdio_client

PUBLIC_USER = "manton"  # Micro.blog's founder: a stable public account for reads


def run(*args: str, fmt: str | None = "json", stdin: str | None = None, profile: str = ""):
    command = [MB]
    if profile:
        command += ["--profile", profile]
    if fmt:
        command += ["-f", fmt]
    return subprocess.run(
        command + list(args), env=ENV, input=stdin, capture_output=True, text=True, timeout=180
    )


def clean(proc) -> bool:
    return "Traceback" not in proc.stderr and "Traceback" not in proc.stdout


def refused(name: str, *args: str, code: int | None = None, exit: int = 1, **kw) -> dict:
    """A structured refusal: the expected exit status, ok false, no traceback."""
    proc = run(*args, **kw)
    try:
        result = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        result = {}
    ok = proc.returncode == exit and clean(proc)
    if exit == 1:
        ok = ok and result.get("ok") is False and (code is None or result.get("code") == code)
    detail = f"exit {proc.returncode} code {result.get('code')} {str(result.get('error'))[:120]}"
    step(f"refuses {name}", ok, detail)
    return result


def text(name: str, *args: str, fmt: str, stdin: str | None = None) -> str:
    proc = run(*args, fmt=fmt, stdin=stdin)
    ok = proc.returncode == 0 and clean(proc) and bool(proc.stdout.strip())
    step(f"{fmt} {name}", ok, "" if ok else (proc.stderr or proc.stdout)[-300:])
    return proc.stdout


def data(result: dict) -> dict:
    return result.get("data") or {}


# ── reads ─────────────────────────────────────────────────


def cli_reads() -> tuple[str, str]:
    me = data(cli("whoami")).get("username", "")
    cli("profiles")
    text("guide", "guide", fmt="agent")
    timeline = data(cli("timeline", "--count", "5"))
    ids = [str(i["id"]) for i in timeline.get("items", []) if i.get("id")]
    post_id = ids[0] if ids else ""
    if len(ids) > 2:
        cli("timeline", "--count", "3", "--before", ids[1])
        cli("timeline", "--count", "3", "--since", ids[-1])
        cli("timeline", "check", "--since", ids[-1])
    cli("timeline", "mentions")
    cli("timeline", "photos")
    cli("timeline", "discover", "--count", "3")
    cli("discover", "--list")
    cli("discover", "--collection", "books", "--count", "3")
    cli("user", "show", PUBLIC_USER, "--count", "3")
    if me:
        cli("user", "show", me, "--count", "3")
    cli("user", "following")
    cli("following", PUBLIC_USER)
    cli("user", "discover", PUBLIC_USER)
    cli("user", "is-following", PUBLIC_USER)
    cli("user", "muting")
    cli("user", "blocking")
    cli("lookup", "users", PUBLIC_USER, "--last-post", "--days-since-posting")
    if post_id:
        cli("conversation", post_id)
        cli("lookup", "posts", post_id, "--post", "--conversation")
    categories = data(cli("blog", "categories")).get("categories") or []
    cli("blog", "posts", "--count", "5")
    if categories:
        cli("blog", "posts", "--count", "3", "--category", str(categories[0]))
    cli("blog", "search", "the", "--count", "3")
    cli("post", "list")
    cli("post", "list", "--drafts")
    cli("post", "replies", "--count", "3")
    return me, post_id


def formats_and_pipelines(post_id: str) -> None:
    for fmt in ("agent", "human"):
        text("whoami", "whoami", fmt=fmt)
        text("timeline", "timeline", "--count", "3", fmt=fmt)
        text("blog posts", "blog", "posts", "--count", "3", fmt=fmt)
        text("inbox", "inbox", "--all", fmt=fmt)
        text("doctor", "doctor", fmt=fmt)
    lines = run("timeline", "--count", "3", fmt="agent").stdout
    text("timeline | lookup posts -", "lookup", "posts", "-", "--post", fmt="json", stdin=lines)
    text(
        "names | lookup users -",
        "lookup",
        "users",
        "-",
        "--last-post",
        fmt="json",
        stdin=f"# c\n\n{PUBLIC_USER}\n",
    )
    if post_id:
        text("conversation", "conversation", post_id, fmt="agent")


def poll(post_id: str) -> None:
    if not post_id:
        return
    command = [MB, "-f", "json", "poll", "--since", post_id, "--interval", "2"]
    proc = subprocess.Popen(
        command, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    time.sleep(6)
    proc.send_signal(signal.SIGINT)
    out, err = proc.communicate(timeout=20)
    lines = [line for line in out.splitlines() if line.strip()]
    parsed = all(_is_json(line) for line in lines)
    step(
        "poll emits JSON lines and stops on ctrl-c",
        parsed and "Traceback" not in err,
        f"{len(lines)} lines",
    )


def _is_json(line: str) -> bool:
    try:
        json.loads(line)
    except json.JSONDecodeError:
        return False
    return True


def refusals() -> None:
    refused("an out-of-range count", "timeline", "--count", "99", exit=2)
    refused("an unknown format", "whoami", fmt="yaml", exit=2)
    refused("an unknown user", "user", "show", "no-such-user-mb-qa-zz9")
    refused(
        "a missing post", "post", "get", "https://612.poapchallenge.com/2001/01/01/missing.html"
    )
    refused(
        "an edit off the selected blog",
        "post",
        "edit",
        "https://manton.org/2020/01/01/x.html",
        "--content",
        f"{MARKER} nope",
        "--operation-id",
        f"qa-{RUN}-offblog",
    )
    refused("an unnamed checkpoint", "checkpoint", "get", "bad name!")
    refused("bare auth without a terminal", "auth", stdin="")


# ── local state ───────────────────────────────────────────


def checkpoints(post_id: str) -> None:
    if not post_id:
        return
    cli("checkpoint", "set", "qa", post_id)
    got = data(cli("checkpoint", "get", "qa"))
    step(
        "checkpoint round-trips", str(got.get("checkpoint", got.get("id", ""))) == post_id, str(got)
    )
    cli("checkpoint", "list")
    cli("timeline", "checkpoint", post_id)
    cli("timeline", "checkpoint")
    cli("heartbeat")
    cli("heartbeat", "--no-advance", "--mentions-only")
    # Advancing is refused while more mentions remain than were read; both outcomes are valid.
    proc = run("inbox", "--advance")
    result = json.loads(proc.stdout or "{}")
    allowed = result.get("ok") is True or "truncated" in str(result.get("error"))
    step(
        "inbox --advance advances or refuses a truncated page",
        allowed and clean(proc),
        str(result.get("error")),
    )
    cli("catchup", "--advance")
    cli("catchup")
    cli("checkpoint", "clear", "qa")
    cli("checkpoint", "clear", "--all")


async def mcp_extended() -> None:
    async with stdio_client(server("--read-only")) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=60) as session:
            await session.initialize()
            schemas = {t.name: t.output_schema for t in (await session.list_tools()).tools}
            for tool, args in [
                ("heartbeat", {}),
                ("inbox", {"count": 3}),
                ("discover", {"count": 3, "collection": "books"}),
                ("profile_get", {"username": PUBLIC_USER, "count": 3}),
                ("blog_posts", {"count": 3, "drafts": True}),
                ("replies", {"count": 3}),
            ]:
                await call(session, schemas, tool, {**args, "verbose": True})
            result = await session.call_tool(
                "post_create",
                {"content": f"{MARKER} read-only", "operation_id": f"qa-{RUN}-ro"},
            )
            code = (result.structured_content or {}).get("code")
            step("read-only server refuses post_create", code == 403, str(code))
            result = await session.call_tool("checkpoint_ack", {"receipt": "bogus"})
            code = (result.structured_content or {}).get("code")
            step("read-only server refuses checkpoint_ack", code == 403, str(code))

    async with stdio_client(server()) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=60) as session:
            await session.initialize()
            schemas = {t.name: t.output_schema for t in (await session.list_tools()).tools}
            beat = data(await call(session, schemas, "heartbeat"))
            receipt = beat.get("ack_receipt")
            step("heartbeat offers an ack receipt", bool(receipt))
            if receipt:
                ack = data(await call(session, schemas, "checkpoint_ack", {"receipt": receipt}))
                step("checkpoint_ack applies", ack.get("already_applied") is False, str(ack))
                again = data(await call(session, schemas, "checkpoint_ack", {"receipt": receipt}))
                step("checkpoint_ack is idempotent", again.get("already_applied") is True)
            inbox = data(await call(session, schemas, "inbox", {"count": 5}))
            step("fresh inbox reports anchor state", "anchor_missing" in inbox, str(sorted(inbox)))


# ── CLI post lifecycle on the test blog ───────────────────


def get(url: str) -> dict:
    return data(cli("post", "get", url))


def prop(source: dict, name: str) -> list:
    return (source.get("properties") or {}).get(name) or []


def cli_write_cycle() -> None:
    op = f"qa-{RUN}"
    body = f"{MARKER} {RUN} cli draft. This test post is deleted within a minute."
    dry = cli("post", "new", "--dry-run", "--title", "QA", body)
    step("dry run sends nothing", data(dry).get("dry_run") is True, str(sorted(data(dry))))
    draft_args = ["post", "new", "--draft", "--title", "QA draft", "--category", "qa", body]
    created = data(cli(*draft_args, "--operation-id", f"{op}-draft"))
    url = created.get("url", "")
    step("cli draft has a url", bool(url), url)
    if not url:
        return
    urls = [url]
    try:
        retry = data(cli(*draft_args, "--operation-id", f"{op}-draft"))
        step(
            "same operation ID returns the same draft",
            retry.get("url") == url,
            str(retry.get("url")),
        )
        refused(
            "an operation ID reused with different content",
            "post",
            "new",
            "--draft",
            f"{body} changed",
            "--operation-id",
            f"{op}-draft",
        )
        source = get(url)
        step(
            "draft keeps title and category",
            prop(source, "name") == ["QA draft"] and "qa" in prop(source, "category"),
            str(source.get("properties")),
        )
        step("draft status", prop(source, "post-status") == ["draft"])
        refused(
            "an empty edit", "post", "edit", url, "--content", "", "--operation-id", f"{op}-empty"
        )
        cli(
            "post",
            "edit",
            url,
            "--content",
            body.replace("draft", "edited"),
            "--title",
            "QA edited",
            "--operation-id",
            f"{op}-edit",
        )
        source = get(url)
        step(
            "cli edit visible",
            "edited" in " ".join(prop(source, "content")) and prop(source, "name") == ["QA edited"],
        )
        refused(
            "a stale source hash",
            "post",
            "publish",
            url,
            "--source-hash",
            "0" * 64,
            "--operation-id",
            f"{op}-stale",
            code=409,
        )
        published = data(
            cli(
                "post",
                "publish",
                url,
                "--source-hash",
                source.get("source_hash", ""),
                "--operation-id",
                f"{op}-publish",
            )
        )
        live = published.get("url", url)
        urls.append(live)
        step(
            "cli publish reports the new url",
            live != url and published.get("draft_url") == url,
            f"{url} -> {live}",
        )
        source = get(live)
        step("published status", prop(source, "post-status") == ["published"])
        refused(
            "publishing a post that is not a draft",
            "post",
            "publish",
            live,
            "--source-hash",
            source.get("source_hash", ""),
            "--operation-id",
            f"{op}-again",
            code=409,
        )
        cli(
            "post",
            "edit",
            live,
            "--content",
            body.replace("draft", "edited after publish"),
            "--operation-id",
            f"{op}-edit2",
        )
        step("edit after publish visible", "after publish" in " ".join(prop(get(live), "content")))
        cli("operation-status", f"{op}-publish")
        cli("operation-status", "--latest")
    finally:
        for index, target in enumerate(dict.fromkeys(reversed(urls))):
            run("post", "delete", target, "--operation-id", f"{op}-delete-{index}")
    refused("reading a deleted post", "post", "get", urls[-1])

    for kind, args in [
        ("direct post", ["post", "new", "--title", "QA direct", f"{MARKER} {RUN} direct post."]),
        ("short post", ["post", "short", f"{MARKER} {RUN} short post."]),
    ]:
        made = data(cli(*args, "--operation-id", f"{op}-{kind.split()[0]}"))
        target = made.get("url", "")
        step(
            f"{kind} is published",
            prop(get(target), "post-status") == ["published"] if target else False,
            target,
        )
        if target:
            cli("post", "delete", target, "--operation-id", f"{op}-{kind.split()[0]}-delete")


def second_profile() -> None:
    proc = run("auth", "-", stdin=TOKEN + "\n", profile="qa")
    ok = proc.returncode == 0 and TOKEN not in proc.stdout + proc.stderr and clean(proc)
    step("mb --profile qa auth - signs in from stdin", ok, f"exit {proc.returncode}")
    who = run("whoami", profile="qa")
    step("profile qa works", who.returncode == 0)
    names = [p.get("name") for p in data(cli("profiles")).get("profiles", [])]
    step("both profiles listed", {"default", "qa"} <= set(names), str(names))


async def sweep() -> None:
    async with stdio_client(server()) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=60) as session:
            await session.initialize()
            for index, leftover in enumerate(await smoke_posts(session)):
                print(f"     deleting leftover {leftover}", flush=True)
                await session.call_tool(
                    "post_delete",
                    {"identifier": leftover, "operation_id": f"qa-{RUN}-sweep-{index}"},
                )
            left = await smoke_posts(session)
            step("no QA posts left on the blog", not left, str(left))


def main() -> int:
    if not TOKEN:
        print("MB_TEST_TOKEN is not set; this test needs a dedicated test account.")
        return 2
    import shutil

    try:
        guided_auth()
        if failures:
            print("\nSign-in failed; skipping the remaining checks.")
            return 1
        print("\n# reads", flush=True)
        _, post_id = cli_reads()
        print("\n# formats and pipelines", flush=True)
        formats_and_pipelines(post_id)
        poll(post_id)
        print("\n# refusals", flush=True)
        refusals()
        print("\n# local state", flush=True)
        checkpoints(post_id)
        print("\n# mcp", flush=True)
        anyio.run(mcp_reads)
        anyio.run(mcp_extended)
        anyio.run(mcp_write_cycle)
        print("\n# cli writes", flush=True)
        cli_write_cycle()
        print("\n# profiles", flush=True)
        second_profile()
    finally:
        try:
            anyio.run(sweep)
        finally:
            shutil.rmtree(HOME, ignore_errors=True)
    print(f"\n{len(failures)} failed" if failures else "\nall live QA checks passed")
    for name in failures:
        print(f"  - {name}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
