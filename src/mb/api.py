"""HTTP client for micro.blog. Accepts base_url override for testing."""

from urllib.parse import urlparse

import httpx

DEFAULT_BASE_URL = "https://micro.blog"


class MicroblogClient:
    def __init__(self, token: str, base_url: str = DEFAULT_BASE_URL):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.media_endpoint = "/micropub/media"
        self.default_destination: str | None = None
        self.username: str | None = None
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ── helpers ──────────────────────────────────────────────

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Contain transport failures without leaking request headers or credential values."""
        try:
            return self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            before_send = isinstance(
                exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
            )
            outcome = "not_applied" if method == "GET" or before_send else "unknown"
            return httpx.Response(
                599,
                extensions={
                    "mb_error": {
                        "ok": False,
                        "error": "network_error",
                        "code": 599,
                        "outcome": outcome,
                    }
                },
            )

    @staticmethod
    def _retry_after(resp: httpx.Response) -> int:
        try:
            return max(0, int(resp.headers.get("Retry-After", "60")))
        except ValueError:
            return 60

    def _handle_response(self, resp: httpx.Response, *, error_code: int = 502) -> dict:
        """Check for errors and return parsed JSON or error dict."""
        if "mb_error" in resp.extensions:
            return resp.extensions["mb_error"]
        if resp.status_code == 429:
            retry_after = self._retry_after(resp)
            return {
                "ok": False,
                "error": "rate_limited",
                "code": 429,
                "retry_after": int(retry_after),
            }
        if resp.status_code == 401:
            return {"ok": False, "error": "Unauthorized — invalid token", "code": 401}
        if resp.status_code >= 400:
            text = (
                resp.text.replace(self.token, "[redacted]")[:200].strip()
                or f"HTTP {resp.status_code} error"
            )
            return {"ok": False, "error": text, "code": resp.status_code}
        if resp.status_code >= 300:
            return {"ok": False, "error": "unexpected_redirect", "code": 502}
        # Some endpoints return empty body on success (e.g. delete)
        if not resp.text.strip():
            return {"ok": True, "data": {}}
        try:
            value = resp.json()
            if isinstance(value, dict) and "error" in value:
                return {
                    "ok": False,
                    "error": str(value["error"]).replace(self.token, "[redacted]")[:200],
                    "code": error_code,
                }
            return {"ok": True, "data": value}
        except (ValueError, KeyError):
            return {"ok": False, "error": "invalid_response", "code": 502}

    # ── auth / user info ────────────────────────────────────

    def verify_token(self) -> dict:
        """POST /account/verify — returns user info if token is valid."""
        resp = self._request("POST", "/account/verify", data={"token": self.token})
        # This endpoint reports invalid credentials in a JSON error with HTTP 200.
        return self._handle_response(resp, error_code=401)

    def _handle_feed_response(self, resp: httpx.Response) -> dict:
        result = self._handle_response(resp)
        if result["ok"]:
            data = result.get("data")
            items = data.get("items") if isinstance(data, dict) else None
            if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
                return {"ok": False, "error": "invalid_feed_response", "code": 502}
        return result

    # ── JSON API (reads) ────────────────────────────────────

    def get_timeline(
        self, count: int = 20, since_id: int | None = None, before_id: int | None = None
    ) -> dict:
        params: dict = {"count": count}
        if since_id is not None:
            params["since_id"] = since_id
        if before_id is not None:
            params["before_id"] = before_id
        resp = self._request("GET", "/posts/all", params=params)
        return self._handle_feed_response(resp)

    def get_mentions(self) -> dict:
        resp = self._request("GET", "/posts/mentions")
        return self._handle_feed_response(resp)

    def get_photos(self) -> dict:
        resp = self._request("GET", "/posts/photos")
        return self._handle_feed_response(resp)

    def get_discover(self, collection: str | None = None, count: int = 20) -> dict:
        if collection:
            resp = self._request("GET", f"/posts/discover/{collection}", params={"count": count})
        else:
            resp = self._request("GET", "/posts/discover", params={"count": count})
        return self._handle_feed_response(resp)

    def get_conversation(self, post_id: int) -> dict:
        resp = self._request("GET", "/posts/conversation", params={"id": post_id})
        return self._handle_feed_response(resp)

    def get_url_conversation(self, url: str) -> dict:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username:
            return {"ok": False, "error": "Use a full public post URL", "code": 400}
        resp = self._request(
            "GET",
            "/conversation.js",
            params={"url": url, "format": "jsonfeed"},
            headers={"Accept": "application/json"},
        )
        if resp.status_code == 403 and resp.text.strip() == "Token missing required scope":
            return {
                "ok": False,
                "error": (
                    "URL conversation denied: token missing required scope. Ask the operator "
                    "to review Micro.blog read permissions; use a native conversation ID if known. "
                    "MB will not change credentials or retry anonymously."
                ),
                "code": 403,
                "reason": "insufficient_scope",
            }
        # Official Inkwell treats 404 as an unresolved URL, not proof of no replies.
        if resp.status_code == 404:
            return {"ok": True, "data": {"items": [], "not_found": True}}
        return self._handle_feed_response(resp)

    def get_replies(self, count: int = 20) -> dict:
        resp = self._request("GET", "/posts/replies", params={"count": count})
        return self._handle_feed_response(resp)

    def get_user(self, username: str, count: int = 20) -> dict:
        resp = self._request("GET", f"/posts/{username}", params={"count": count})
        return self._handle_feed_response(resp)

    def get_following(self, username: str) -> dict:
        resp = self._request("GET", f"/users/following/{username}")
        return self._handle_response(resp)

    def get_user_discover(self, username: str) -> dict:
        resp = self._request("GET", f"/users/discover/{username}")
        return self._handle_response(resp)

    def is_following(self, username: str) -> dict:
        resp = self._request("GET", "/users/is_following", params={"username": username})
        return self._handle_response(resp)

    def follow(self, username: str) -> dict:
        resp = self._request("POST", "/users/follow", data={"username": username})
        return self._handle_response(resp)

    def unfollow(self, username: str) -> dict:
        resp = self._request("POST", "/users/unfollow", data={"username": username})
        return self._handle_response(resp)

    def mute(self, value: str, *, keyword: bool = False) -> dict:
        """Mute a username or keyword."""
        resp = self._request(
            "POST", "/users/mute", data={"keyword" if keyword else "username": value}
        )
        return self._handle_response(resp)

    def get_muting(self) -> dict:
        resp = self._request("GET", "/users/muting")
        return self._handle_response(resp)

    def unmute(self, mute_id: int) -> dict:
        resp = self._request("DELETE", f"/users/muting/{mute_id}")
        return self._handle_response(resp)

    def block(self, username: str) -> dict:
        resp = self._request("POST", "/users/block", data={"username": username})
        return self._handle_response(resp)

    def get_blocking(self) -> dict:
        resp = self._request("GET", "/users/blocking")
        return self._handle_response(resp)

    def unblock(self, block_id: int) -> dict:
        resp = self._request("DELETE", f"/users/blocking/{block_id}")
        return self._handle_response(resp)

    def check_timeline(self, since_id: int) -> dict:
        resp = self._request("GET", "/posts/check", params={"since_id": since_id})
        return self._handle_response(resp)

    def get_blog_posts(self, username: str, count: int = 20, category: str | None = None) -> dict:
        """Get blog posts. Uses Micropub source for non-default destinations."""
        if self.default_destination:
            result = self.micropub_list()
            if not result["ok"]:
                return result
            items = result["data"].get("items", [])
            normalized = self._normalize_micropub_items(items, owner=username)
            if category:
                normalized = [i for i in normalized if category in i.get("tags", [])]
            return {"ok": True, "data": {"items": normalized[:count]}}
        params: dict = {"count": count}
        if category:
            params["category"] = category
        resp = self._request("GET", f"/posts/{username}", params=params)
        return self._handle_response(resp)

    def search_blog(self, username: str, query: str, category: str | None = None) -> dict:
        """Server-side search of selected blog source, as used by the official client."""
        if not self.default_destination:
            return {"ok": False, "error": "Resolve a selected blog before searching", "code": 400}
        result = self.micropub_list(query=query)
        if not result["ok"]:
            return result
        items = self._normalize_micropub_items(result["data"]["items"], owner=username)
        if category:
            items = [i for i in items if category in i.get("tags", [])]
        return {
            "ok": True,
            "data": {
                "items": items,
                "coverage": "server-filtered-source-window",
                "coverage_complete": False,
            },
        }

    @staticmethod
    def _normalize_micropub_items(items: list, owner: str | None = None) -> list:
        """Convert Micropub h-entry items to JSON Feed-compatible format."""
        out = []
        for item in items:
            props = item.get("properties", {})
            content_list = props.get("content", [])
            content = content_list[0] if content_list else ""
            name_list = props.get("name", [])
            title = name_list[0] if name_list else ""
            url_list = props.get("url", [])
            url = url_list[0] if url_list else ""
            uid_list = props.get("uid", [])
            uid = str(uid_list[0]) if uid_list else ""
            pub_list = props.get("published", [])
            published = pub_list[0] if pub_list else ""
            categories = props.get("category", [])
            status_list = props.get("post-status", [])
            status = status_list[0] if status_list else "published"
            normalized_item: dict = {
                "id": uid,
                "url": url,
                "title": title,
                "content_html": content,
                "date_published": published,
                "tags": categories,
                "_microblog": {"post_status": status},
            }
            if owner:
                normalized_item["author"] = {"_microblog": {"username": owner}}
            out.append(normalized_item)
        return out

    # ── Micropub API (writes) ───────────────────────────────

    def post_reply(self, post_id: int, content: str) -> dict:
        """POST /posts/reply — reply to a post via the native API."""
        resp = self._request("POST", "/posts/reply", data={"id": post_id, "content": content})
        result = self._handle_response(resp)
        if result["ok"]:
            data = result.get("data")
            reply_id = data.get("id") if isinstance(data, dict) else None
            if (
                isinstance(reply_id, bool)
                or not isinstance(reply_id, (str, int))
                or not str(reply_id).isascii()
                or len(str(reply_id)) > 20
                or not str(reply_id).isdigit()
                or int(reply_id) <= 0
            ):
                # A successful HTTP status without an identifiable reply cannot
                # settle a write. Keep its claim recoverable and never resend it.
                return {
                    "ok": False,
                    "error": "invalid_reply_confirmation",
                    "code": 502,
                    "outcome": "unknown",
                }
        return result

    def micropub_create(
        self,
        *,
        content: str,
        title: str | None = None,
        draft: bool = False,
        reply_to: str | None = None,
        photo_url: str | None = None,
        photo_alt: str | None = None,
        categories: list[str] | None = None,
        mp_destination: str | None = None,
    ) -> dict:
        """Create a new post via Micropub."""
        data: dict = {
            "h": "entry",
            "content": content,
        }
        if title:
            data["name"] = title
        if draft:
            data["post-status"] = "draft"
        if reply_to:
            data["in-reply-to"] = reply_to
        if photo_url:
            data["photo"] = photo_url
            if photo_alt is not None:
                data["mp-photo-alt"] = photo_alt
        if categories:
            data["category[]"] = categories
        destination = mp_destination or self.default_destination
        if destination:
            data["mp-destination"] = destination
        resp = self._request("POST", "/micropub", data=data)
        return self._handle_micropub_response(resp, require_location=True)

    def micropub_update(
        self,
        url: str,
        *,
        content: str | None = None,
        title: str | None = None,
        categories: list[str] | None = None,
    ) -> dict:
        """Update an existing post via Micropub action=update."""
        data: dict = {
            "action": "update",
            "url": url,
        }
        if self.default_destination:
            data["mp-destination"] = self.default_destination
        replace = {}
        if content is not None:
            replace["content"] = [content]
        if title is not None:
            replace["name"] = [title]
        if categories is not None:
            replace["category"] = categories
        if not replace:
            return {
                "ok": False,
                "error": "Nothing to update — provide --content, --title, or --category",
                "code": 400,
            }
        data["replace"] = replace
        resp = self._request("POST", "/micropub", json=data)
        return self._handle_micropub_response(resp)

    def micropub_publish(self, url: str) -> dict:
        """Publish the existing draft without replacing its reviewed content."""
        data: dict = {"action": "update", "url": url, "replace": {"post-status": ["published"]}}
        if self.default_destination:
            data["mp-destination"] = self.default_destination
        return self._handle_micropub_response(self._request("POST", "/micropub", json=data))

    def micropub_delete(self, url: str) -> dict:
        data: dict = {
            "action": "delete",
            "url": url,
        }
        if self.default_destination:
            data["mp-destination"] = self.default_destination
        resp = self._request("POST", "/micropub", data=data)
        return self._handle_micropub_response(resp)

    def micropub_get(self, url: str) -> dict:
        """GET /micropub?q=source&url=<url> — fetch a single post's properties."""
        params: dict = {"q": "source", "url": url}
        if self.default_destination:
            params["mp-destination"] = self.default_destination
        resp = self._request("GET", "/micropub", params=params)
        result = self._handle_response(resp)
        if result["ok"] and (
            not isinstance(result.get("data"), dict)
            or not isinstance(result["data"].get("properties"), dict)
        ):
            return {"ok": False, "error": "invalid_source_response", "code": 502}
        return result

    def micropub_list(self, drafts: bool = False, query: str | None = None) -> dict:
        params: dict = {"q": "source"}
        if query is not None:
            params["filter"] = query
        if drafts:
            params["post-status"] = "draft"
        if self.default_destination:
            params["mp-destination"] = self.default_destination
        resp = self._request("GET", "/micropub", params=params)
        return self._handle_feed_response(resp)

    def micropub_get_categories(self) -> dict:
        """GET /micropub?q=category — list all categories."""
        params: dict = {"q": "category"}
        if self.default_destination:
            params["mp-destination"] = self.default_destination
        resp = self._request("GET", "/micropub", params=params)
        return self._handle_response(resp)

    def micropub_get_config(self) -> dict:
        """GET /micropub?q=config — get Micropub config including blog destinations."""
        resp = self._request("GET", "/micropub", params={"q": "config"})
        return self._handle_response(resp)

    def micropub_upload_bytes(
        self, filename: str, content: bytes, alt: str | None = None, content_type: str | None = None
    ) -> dict:
        """Upload image bytes to the media endpoint, return its URL."""
        file_value = (filename, content, content_type) if content_type else (filename, content)
        files = {"file": file_value}
        data = {}
        if alt:
            data["mp-photo-alt"] = alt
        if self.default_destination:
            data["mp-destination"] = self.default_destination
        resp = self._request(
            "POST", getattr(self, "media_endpoint", "/micropub/media"), files=files, data=data
        )
        result = self._handle_micropub_response(resp, require_location=True)
        if result["ok"] and resp.status_code not in {201, 202}:
            return {
                "ok": False,
                "error": "unexpected_upload_status",
                "code": 502,
                "outcome": "unknown",
            }
        if result["ok"]:
            result["data"].pop("id", None)
            result["data"].pop("preview", None)
            result["data"].update(
                upload_status="accepted" if resp.status_code == 202 else "created",
                processing_pending=resp.status_code == 202,
            )
        return result

    def _handle_micropub_response(
        self, resp: httpx.Response, *, require_location: bool = False
    ) -> dict:
        """Handle Micropub responses (201 with Location header on success)."""
        if "mb_error" in resp.extensions:
            return resp.extensions["mb_error"]
        if resp.status_code == 429:
            retry_after = self._retry_after(resp)
            return {
                "ok": False,
                "error": "rate_limited",
                "code": 429,
                "retry_after": int(retry_after),
            }
        if resp.status_code == 401:
            return {"ok": False, "error": "Unauthorized — invalid token", "code": 401}
        if resp.status_code >= 400:
            text = (
                resp.text.replace(self.token, "[redacted]")[:200].strip()
                or f"HTTP {resp.status_code} error"
            )
            return {"ok": False, "error": text, "code": resp.status_code}
        if resp.status_code >= 300:
            return {"ok": False, "error": "unexpected_redirect", "code": 502, "outcome": "unknown"}
        payload = {}
        if resp.text.strip():
            try:
                value = resp.json()
                if not isinstance(value, dict) or "error" in value:
                    return {
                        "ok": False,
                        "error": "invalid_write_response",
                        "code": 502,
                        "outcome": "unknown",
                    }
                payload = value
            except ValueError:
                return {
                    "ok": False,
                    "error": "invalid_write_response",
                    "code": 502,
                    "outcome": "unknown",
                }
        location = resp.headers.get("Location") or payload.get("url", "")
        if not isinstance(location, str) or (
            require_location
            and (
                not location
                or urlparse(location).scheme not in {"http", "https"}
                or not urlparse(location).netloc
            )
        ):
            return {
                "ok": False,
                "error": "missing_write_location",
                "code": 502,
                "outcome": "unknown",
            }
        post_id = location.rstrip("/").split("/")[-1] if location else ""
        data = {"url": location, "id": post_id}
        # Draft preview links are returned to the caller, never copied into durable receipts.
        if isinstance(payload.get("preview"), str):
            data["preview"] = payload["preview"]
        return {"ok": True, "data": data}
