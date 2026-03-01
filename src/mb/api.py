"""HTTP client for micro.blog. Accepts base_url override for testing."""

import httpx

DEFAULT_BASE_URL = "https://micro.blog"


class MicroblogClient:
    def __init__(self, token: str, base_url: str = DEFAULT_BASE_URL):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.default_destination: str | None = None
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
            text = resp.text[:200]
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
        """GET /posts/account/verify — returns user info if token is valid."""
        resp = self._client.get("/posts/account/verify")
        return self._handle_response(resp)

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

    def get_discover_user(self, username: str) -> dict:
        resp = self._client.get(f"/posts/{username}")
        return self._handle_response(resp)

    def is_following(self, username: str) -> dict:
        resp = self._client.get(f"/users/is-following/{username}")
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
        """Get a user's own blog posts, optionally filtered by category."""
        params: dict = {"count": count}
        if category:
            params["category"] = category
        resp = self._client.get(f"/posts/{username}", params=params)
        return self._handle_response(resp)

    def search_blog(self, username: str, query: str) -> dict:
        """Search posts. Uses /posts/{username}?search=query if supported."""
        resp = self._client.get(f"/posts/{username}", params={"search": query})
        return self._handle_response(resp)

    # ── Micropub API (writes) ───────────────────────────────

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

    def micropub_delete(self, url: str) -> dict:
        data = {
            "action": "delete",
            "url": url,
        }
        resp = self._client.post("/micropub", data=data)
        return self._handle_micropub_response(resp)

    def micropub_list(self, drafts: bool = False) -> dict:
        params: dict = {"q": "source"}
        if drafts:
            params["post-status"] = "draft"
        resp = self._client.get("/micropub", params=params)
        return self._handle_response(resp)

    def micropub_get_categories(self) -> dict:
        """GET /micropub?q=category — list all categories."""
        resp = self._client.get("/micropub", params={"q": "category"})
        return self._handle_response(resp)

    def micropub_get_config(self) -> dict:
        """GET /micropub?q=config — get Micropub config including blog destinations."""
        resp = self._client.get("/micropub", params={"q": "config"})
        return self._handle_response(resp)

    def micropub_upload_photo(self, filepath: str, alt: str | None = None) -> dict:
        """Upload a photo to the media endpoint, return its URL."""
        with open(filepath, "rb") as f:
            files = {"file": (filepath.split("/")[-1], f)}
            data = {}
            if alt:
                data["mp-photo-alt"] = alt
            resp = self._client.post("/micropub/media", files=files, data=data)
        if resp.status_code in (201, 202):
            location = resp.headers.get("Location", "")
            return {"ok": True, "data": {"url": location}}
        return self._handle_response(resp)

    def _handle_micropub_response(self, resp: httpx.Response) -> dict:
        """Handle Micropub responses (201 with Location header on success)."""
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After", 60)
            return {"ok": False, "error": "rate_limited", "retry_after": int(retry_after)}
        if resp.status_code == 401:
            return {"ok": False, "error": "Unauthorized — invalid token", "code": 401}
        if resp.status_code >= 400:
            text = resp.text[:200]
            return {"ok": False, "error": text, "code": resp.status_code}
        location = resp.headers.get("Location", "")
        # Extract post ID from URL if possible
        post_id = location.rstrip("/").split("/")[-1] if location else ""
        return {"ok": True, "data": {"url": location, "id": post_id}}
