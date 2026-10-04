"""Shared domain operations for CLI and MCP, independent of presentation and transport."""

import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from mb.api import MicroblogClient
from mb.domain import _build_thread, _classify_item, _extract_author_username
from mb.formatters import strip_html
from mb.state import StateConflict, StateStore


class AuthenticationUnavailable(RuntimeError):
    """No credential was configured; never carries a credential value."""


def failure(message: str, code: int = 400, **extra) -> dict:
    return {"ok": False, "error": message, "code": code, **extra}


def preview_post(
    content: str,
    title: str | None = None,
    draft: bool = False,
    photo_url: str | None = None,
    categories: list[str] | None = None,
) -> dict:
    """Pure validation used by both publishing interfaces."""
    if not content.strip():
        return failure("Content is empty")
    if photo_url and (
        urlparse(photo_url).scheme not in {"http", "https"} or not urlparse(photo_url).netloc
    ):
        return failure("Photo URL must use http or https")
    return {
        "ok": True,
        "data": {
            "content": content,
            "title": title,
            "draft": draft,
            "photo_url": photo_url,
            "categories": categories or [],
            "char_count": len(content),
        },
    }


def create_post(client: MicroblogClient, **arguments) -> dict:
    """Validate the same publish payload for both CLI and MCP."""
    preview = preview_post(**arguments)
    return client.micropub_create(**arguments) if preview["ok"] else preview


def reply_post(client: MicroblogClient, post_id: int, content: str) -> dict:
    """Native reply with the recipient mention expected by Micro.blog."""
    if not content.strip():
        return failure("Content is empty")
    result = client.get_conversation(post_id)
    if not result["ok"]:
        return result
    username = next(
        (
            _extract_author_username(i.get("author", {}))
            for i in result["data"].get("items", [])
            if str(i.get("id")) == str(post_id)
        ),
        None,
    )
    if not username:
        return failure("Post not found in conversation", 404)
    if not content.lstrip().startswith(f"@{username}"):
        content = f"@{username} {content}"
    return client.post_reply(post_id, content)


def normalize_post(item: dict) -> dict:
    content = item.get("content_html") or item.get("content_text") or ""
    if isinstance(content, dict):
        content = content.get("html") or content.get("value") or ""
    return {
        **item,
        "id": str(item.get("id", "")),
        "content_html": content,
        "content_text": strip_html(content),
        "author_username": _extract_author_username(item.get("author", {})),
    }


@dataclass(frozen=True)
class Identity:
    profile: str
    username: str
    blog: str


class MicroblogService:
    """One immutable account/destination; caller supplies a mocked client in tests."""

    def __init__(
        self,
        client: MicroblogClient,
        profile: str,
        blog: str | None,
        consumer: str,
        state_path: Path,
        read_only: bool = False,
    ):
        self.client = client
        self.profile = profile
        self.requested_blog = blog
        self.consumer = consumer
        self.state = StateStore(state_path)
        self.read_only = read_only
        self._identity: Identity | None = None
        self._receipts: dict[str, dict] = {}
        self._windows: dict[str, dict] = {}

    def identity(self) -> dict:
        if self._identity is None:
            account = self.client.verify_token()
            if not account["ok"]:
                return account
            username = account["data"].get("username")
            if not username:
                return failure("Account verification did not return a username", 502)
            configuration = self.client.micropub_get_config()
            if not configuration["ok"]:
                return configuration
            destinations = configuration["data"].get("destination", [])
            requested = self.requested_blog
            if requested:
                matches = [d for d in destinations if requested in {d.get("uid"), d.get("name")}]
                if len(matches) != 1:
                    return failure("Blog must resolve to exactly one available destination", 400)
                blog = matches[0]["uid"]
            else:
                default = account["data"].get("default_site", "")
                blog = f"https://{default}/" if default else ""
                matches = [
                    d for d in destinations if d.get("uid", "").rstrip("/") == blog.rstrip("/")
                ]
                if not matches:
                    if len(destinations) != 1:
                        return failure("Choose an explicit --blog destination", 400)
                    matches = destinations
                blog = matches[0]["uid"]
            self._identity = Identity(self.profile, username, blog)
            self.client.default_destination = blog
        return {
            "ok": True,
            "data": {
                "profile": self._identity.profile,
                "username": self._identity.username,
                "blog": self._identity.blog,
                "consumer": self.consumer,
                "read_only": self.read_only,
            },
        }

    def _scope(self, workflow: str | None = None) -> str:
        assert self._identity is not None
        values = [self._identity.username, self._identity.blog]
        if workflow:
            values += [self.consumer, workflow]
        return json.dumps(values)

    def timeline(
        self, count: int = 20, since: str | None = None, before: str | None = None
    ) -> dict:
        result = self.client.get_timeline(
            count=count + 1,
            since_id=int(since) if since else None,
            before_id=int(before) if before else None,
        )
        if not result["ok"]:
            return result
        items = result["data"].get("items", [])
        selected = items[:count]
        more = len(items) > count
        if selected and not more:
            probe = self.client.get_timeline(
                count=1, since_id=int(since) if since else None, before_id=int(selected[-1]["id"])
            )
            if not probe["ok"]:
                return probe
            more = bool(probe["data"].get("items"))
        return {
            "ok": True,
            "data": {
                "items": [normalize_post(i) for i in selected],
                "returned_count": len(selected),
                "truncated": more,
                "next_cursor": str(selected[-1]["id"]) if more and selected else None,
            },
        }

    def attention(self, workflow: str, count: int = 10, cursor: str | None = None) -> dict:
        identity = self.identity()
        if not identity["ok"]:
            return identity
        scope = self._scope(workflow)
        checkpoint, revision = self.state.cursor(scope)
        previous = self._windows.get(cursor or "")
        if cursor and (
            not previous or previous["scope"] != scope or previous["revision"] != revision
        ):
            return failure("Cursor expired or checkpoint changed; read a fresh window", 409)
        if previous:
            window = dict(previous)
        else:
            result = (
                self.client.get_mentions()
                if workflow == "inbox"
                else self.client.get_timeline(
                    count=count, since_id=int(checkpoint) if checkpoint else None
                )
            )
            if not result["ok"]:
                return result
            raw = result["data"].get("items", [])
            items = sorted(
                [i for i in raw if not checkpoint or int(i["id"]) > int(checkpoint)],
                key=lambda i: int(i["id"]),
                reverse=True,
            )
            complete = (
                (
                    checkpoint is None
                    or not items
                    or any(int(i["id"]) <= int(checkpoint) for i in raw)
                )
                if workflow == "inbox"
                else not raw or (workflow == "heartbeat" and checkpoint is None)
            )
            window = {
                "scope": scope,
                "revision": revision,
                "checkpoint": checkpoint,
                "items": items,
                "latest": str(items[0]["id"]) if items else checkpoint,
                "complete": complete,
                "before": str(raw[-1]["id"]) if raw else None,
            }
        selected = window["items"][:count]
        remaining = window["items"][count:]
        if workflow != "inbox" and not remaining and not window["complete"]:
            before = window["before"]
            page = self.client.get_timeline(
                count=count,
                since_id=int(checkpoint) if checkpoint else None,
                before_id=int(before) if before else None,
            )
            if not page["ok"]:
                return page
            raw = page["data"].get("items", [])
            if any(int(i["id"]) >= int(before) for i in raw):
                return failure(
                    "Upstream pagination did not move backwards; checkpoint was not advanced", 502
                )
            remaining = [i for i in raw if not checkpoint or int(i["id"]) > int(checkpoint)]
            window["before"] = str(raw[-1]["id"]) if raw else before
            # An empty page or reaching the lower fence proves exhaustion even if upstream caps count.
            window["complete"] = not raw or not remaining
        next_cursor = None
        if remaining:
            next_cursor = secrets.token_urlsafe(24)
            self._windows[next_cursor] = {**window, "items": remaining}
        receipt = None
        if not remaining and window["complete"] and window["latest"]:
            receipt = secrets.token_urlsafe(24)
            self._receipts[receipt] = {
                "scope": scope,
                "value": window["latest"],
                "revision": revision,
            }
        # Bound in-memory attention metadata; evicted handles produce a useful conflict.
        while len(self._windows) > 128:
            self._windows.pop(next(iter(self._windows)))
        while len(self._receipts) > 128:
            self._receipts.pop(next(iter(self._receipts)))
        if workflow == "inbox":
            with ThreadPoolExecutor(max_workers=4) as pool:
                entries = list(
                    pool.map(
                        lambda item: _classify_item(
                            self.client, identity["data"]["username"], normalize_post(item)
                        ),
                        selected,
                    )
                )
        else:
            entries = [normalize_post(i) for i in selected]
        return {
            "ok": True,
            "data": {
                "kind": workflow,
                "identity": identity["data"],
                "mode": "bootstrap" if checkpoint is None else "since-checkpoint",
                "checkpoint": checkpoint,
                "revision": revision,
                "items": entries,
                "returned_count": len(entries),
                "truncated": bool(remaining),
                "coverage_complete": window["complete"] and not remaining,
                "coverage": "recent-mentions-window"
                if workflow == "inbox"
                else "bootstrap-recent-baseline"
                if workflow == "heartbeat" and checkpoint is None
                else "paged-timeline",
                "next_cursor": next_cursor,
                "ack_receipt": receipt,
                "advanced": False,
            },
        }

    def heartbeat(self, count: int = 3, cursor: str | None = None) -> dict:
        result = self.attention("heartbeat", count, cursor)
        if not result["ok"]:
            return result
        mentions = self.client.get_mentions()
        if not mentions["ok"]:
            return mentions
        items = mentions["data"].get("items", [])
        result["data"]["mentions"] = [normalize_post(i) for i in items[:3]]
        result["data"]["mentions_truncated"] = len(items) > 3
        result["data"]["mentions_coverage"] = "recent-window; use inbox for acknowledgement"
        return result

    def acknowledge(self, receipt: str) -> dict:
        if self.read_only:
            return failure("Server is read-only", 403)
        record = self._receipts.get(receipt)
        if not record:
            return failure("Unknown acknowledgement receipt; read a complete window first", 409)
        try:
            return {
                "ok": True,
                "data": self.state.acknowledge(
                    record["scope"], record["value"], record["revision"]
                ),
            }
        except StateConflict as exc:
            return failure(str(exc), 409)

    def conversation(self, post_id: str) -> dict:
        result = self.client.get_conversation(int(post_id))
        if not result["ok"]:
            return result
        return {
            "ok": True,
            "data": {
                "items": [normalize_post(i) for i in _build_thread(result["data"].get("items", []))]
            },
        }

    def own_posts(self, count: int = 10, drafts: bool = False) -> dict:
        identity = self.identity()
        if not identity["ok"]:
            return identity
        result = self.client.micropub_list(drafts=drafts)
        if not result["ok"]:
            return result
        items = self.client._normalize_micropub_items(
            result["data"].get("items", []), owner=identity["data"]["username"]
        )
        return {
            "ok": True,
            "data": {
                "items": [normalize_post(i) for i in items[:count]],
                "truncated": len(items) > count,
                "coverage": "recent-source-window",
                "identity": identity["data"],
            },
        }

    def resolve_url(self, identifier: str) -> dict:
        if identifier.startswith(("https://", "http://")):
            return {"ok": True, "data": {"url": identifier}}
        if identifier.isdigit():
            result = self.client.get_conversation(int(identifier))
            if not result["ok"]:
                return result
            for item in result["data"].get("items", []):
                if str(item.get("id")) == identifier and item.get("url"):
                    return {"ok": True, "data": {"url": item["url"]}}
        return failure("Use a full post URL or numeric Micro.blog ID", 404)

    def post_get(self, identifier: str) -> dict:
        resolved = self.resolve_url(identifier)
        return self.client.micropub_get(resolved["data"]["url"]) if resolved["ok"] else resolved

    def preview(self, **arguments) -> dict:
        identity = self.identity()
        if not identity["ok"]:
            return identity
        result = preview_post(**arguments)
        if result["ok"]:
            result["data"]["identity"] = identity["data"]
            result["data"]["dry_run"] = True
        return result

    def write(self, action: str, operation_id: str, arguments: dict) -> dict:
        if self.read_only:
            return failure("Server is read-only", 403, outcome="not_applied")
        identity = self.identity()
        if not identity["ok"]:
            return identity
        if action == "post_create":
            preview = preview_post(**arguments)
            if not preview["ok"]:
                return preview
        if action == "post_edit" and not any(
            arguments.get(k) is not None for k in ("content", "title", "categories")
        ):
            return failure("Nothing to update")
        if action == "post_reply" and not arguments["content"].strip():
            return failure("Content is empty")
        scope = self._scope()
        fingerprint = self.state.fingerprint(action, arguments)
        try:
            previous = self.state.lookup(scope, operation_id, fingerprint)
        except StateConflict as exc:
            return failure(str(exc), 409)
        if previous is not None:
            return previous
        target = None
        if action in {"post_edit", "post_delete"}:
            resolved = self.resolve_url(arguments["identifier"])
            if not resolved["ok"]:
                return resolved
            target = resolved["data"]["url"]
            blog_url = urlparse(identity["data"]["blog"])
            target_url = urlparse(target)
            if (
                target_url.scheme not in {"http", "https"}
                or target_url.netloc != blog_url.netloc
                or not target_url.path.startswith(blog_url.path.rstrip("/") + "/")
            ):
                return failure("Post must belong to this server's selected blog", 403)
            source = self.client.micropub_get(target)
            if not source["ok"]:
                return source
        try:
            previous = self.state.claim(scope, operation_id, fingerprint)
        except StateConflict as exc:
            return failure(str(exc), 409)
        if previous is not None:
            return previous
        try:
            if action == "post_create":
                result = create_post(self.client, **arguments)
            elif action == "post_reply":
                result = reply_post(self.client, int(arguments["post_id"]), arguments["content"])
            elif action == "post_edit":
                assert target is not None
                result = self.client.micropub_update(
                    target, **{k: v for k, v in arguments.items() if k != "identifier"}
                )
            elif action == "post_delete":
                assert target is not None
                result = self.client.micropub_delete(target)
            else:
                result = failure("Unknown write operation")
        except Exception:
            self.state.finish(
                scope,
                operation_id,
                failure("write_outcome_unknown", 409, outcome="unknown", operation_id=operation_id),
            )
            return failure(
                "write_outcome_unknown", 409, outcome="unknown", operation_id=operation_id
            )
        result = {
            **result,
            "operation_id": operation_id,
            "outcome": result.get(
                "outcome",
                "applied"
                if result["ok"]
                else "unknown"
                if result.get("code", 0) >= 500
                else "not_applied",
            ),
        }
        # Receipts contain only recovery metadata, never post bodies or token responses.
        stored = {
            k: v
            for k, v in result.items()
            if k in {"ok", "code", "retry_after", "operation_id", "outcome"}
        }
        if not result["ok"]:
            stored["error"] = (
                "write_outcome_unknown" if result["outcome"] == "unknown" else "write_failed"
            )
        stored["data"] = {k: v for k, v in result.get("data", {}).items() if k in {"url", "id"}}
        self.state.finish(scope, operation_id, stored)
        return result

    def operation_status(self, operation_id: str) -> dict:
        identity = self.identity()
        if not identity["ok"]:
            return identity
        result = self.state.operation(self._scope(), operation_id)
        return result if result is not None else failure("Operation not found", 404)
