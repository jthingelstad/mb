"""Versioned response shapes: compact MCP results and their published JSON Schemas.

Stability policy for SCHEMA_VERSION: adding a field, or a new optional value for a
field, keeps the version. Removing, renaming or retyping a field bumps it. Verbose
results carry extra upstream fields that are not covered by the schema.
"""

import re
from html import unescape
from typing import Any

SCHEMA_VERSION = 1
EXCERPT_CHARS = 500

_IMAGE = re.compile(r"""<img\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_LINK = re.compile(r"""<a\b[^>]*?\bhref\s*=\s*["'](https?://[^"']+)["']""", re.IGNORECASE)
_FEED_NOISE = ("_microblog", "version", "title", "home_page_url", "feed_url", "author")
_PROFILE_FIELDS = (
    "bio",
    "pronouns",
    "is_following",
    "is_you",
    "following_count",
    "discover_count",
)


def versioned(result: dict) -> dict:
    """Put the schema version first in every envelope."""
    return {"schema_version": SCHEMA_VERSION, **result}


def _text(item: dict) -> str:
    return (item.get("content_text") or "").strip()


def compact_post(item: dict) -> dict:
    """One feed post: text only, a flat author, links and images listed, no upstream blobs."""
    author = item.get("author") or {}
    flags = item.get("_microblog") or {}
    html = item.get("content_html") or ""
    post: dict[str, Any] = {
        "id": item.get("id", ""),
        "url": item.get("url"),
        "author_username": item.get("author_username"),
        "author_name": author.get("name") if isinstance(author, dict) else None,
        "date_published": item.get("date_published"),
        "content_text": _text(item),
    }
    if isinstance(html, str):
        for field, pattern in (("links", _LINK), ("images", _IMAGE)):
            found = list(dict.fromkeys(unescape(u) for u in pattern.findall(html)))
            if found:
                post[field] = found
    for flag in ("is_conversation", "is_mention"):
        if flags.get(flag):
            post[flag] = True
    return post


def compact_source_post(item: dict) -> dict:
    """One post from the selected blog: an excerpt; read post_get for the full source."""
    text = _text(item)
    return {
        "id": item.get("id", ""),
        "url": item.get("url"),
        "title": item.get("title") or None,
        "date_published": item.get("date_published"),
        "status": (item.get("_microblog") or {}).get("post_status"),
        "tags": item.get("tags") or [],
        "content_text": text[:EXCERPT_CHARS],
        "content_truncated": len(text) > EXCERPT_CHARS,
    }


def _compact_entry(entry: dict) -> dict:
    """An inbox entry keeps its classification and compacts the mention."""
    if "item" not in entry:
        return compact_post(entry)
    return {**entry, "item": compact_post(entry["item"])}


def _without(data: dict, *keys: str) -> dict:
    return {k: v for k, v in data.items() if k not in keys}


def compact(tool: str, result: dict) -> dict:
    """Reduce a successful read to its schema fields. Failures and writes pass through."""
    data = result.get("data")
    if not result.get("ok") or not isinstance(data, dict):
        return result
    if tool in {"heartbeat", "inbox", "catchup"}:
        data = _without(data, "identity", "checkpoint", "revision")
        data["items"] = [_compact_entry(i) for i in data.get("items", [])]
        if "mentions" in data:
            data["mentions"] = [compact_post(i) for i in data["mentions"]]
    elif tool in {"timeline", "conversation", "discover", "replies", "profile_get"}:
        profile = None
        if tool == "profile_get":
            author = data.get("author") or {}
            extra = data.get("_microblog") or {}
            profile = {
                "username": extra.get("username"),
                "name": author.get("name"),
                "url": author.get("url"),
                "avatar": author.get("avatar"),
                **{k: extra.get(k) for k in _PROFILE_FIELDS},
            }
        data = _without(data, *_FEED_NOISE)
        data["items"] = [compact_post(i) for i in data.get("items", [])]
        if profile is not None:
            data["profile"] = profile
    elif tool in {"blog_posts", "blog_search"}:
        data = _without(data, "identity")
        data["items"] = [compact_source_post(i) for i in data.get("items", [])]
    elif tool == "blog_categories":
        data = _without(data, "identity", "microblog-categories")
    else:
        return result
    return {**result, "data": data}


# JSON Schemas ------------------------------------------------------------------------

_STR = {"type": "string"}
_NSTR = {"type": ["string", "null"]}
_BOOL = {"type": "boolean"}
_INT = {"type": "integer"}


def _obj(required: dict[str, Any], optional: dict[str, Any] | None = None) -> dict:
    return {
        "type": "object",
        "properties": {**required, **(optional or {})},
        "required": list(required),
        "additionalProperties": True,
    }


IDENTITY = _obj(
    {"profile": _STR, "username": _STR, "blog": _STR, "consumer": _STR, "read_only": _BOOL}
)
POST = _obj(
    {"id": _STR, "author_username": _NSTR, "content_text": _STR},
    {
        "url": _NSTR,
        "date_published": _NSTR,
        "author_name": _NSTR,
        "links": {"type": "array", "items": _STR},
        "images": {"type": "array", "items": _STR},
        "is_conversation": _BOOL,
        "is_mention": _BOOL,
        "content_html": _STR,
    },
)
SOURCE_POST = _obj(
    {"id": _STR, "content_text": _STR},
    {
        "url": _NSTR,
        "date_published": _NSTR,
        "title": _NSTR,
        "status": _NSTR,
        "tags": {"type": "array", "items": _STR},
        "content_truncated": _BOOL,
    },
)
INBOX_ENTRY = _obj(
    {"reason": _STR, "thread_has_self_post": _BOOL, "thread_count": _INT, "item": POST},
    {"conversation_error": _STR},
)


def _items(item: dict) -> dict:
    return {"type": "array", "items": item}


_PAGE = {"returned_count": _INT, "truncated": _BOOL}
_COVERAGE = {"coverage": _STR, "coverage_complete": _BOOL, "scope": _STR}
_ATTENTION = {
    "kind": {"enum": ["heartbeat", "inbox", "catchup"]},
    "mode": _STR,
    "checkpoint_status": _STR,
    "checkpoint_review_required": _BOOL,
    **_PAGE,
    "coverage": _STR,
    "coverage_complete": _BOOL,
    "next_cursor": _NSTR,
    "ack_receipt": _NSTR,
    "advanced": _BOOL,
}
_REBASELINE = {"anchor_missing": _BOOL, "rebaselined": _BOOL}
_FEED = _obj({"items": _items(POST), **_PAGE, **_COVERAGE})
_SOURCE_LIST = _obj({"items": _items(SOURCE_POST), **_PAGE, **_COVERAGE})
_WRITE = _obj({}, {"url": _STR, "id": _STR})

DATA_SCHEMAS: dict[str, dict] = {
    "identity": IDENTITY,
    "heartbeat": _obj(
        {**_ATTENTION, "items": _items(POST), "mentions": _items(POST)},
        {"mentions_truncated": _BOOL, "mentions_coverage": _STR},
    ),
    "inbox": _obj({**_ATTENTION, "items": _items(INBOX_ENTRY)}, _REBASELINE),
    "catchup": _obj({**_ATTENTION, "items": _items(POST)}),
    "timeline": _obj({"items": _items(POST), **_PAGE, "next_cursor": _NSTR}),
    "conversation": _obj({"items": _items(POST), "coverage": _STR, "scope": _STR}),
    "discover": _FEED,
    "replies": _FEED,
    "profile_get": _obj(
        {"items": _items(POST), **_PAGE, **_COVERAGE},
        {
            "profile": _obj(
                {"username": _NSTR},
                {
                    "name": _NSTR,
                    "url": _NSTR,
                    "avatar": _NSTR,
                    "bio": _NSTR,
                    "pronouns": _NSTR,
                    "is_following": {"type": ["boolean", "null"]},
                    "is_you": {"type": ["boolean", "null"]},
                    "following_count": {"type": ["integer", "null"]},
                    "discover_count": {"type": ["integer", "null"]},
                },
            )
        },
    ),
    "blog_posts": _SOURCE_LIST,
    "blog_search": _SOURCE_LIST,
    "blog_categories": _obj({"categories": _items(_STR), "scope": _STR}),
    "post_get": _obj(
        {
            "type": {"type": ["string", "array"], "items": _STR},
            "properties": {"type": "object"},
            "source_hash": _STR,
        }
    ),
    "post_preview": _obj(
        {
            "content": _STR,
            "title": _NSTR,
            "draft": _BOOL,
            "photo_url": _NSTR,
            "photo_alt": _NSTR,
            "categories": _items(_STR),
            "char_count": _INT,
            "identity": IDENTITY,
            "dry_run": {"const": True},
        }
    ),
    "media_preview": _obj(
        {
            "file": _STR,
            "filename": _STR,
            "sha256": _STR,
            "byte_count": _INT,
            "mime_type": _STR,
            "alt": _STR,
            "destination": _STR,
            "identity": IDENTITY,
            "dry_run": {"const": True},
        }
    ),
    "post_create": _WRITE,
    "post_reply": _WRITE,
    "post_edit": _WRITE,
    "post_delete": _WRITE,
    "post_publish": _WRITE,
    "media_upload": _obj(
        {},
        {
            "url": _STR,
            "sha256": _STR,
            "mime_type": _STR,
            "alt": _STR,
            "processing_pending": _BOOL,
        },
    ),
    "checkpoint_ack": _obj(
        {"checkpoint": _STR, "revision": _INT, "already_applied": _BOOL},
        {"rebaselined": _BOOL, "previous_checkpoint": _NSTR},
    ),
    "operation_status": _obj({}, {"url": _STR, "id": _STR}),
}


def output_schema(tool: str) -> dict:
    """The full result envelope for one tool; failures carry error and code instead of data."""
    return {
        "type": "object",
        "properties": {
            "schema_version": {"const": SCHEMA_VERSION},
            "ok": _BOOL,
            "data": DATA_SCHEMAS[tool],
            "error": _STR,
            "code": _INT,
            "reason": _STR,
            "retry_after": {"type": "number"},
            "operation_id": _NSTR,
            "outcome": {"enum": ["applied", "unknown", "not_applied"]},
        },
        "required": ["schema_version", "ok"],
        "additionalProperties": True,
    }
