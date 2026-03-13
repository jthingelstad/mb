"""HTTP client for micro.blog. Accepts base_url override for testing."""

from pathlib import Path

import httpx

DEFAULT_BASE_URL = "https://micro.blog"


class MicroblogClient:
    def __init__(self, token: str, base_url: str = DEFAULT_BASE_URL):
        self.token = token
        self.base_url = base_url.rstrip("/")
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

    def _handle_response(self, resp: httpx.Response) -> dict:
        """Check for errors and return parsed JSON or error dict."""
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After", 60)
            return {
                "ok": False,
                "error": "rate_limited",
                "retry_after": int(retry_after),
            }
        if resp.status_code == 401:
            return {"ok": False, "error": "Unauthorized — invalid token", "code": 401}
        if resp.status_code >= 400:
            text = resp.text[:200].strip() or f"HTTP {resp.status_code} error"
            return {"ok": False, "error": text, "code": resp.status_code}
        # Some endpoints return empty body on success (e.g. delete)
        if not resp.text.strip():
            return {"ok": True, "data": {}}
        try:
            return {"ok": True, "data": resp.json()}
        except (ValueError, KeyError):
            return {"ok": True, "data": {"raw": resp.text}}

    # ── auth / user info ────────────────────────────────────

    def verify_token(self) -> dict:
        """POST /account/verify — returns user info if token is valid."""
        resp = self._client.post("/account/verify", data={"token": self.token})
        result = self._handle_response(resp)
        # API returns 200 with {"error": "..."} for invalid tokens
        if result["ok"] and isinstance(result.get("data"), dict) and "error" in result["data"]:
            return {"ok": False, "error": result["data"]["error"], "code": 401}
        return result

    # ── JSON API (reads) ────────────────────────────────────

    def get_timeline(self, count: int = 20, since_id: int | None = None,
                     before_id: int | None = None) -> dict:
        params: dict = {"count": count}
        if since_id is not None:
            params["since_id"] = since_id
        if before_id is not None:
            params["before_id"] = before_id
        resp = self._client.get("/posts/all", params=params)
        return self._handle_response(resp)

    def get_mentions(self) -> dict:
        resp = self._client.get("/posts/mentions")
        return self._handle_response(resp)

    def get_photos(self) -> dict:
        resp = self._client.get("/posts/photos")
        return self._handle_response(resp)

    def get_discover(self, collection: str | None = None) -> dict:
        if collection:
            resp = self._client.get(f"/posts/discover/{collection}")
        else:
            resp = self._client.get("/posts/discover")
        return self._handle_response(resp)

    def get_conversation(self, post_id: int) -> dict:
        resp = self._client.get("/posts/conversation", params={"id": post_id})
        return self._handle_response(resp)

    def get_user(self, username: str) -> dict:
        resp = self._client.get(f"/posts/{username}")
        return self._handle_response(resp)

    def get_following(self, username: str) -> dict:
        resp = self._client.get(f"/users/following/{username}")
        return self._handle_response(resp)

    def get_user_discover(self, username: str) -> dict:
        resp = self._client.get(f"/users/discover/{username}")
        return self._handle_response(resp)

    def is_following(self, username: str) -> dict:
        resp = self._client.get("/users/is_following", params={"username": username})
        return self._handle_response(resp)

    def follow(self, username: str) -> dict:
        resp = self._client.post("/users/follow", data={"username": username})
        return self._handle_response(resp)

    def unfollow(self, username: str) -> dict:
        resp = self._client.post("/users/unfollow", data={"username": username})
        return self._handle_response(resp)

    def mute(self, value: str) -> dict:
        """Mute a username or keyword."""
        resp = self._client.post("/users/mute", data={"username": value})
        return self._handle_response(resp)

    def get_muting(self) -> dict:
        resp = self._client.get("/users/muting")
        return self._handle_response(resp)

    def unmute(self, mute_id: int) -> dict:
        resp = self._client.post("/users/unmute", data={"id": mute_id})
        return self._handle_response(resp)

    def block(self, username: str) -> dict:
        resp = self._client.post("/users/block", data={"username": username})
        return self._handle_response(resp)

    def get_blocking(self) -> dict:
        resp = self._client.get("/users/blocking")
        return self._handle_response(resp)

    def unblock(self, block_id: int) -> dict:
        resp = self._client.post("/users/unblock", data={"id": block_id})
        return self._handle_response(resp)

    def check_timeline(self, since_id: int) -> dict:
        resp = self._client.get("/posts/check", params={"since_id": since_id})
        return self._handle_response(resp)

    def get_blog_posts(self, username: str, count: int = 20,
                       category: str | None = None) -> dict:
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
        resp = self._client.get(f"/posts/{username}", params=params)
        return self._handle_response(resp)

    def search_blog(self, username: str, query: str,
                    category: str | None = None) -> dict:
        """Search posts. Uses client-side search for non-default destinations."""
        if self.default_destination:
            result = self.micropub_list()
            if not result["ok"]:
                return result
            items = result["data"].get("items", [])
            normalized = self._normalize_micropub_items(items, owner=username)
            q = query.lower()
            matched = [
                i for i in normalized
                if q in (i.get("content_html") or "").lower()
                or q in (i.get("title") or "").lower()
            ]
            if category:
                matched = [i for i in matched if category in i.get("tags", [])]
            return {"ok": True, "data": {"items": matched}}
        params: dict = {"search": query}
        if category:
            params["category"] = category
        resp = self._client.get(f"/posts/{username}", params=params)
        return self._handle_response(resp)

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
            item: dict = {
                "id": uid,
                "url": url,
                "title": title,
                "content_html": content,
                "date_published": published,
                "tags": categories,
                "_microblog": {"post_status": status},
            }
            if owner:
                item["author"] = {"_microblog": {"username": owner}}
            out.append(item)
        return out

    # ── Micropub API (writes) ───────────────────────────────

    def post_reply(self, post_id: int, content: str) -> dict:
        """POST /posts/reply — reply to a post via the native API."""
        resp = self._client.post("/posts/reply", data={"id": post_id, "content": content})
        return self._handle_response(resp)

    def micropub_create(self, *, content: str, title: str | None = None,
                        draft: bool = False, reply_to: str | None = None,
                        photo_url: str | None = None,
                        categories: list[str] | None = None,
                        mp_destination: str | None = None) -> dict:
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
        if categories:
            data["category[]"] = categories
        destination = mp_destination or self.default_destination
        if destination:
            data["mp-destination"] = destination
        resp = self._client.post("/micropub", data=data)
        return self._handle_micropub_response(resp)

    def micropub_update(self, url: str, *, content: str | None = None,
                        title: str | None = None,
                        categories: list[str] | None = None) -> dict:
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
            return {"ok": False, "error": "Nothing to update — provide --content, --title, or --category", "code": 400}
        data["replace"] = replace
        resp = self._client.post("/micropub", json=data)
        return self._handle_micropub_response(resp)

    def micropub_delete(self, url: str) -> dict:
        data: dict = {
            "action": "delete",
            "url": url,
        }
        if self.default_destination:
            data["mp-destination"] = self.default_destination
        resp = self._client.post("/micropub", data=data)
        return self._handle_micropub_response(resp)

    def micropub_get(self, url: str) -> dict:
        """GET /micropub?q=source&url=<url> — fetch a single post's properties."""
        params: dict = {"q": "source", "url": url}
        if self.default_destination:
            params["mp-destination"] = self.default_destination
        resp = self._client.get("/micropub", params=params)
        return self._handle_response(resp)

    def micropub_list(self, drafts: bool = False) -> dict:
        params: dict = {"q": "source"}
        if drafts:
            params["post-status"] = "draft"
        if self.default_destination:
            params["mp-destination"] = self.default_destination
        resp = self._client.get("/micropub", params=params)
        return self._handle_response(resp)

    def micropub_get_categories(self) -> dict:
        """GET /micropub?q=category — list all categories."""
        params: dict = {"q": "category"}
        if self.default_destination:
            params["mp-destination"] = self.default_destination
        resp = self._client.get("/micropub", params=params)
        return self._handle_response(resp)

    def micropub_get_config(self) -> dict:
        """GET /micropub?q=config — get Micropub config including blog destinations."""
        resp = self._client.get("/micropub", params={"q": "config"})
        return self._handle_response(resp)

    def micropub_upload_bytes(self, filename: str, content: bytes,
                              alt: str | None = None,
                              content_type: str | None = None) -> dict:
        """Upload image bytes to the media endpoint, return its URL."""
        file_value = (filename, content, content_type) if content_type else (filename, content)
        files = {"file": file_value}
        data = {}
        if alt:
            data["mp-photo-alt"] = alt
        resp = self._client.post("/micropub/media", files=files, data=data)
        if resp.status_code in (201, 202):
            location = resp.headers.get("Location", "")
            return {"ok": True, "data": {"url": location}}
        return self._handle_response(resp)

    def micropub_upload_photo(self, filepath: str, alt: str | None = None) -> dict:
        """Upload a photo to the media endpoint, return its URL."""
        try:
            content = Path(filepath).read_bytes()
        except FileNotFoundError:
            return {"ok": False, "error": f"File not found: {filepath}", "code": 400}
        except OSError as e:
            return {"ok": False, "error": f"Cannot read file: {filepath} ({e})", "code": 400}
        return self.micropub_upload_bytes(filepath.split("/")[-1], content, alt=alt)

    def _handle_micropub_response(self, resp: httpx.Response) -> dict:
        """Handle Micropub responses (201 with Location header on success)."""
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After", 60)
            return {"ok": False, "error": "rate_limited", "retry_after": int(retry_after)}
        if resp.status_code == 401:
            return {"ok": False, "error": "Unauthorized — invalid token", "code": 401}
        if resp.status_code >= 400:
            text = resp.text[:200].strip() or f"HTTP {resp.status_code} error"
            return {"ok": False, "error": text, "code": resp.status_code}
        location = resp.headers.get("Location", "")
        # Extract post ID from URL if possible
        post_id = location.rstrip("/").split("/")[-1] if location else ""
        return {"ok": True, "data": {"url": location, "id": post_id}}
