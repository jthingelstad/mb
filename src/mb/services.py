"""Shared domain operations for CLI and MCP, independent of presentation and transport."""

import json
import re
import secrets
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from mb.api import MicroblogClient
from mb.domain import _build_thread, _classify_item, _extract_author_username
from mb.formatters import strip_html
from mb.state import LEGACY_CURSOR, CheckpointReviewRequired, StateConflict, StateStore


class AuthenticationUnavailable(RuntimeError):
    """No credential was configured; never carries a credential value."""


def failure(message: str, code: int = 400, **extra) -> dict:
    return {"ok": False, "error": message, "code": code, **extra}


def preview_post(
    content: str,
    title: str | None = None,
    draft: bool = False,
    photo_url: str | None = None,
    photo_alt: str | None = None,
    categories: list[str] | None = None,
) -> dict:
    """Pure validation used by both publishing interfaces."""
    if not content.strip():
        return failure("Content is empty")
    if photo_url and (
        urlparse(photo_url).scheme not in {"http", "https"} or not urlparse(photo_url).netloc
    ):
        return failure("Photo URL must use http or https")
    if photo_alt is not None and not photo_url:
        return failure("Photo alt text requires a photo URL")
    return {
        "ok": True,
        "data": {
            "content": content,
            "title": title,
            "draft": draft,
            "photo_url": photo_url,
            "photo_alt": photo_alt,
            "categories": categories or [],
            "char_count": len(content),
        },
    }


def create_post(client: MicroblogClient, **arguments) -> dict:
    """Validate the same publish payload for both CLI and MCP."""
    preview = preview_post(**arguments)
    return client.micropub_create(**arguments) if preview["ok"] else preview


def reply_content(client: MicroblogClient, post_id: int, content: str) -> dict:
    """Read the recipient and add the mention Micro.blog expects; never writes."""
    if not content.strip():
        return failure("Content is empty", outcome="not_applied")
    result = client.get_conversation(post_id)
    if not result["ok"]:
        return {**result, "outcome": "not_applied"}
    username = next(
        (
            _extract_author_username(i.get("author", {}))
            for i in result["data"].get("items", [])
            if str(i.get("id")) == str(post_id)
        ),
        None,
    )
    if not username:
        return failure("Post not found in conversation", 404, outcome="not_applied")
    if not content.lstrip().startswith(f"@{username}"):
        content = f"@{username} {content}"
    return {"ok": True, "data": {"content": content}}


def source_hash(data: dict) -> str:
    return StateStore.fingerprint(
        "post_source", {"type": data.get("type"), "properties": data.get("properties", {})}
    )


def read_source(client: MicroblogClient, url: str) -> dict:
    result = client.micropub_get(url)
    if result["ok"]:
        result = {**result, "data": {**result["data"], "source_hash": source_hash(result["data"])}}
    return result


def read_conversation(client: MicroblogClient, identifier: str) -> dict:
    if identifier.isdigit():
        result = client.get_conversation(int(identifier))
        coverage = "native-thread"
    elif identifier.startswith(("https://", "http://")):
        result = client.get_url_conversation(identifier)
        coverage = "url-conversation"
    else:
        return failure("Use a numeric Micro.blog ID or full public post URL")
    if not result["ok"]:
        return result
    try:
        items = [normalize_post(i) for i in _build_thread(result["data"]["items"])]
    except (KeyError, TypeError, ValueError, AttributeError):
        return failure("Invalid conversation response", 502)
    return {
        "ok": True,
        "data": {
            **result["data"],
            "items": items,
            "coverage": coverage,
            "scope": "account",
        },
    }


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


@dataclass(frozen=True)
class _ClaimedWrite:
    """A write whose operation ID is durably claimed and must now be finished."""

    scope: str
    identity: dict
    arguments: dict
    target: str | None
    media: tuple[dict, bytes] | None
    reply_content: str | None


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
        media_root: Path | None = None,
    ):
        self.client = client
        self.profile = profile
        self.requested_blog = blog
        self.consumer = consumer
        self.state = StateStore(state_path)
        self.read_only = read_only
        self.media_root = media_root
        self._identity: Identity | None = None
        self._blog_urls: tuple[str, ...] = ()
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
                matches = [
                    d
                    for d in destinations
                    if requested == d.get("name")
                    or requested.rstrip("/")
                    in {u.rstrip("/") for u in self._destination_urls(d, destinations)}
                ]
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
            endpoint = configuration["data"].get("media-endpoint")
            if endpoint:
                parsed = urlparse(endpoint)
                trusted = urlparse(self.client.base_url)
                if (
                    parsed.scheme != trusted.scheme
                    or parsed.netloc != trusted.netloc
                    or parsed.username
                    or parsed.fragment
                ):
                    return failure(
                        "Configured media endpoint must use the authenticated Micro.blog origin",
                        502,
                    )
                self.client.media_endpoint = endpoint
            self._blog_urls = self._destination_urls(matches[0], destinations)
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

    @staticmethod
    def _destination_urls(destination: dict, destinations: list[dict]) -> tuple[str, ...]:
        # Micro.blog's UID remains native when published URLs use a custom domain.
        # Only trust an unambiguous hostname supplied by the selected destination.
        blog = destination["uid"]
        aliases = [blog]
        name = destination.get("name", "")
        if (
            urlparse(blog).path in {"", "/"}
            and isinstance(name, str)
            and re.fullmatch(r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,63}", name)
        ):
            competing = [
                d
                for d in destinations
                if d is not destination
                and (
                    str(d.get("name", "")).lower() == name.lower()
                    or urlparse(d.get("uid", "")).netloc.lower() == name.lower()
                )
            ]
            if not competing:
                aliases.append(f"https://{name.lower()}/")
        return tuple(dict.fromkeys(aliases))

    def _scope(self, workflow: str | None = None) -> str:
        assert self._identity is not None
        values = [self._identity.username, self._identity.blog]
        if workflow:
            values += [self.consumer, workflow]
        return json.dumps(values)

    def _reply_scope(self) -> str:
        assert self._identity is not None
        return json.dumps([self._identity.username, "native-replies"])

    def _owns_url(self, target: str) -> bool:
        parsed = urlparse(target)
        path = unquote(parsed.path)
        # Reject encoded delimiters and dot segments before HTTP normalization can
        # redirect a path-scoped destination into a sibling blog.
        if path != unquote(path) or "\\" in path or any(p in {".", ".."} for p in path.split("/")):
            return False
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            return False
        return any(
            parsed.netloc.lower() == urlparse(blog).netloc.lower()
            and path.startswith(urlparse(blog).path.rstrip("/") + "/")
            for blog in self._blog_urls
        )

    @staticmethod
    def _feed_items(result: dict) -> dict:
        """Validate native IDs without assigning chronological meaning to them."""
        if not result["ok"]:
            return result
        try:
            items = result["data"]["items"]
            if not isinstance(items, list) or any(
                not isinstance(i, dict)
                or not re.fullmatch(r"[0-9]{1,20}", str(i.get("id", "")))
                or int(i["id"]) <= 0
                for i in items
            ):
                raise ValueError
            ids = [str(int(i["id"])) for i in items]
            if len(ids) != len(set(ids)):
                raise ValueError
            return {"ok": True, "data": {"items": [{**i, "id": key} for i, key in zip(items, ids)]}}
        except (KeyError, TypeError, ValueError):
            return failure("Invalid timeline page; checkpoint was not advanced", 502)

    def timeline(
        self, count: int = 20, since: str | None = None, before: str | None = None
    ) -> dict:
        result = self.client.get_timeline(
            count=count + 1,
            since_id=int(since) if since else None,
            before_id=int(before) if before else None,
        )
        # Micro.blog's feed order determines pagination. IDs are unique, but
        # imported/backdated posts need not appear in numeric ID order.
        result = self._feed_items(result)
        if not result["ok"]:
            return result
        items = result["data"]["items"]
        if any(
            (before is not None and int(i["id"]) == int(before))
            or (since is not None and int(i["id"]) == int(since))
            for i in items
        ):
            return failure("Upstream timeline page repeated an exclusive boundary", 502)
        selected = items[:count]
        more = len(items) > count
        if selected and not more:
            probe = self.client.get_timeline(
                count=1, since_id=int(since) if since else None, before_id=int(selected[-1]["id"])
            )
            probe = self._feed_items(probe)
            if not probe["ok"]:
                return probe
            if any(
                int(i["id"]) in {int(item["id"]) for item in selected}
                or (since is not None and int(i["id"]) == int(since))
                for i in probe["data"]["items"]
            ):
                return failure("Upstream timeline pagination repeated an item or boundary", 502)
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
        record = self.state.cursor_record(scope)
        checkpoint, revision = record["value"], record["revision"]
        review_required = record["scheme"] == LEGACY_CURSOR
        anchor = (
            str(int(checkpoint))
            if isinstance(checkpoint, str)
            and re.fullmatch(r"[0-9]{1,20}", checkpoint)
            and int(checkpoint) > 0
            else None
        )
        previous = self._windows.get(cursor or "")
        if cursor and (
            not previous
            or previous["scope"] != scope
            or previous["revision"] != revision
            or previous["checkpoint"] != checkpoint
            or previous["scheme"] != record["scheme"]
        ):
            return failure("Cursor expired or checkpoint changed; read a fresh window", 409)
        if previous:
            window = dict(previous)
        else:
            result = (
                self.client.get_mentions()
                if workflow == "inbox"
                else self.client.get_timeline(count=count, since_id=int(anchor) if anchor else None)
            )
            result = self._feed_items(result)
            if not result["ok"]:
                return result
            raw = result["data"]["items"]
            fence = next((index for index, i in enumerate(raw) if i["id"] == anchor), None)
            items = raw[:fence] if fence is not None else raw
            complete = (
                (record["scheme"] is None or fence is not None)
                if workflow == "inbox"
                else not raw
                or fence is not None
                or (workflow == "heartbeat" and record["scheme"] is None)
            )
            window = {
                "scope": scope,
                "revision": revision,
                "checkpoint": checkpoint,
                "scheme": record["scheme"],
                "items": items,
                "latest": items[0]["id"] if items else anchor,
                "complete": complete,
                "before": raw[-1]["id"] if raw else None,
                "seen": frozenset(i["id"] for i in raw),
            }
        selected = window["items"][:count]
        remaining = window["items"][count:]
        if workflow != "inbox" and not remaining and not window["complete"]:
            before = window["before"]
            page = self.client.get_timeline(
                count=count,
                since_id=int(anchor) if anchor else None,
                before_id=int(before) if before else None,
            )
            page = self._feed_items(page)
            if not page["ok"]:
                return page
            raw = page["data"]["items"]
            ids = frozenset(i["id"] for i in raw)
            if ids & window["seen"]:
                return failure(
                    "Upstream pagination repeated an item; checkpoint was not advanced", 502
                )
            fence = next((index for index, i in enumerate(raw) if i["id"] == anchor), None)
            remaining = raw[:fence] if fence is not None else raw
            window["before"] = raw[-1]["id"] if raw else before
            window["seen"] = window["seen"] | ids
            # Native exhaustion or an exact anchor proves the bounded read is consumed.
            window["complete"] = not raw or fence is not None
        next_cursor = None
        if remaining:
            next_cursor = secrets.token_urlsafe(24)
            self._windows[next_cursor] = {**window, "items": remaining}
        receipt = None
        if not remaining and window["complete"] and window["latest"] and not review_required:
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
                "mode": "checkpoint-review-required"
                if review_required
                else "bootstrap"
                if record["scheme"] is None
                else "since-checkpoint",
                "checkpoint_status": record["scheme"] or "empty",
                "checkpoint_review_required": review_required,
                "checkpoint": checkpoint,
                "revision": revision,
                "items": entries,
                "returned_count": len(entries),
                "truncated": bool(remaining),
                "coverage_complete": window["complete"] and not remaining and not review_required,
                "coverage": "legacy-checkpoint-review-required"
                if review_required
                else "recent-mentions-window"
                if workflow == "inbox"
                else "bootstrap-recent-baseline"
                if workflow == "heartbeat" and record["scheme"] is None
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
                    record["scope"], record["value"], record["revision"], native=True
                ),
            }
        except CheckpointReviewRequired as exc:
            return failure(str(exc), 409, reason="checkpoint_review_required")
        except StateConflict as exc:
            return failure(str(exc), 409)

    def conversation(self, post_id: str) -> dict:
        return read_conversation(self.client, post_id)

    @staticmethod
    def _bounded_read(result: dict, count: int, coverage: str) -> dict:
        if not result["ok"]:
            return result
        items = result["data"]["items"]
        return {
            "ok": True,
            "data": {
                **result["data"],
                "items": [normalize_post(i) for i in items[:count]],
                "returned_count": len(items[:count]),
                "truncated": len(items) > count,
                "coverage": coverage,
                "coverage_complete": False,
                "scope": "account",
            },
        }

    def discover(self, count: int = 20, collection: str | None = None) -> dict:
        from mb.discover_collections import get_discover_collection

        if collection and not get_discover_collection(collection):
            return failure("Unknown discover collection; read mb://discover-collections")
        return self._bounded_read(
            self.client.get_discover(collection, count=count + 1), count, "recent-discover-window"
        )

    def profile_get(self, username: str, count: int = 10) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", username):
            return failure("Use a Micro.blog username")
        return self._bounded_read(
            self.client.get_user(username, count=count + 1), count, "recent-user-posts"
        )

    def replies(self, count: int = 10) -> dict:
        return self._bounded_read(
            self.client.get_replies(count=count + 1), count, "recent-account-replies"
        )

    def blog_search(self, query: str, count: int = 20, category: str | None = None) -> dict:
        if not query.strip():
            return failure("Search query is empty")
        identity = self.identity()
        if not identity["ok"]:
            return identity
        result = self.client.search_blog(identity["data"]["username"], query, category)
        result = self._bounded_read(result, count, "server-filtered-source-window")
        if result["ok"]:
            result["data"]["scope"] = "selected-blog"
            result["data"]["identity"] = identity["data"]
        return result

    def blog_categories(self) -> dict:
        identity = self.identity()
        if not identity["ok"]:
            return identity
        result = self.client.micropub_get_categories()
        if result["ok"]:
            result["data"].update(scope="selected-blog", identity=identity["data"])
        return result

    def own_posts(self, count: int = 10, drafts: bool = False, category: str | None = None) -> dict:
        identity = self.identity()
        if not identity["ok"]:
            return identity
        result = self.client.micropub_list(drafts=drafts)
        if not result["ok"]:
            return result
        items = self.client._normalize_micropub_items(
            result["data"].get("items", []), owner=identity["data"]["username"]
        )
        if category:
            items = [i for i in items if category in i.get("tags", [])]
        return {
            "ok": True,
            "data": {
                "items": [normalize_post(i) for i in items[:count]],
                "truncated": len(items) > count,
                "coverage": "recent-source-window",
                "coverage_complete": False,
                "scope": "selected-blog",
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
        identity = self.identity()
        if not identity["ok"]:
            return identity
        resolved = self.resolve_url(identifier)
        if resolved["ok"] and not self._owns_url(resolved["data"]["url"]):
            return failure("Post must belong to this server's selected blog", 403)
        return read_source(self.client, resolved["data"]["url"]) if resolved["ok"] else resolved

    def preview(self, **arguments) -> dict:
        identity = self.identity()
        if not identity["ok"]:
            return identity
        result = preview_post(**arguments)
        if result["ok"]:
            result["data"]["identity"] = identity["data"]
            result["data"]["dry_run"] = True
        return result

    def media_preview(self, file: str, alt: str) -> dict:
        from mb.media import ImageInputError, load_image

        if not alt.strip():
            return failure("Provide descriptive alt text for the image")
        identity = self.identity()
        if not identity["ok"]:
            return identity
        try:
            metadata, _ = load_image(self.media_root, file)
        except ImageInputError as exc:
            return failure(str(exc))
        return {
            "ok": True,
            "data": {**metadata, "alt": alt, "identity": identity["data"], "dry_run": True},
        }

    def write(self, action: str, operation_id: str, arguments: dict) -> dict:
        try:
            prepared = self._prepare_write(action, operation_id, arguments)
        except Exception:
            # Nothing was claimed or sent, so the ID stays unused and needs no recovery.
            # Never expose exception details.
            return failure(
                "Write was not started; inspect configuration or local state",
                503,
                outcome="not_applied",
            )
        if isinstance(prepared, dict):
            return prepared
        return self._dispatch_claimed(action, operation_id, prepared)

    def _prepare_write(
        self, action: str, operation_id: str, arguments: dict
    ) -> "dict | _ClaimedWrite":
        """Validate, read and claim. Every failure here leaves nothing to recover."""
        if self.read_only:
            return failure("Server is read-only", 403, outcome="not_applied")
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", operation_id):
            return failure(
                "Writes require a caller-stable --operation-id (operation_id in MCP): "
                "1-128 letters, digits or _.:-. Save the ID and exact arguments before calling; "
                "reuse both on retries. Never generate a fresh ID to retry an uncertain write.",
                outcome="not_applied",
            )
        if action == "media_upload" and not re.fullmatch(
            r"[a-f0-9]{64}", arguments.get("sha256", "")
        ):
            return failure("Upload requires the sha256 from a reviewed media_preview")
        if action == "post_publish" and not re.fullmatch(
            r"[a-f0-9]{64}", arguments.get("source_hash", "")
        ):
            return failure("Publish requires the source_hash from a reviewed post_get")
        identity = self.identity()
        if not identity["ok"]:
            return identity
        if action == "post_create":
            preview = preview_post(**arguments)
            if not preview["ok"]:
                return preview
            arguments = {k: v for k, v in preview["data"].items() if k != "char_count"}
        if action == "post_edit" and not any(
            arguments.get(k) is not None for k in ("content", "title", "categories")
        ):
            return failure("Nothing to update")
        if (
            action == "post_edit"
            and arguments.get("content") is not None
            and not arguments["content"].strip()
        ):
            # Title- and category-only edits omit content; an empty body is never intended.
            return failure("Content is empty", outcome="not_applied")
        if action == "post_reply" and not arguments["content"].strip():
            return failure("Content is empty")
        scope = self._reply_scope() if action == "post_reply" else self._scope()
        fingerprint = self.state.fingerprint(action, arguments)
        try:
            previous = self.state.lookup(scope, operation_id, fingerprint)
        except StateConflict as exc:
            return failure(str(exc), 409)
        if previous is not None:
            return previous
        media = None
        if action == "media_upload":
            from mb.media import ImageInputError, load_image

            if not arguments["alt"].strip():
                return failure("Provide descriptive alt text for the image")
            try:
                metadata, content = load_image(self.media_root, arguments["file"])
            except ImageInputError as exc:
                return failure(str(exc), outcome="not_applied")
            if metadata["sha256"] != arguments["sha256"]:
                return failure(
                    "Image changed since preview; review it again", 409, outcome="not_applied"
                )
            media = metadata, content
        target = None
        if action in {"post_edit", "post_delete", "post_publish"}:
            resolved = self.resolve_url(arguments["identifier"])
            if not resolved["ok"]:
                return resolved
            target = resolved["data"]["url"]
            if not self._owns_url(target):
                return failure("Post must belong to this server's selected blog", 403)
            source = self.client.micropub_get(target)
            if not source["ok"]:
                return source
            if action == "post_publish":
                if source["data"].get("properties", {}).get("post-status") != ["draft"]:
                    return failure("Post is not an existing draft", 409, outcome="not_applied")
                if source_hash(source["data"]) != arguments["source_hash"]:
                    return failure(
                        "Draft changed since review; read and approve its current source",
                        409,
                        outcome="not_applied",
                    )
        reply = None
        if action == "post_reply":
            # The recipient read happens before the claim so a failed read never
            # consumes the operation ID; only the reply itself runs after it.
            reply = reply_content(self.client, int(arguments["post_id"]), arguments["content"])
            if not reply["ok"]:
                return reply
        try:
            previous = self.state.claim(scope, operation_id, fingerprint)
        except StateConflict as exc:
            return failure(str(exc), 409)
        if previous is not None:
            return previous
        return _ClaimedWrite(
            scope=scope,
            identity=identity["data"],
            arguments=arguments,
            target=target,
            media=media,
            reply_content=reply["data"]["content"] if reply else None,
        )

    def _send(self, action: str, claimed: "_ClaimedWrite") -> dict:
        arguments, target = claimed.arguments, claimed.target
        if action == "media_upload":
            assert claimed.media is not None
            metadata, content = claimed.media
            result = self.client.micropub_upload_bytes(
                metadata["filename"], content, content_type=metadata["mime_type"]
            )
            if result["ok"]:
                result = {
                    **result,
                    "data": {
                        **result["data"],
                        **metadata,
                        "alt": arguments["alt"],
                        "identity": claimed.identity,
                    },
                }
            return result
        if action == "post_create":
            return create_post(self.client, **arguments)
        if action == "post_reply":
            assert claimed.reply_content is not None
            return self.client.post_reply(int(arguments["post_id"]), claimed.reply_content)
        if action == "post_edit":
            assert target is not None
            return self.client.micropub_update(
                target, **{k: v for k, v in arguments.items() if k != "identifier"}
            )
        if action == "post_publish":
            assert target is not None
            return self.client.micropub_publish(target)
        if action == "post_delete":
            assert target is not None
            return self.client.micropub_delete(target)
        return failure("Unknown write operation")

    def _dispatch_claimed(self, action: str, operation_id: str, claimed: "_ClaimedWrite") -> dict:
        scope, target = claimed.scope, claimed.target
        try:
            result = self._send(action, claimed)
        except BaseException as exc:
            # Interrupts, exits and cancellation must not strand a pending claim that
            # blocks every later write in this scope. The request may have landed.
            unknown = failure(
                "write_outcome_unknown", 409, outcome="unknown", operation_id=operation_id
            )
            try:
                self.state.finish(scope, operation_id, unknown)
            except Exception:
                if isinstance(exc, Exception):
                    raise
            if not isinstance(exc, Exception):
                raise
            return unknown
        if result["ok"] and target is not None:
            result = {**result, "data": {**result.get("data", {}), "url": target}}
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
        token = getattr(self.client, "token", None)
        stored["data"] = {
            k: str(v)
            for k, v in result.get("data", {}).items()
            if k in {"url", "id", "sha256", "upload_sha256", "mime_type", "upload_status"}
            and isinstance(v, (str, int))
            and not isinstance(v, bool)
            and not (isinstance(token, str) and token and token in str(v))
        }
        if result.get("data", {}).get("processing_pending") is not None:
            stored["data"]["processing_pending"] = result["data"]["processing_pending"]
        self.state.finish(scope, operation_id, stored)
        return result

    def latest_operation_status(self, scope: str | None = None) -> dict:
        identity = self.identity()
        if not identity["ok"]:
            return identity
        if scope not in {None, "blog", "reply"}:
            return failure("Use blog or reply receipt scope")
        receipts = [
            (receipt[0], {**receipt[1], "receipt_scope": name})
            for name, key in {"blog": self._scope(), "reply": self._reply_scope()}.items()
            if (scope is None or name == scope) and (receipt := self.state.latest_operation(key))
        ]
        return (
            max(receipts, key=lambda r: r[0])[1]
            if receipts
            else failure("Operation not found", 404)
        )

    def operation_status(self, operation_id: str, scope: str | None = None) -> dict:
        identity = self.identity()
        if not identity["ok"]:
            return identity
        if scope not in {None, "blog", "reply"}:
            return failure("Use blog or reply receipt scope")
        receipts = {
            name: self.state.operation(key, operation_id)
            for name, key in {"blog": self._scope(), "reply": self._reply_scope()}.items()
            if scope is None or name == scope
        }
        found = [r for r in receipts.values() if r is not None]
        if len(found) > 1:
            return failure(
                "Operation ID exists in blog and reply scopes; select a scope",
                409,
                reason="ambiguous_operation",
                operation_id=operation_id,
            )
        return found[0] if found else failure("Operation not found", 404)

    def resolve_operation(
        self,
        operation_id: str,
        outcome: str,
        scope: str | None = None,
        note: str | None = None,
        resolved_by: str = "cli",
    ) -> dict:
        """Record a human's checked answer for a pending or unknown write; never dispatches."""
        if self.read_only:
            return failure("Server is read-only", 403)
        if outcome not in {"applied", "not_applied"}:
            return failure("Resolve with applied or not_applied")
        identity = self.identity()
        if not identity["ok"]:
            return identity
        if scope not in {None, "blog", "reply"}:
            return failure("Use blog or reply receipt scope")
        keys = {
            name: key
            for name, key in {"blog": self._scope(), "reply": self._reply_scope()}.items()
            if (scope is None or name == scope) and self.state.operation(key, operation_id)
        }
        if len(keys) > 1:
            return failure(
                "Operation ID exists in blog and reply scopes; select a scope",
                409,
                reason="ambiguous_operation",
                operation_id=operation_id,
            )
        if not keys:
            return failure("Operation not found", 404)
        name, key = next(iter(keys.items()))
        try:
            receipt = self.state.resolve(
                key,
                operation_id,
                outcome,
                resolved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                resolved_by=resolved_by,
                note=note,
            )
        except StateConflict as exc:
            current = self.state.operation(key, operation_id) or {}
            return failure(
                str(exc),
                409,
                reason="not_resolvable",
                operation_id=operation_id,
                outcome=current.get("outcome"),
                receipt_scope=name,
            )
        if receipt is None:
            return failure("Operation not found", 404)
        resolution = receipt["resolution"]
        return {
            "ok": True,
            "operation_id": operation_id,
            "outcome": outcome,
            "data": {
                "kind": "operation_resolution",
                "operation_id": operation_id,
                "receipt_scope": name,
                "outcome": outcome,
                "previous_status": resolution["previous_status"],
                "resolved_at": resolution["resolved_at"],
                "resolved_by": resolution["resolved_by"],
                "note": note,
            },
        }
