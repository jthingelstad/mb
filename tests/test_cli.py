"""CLI integration tests exercising commands through Typer's CliRunner."""

import json
from datetime import datetime, timezone
from unittest.mock import patch

import httpx
from typer.testing import CliRunner

from mb.cli import app
from tests.conftest import VERIFY_RESPONSE, MICROPUB_LIST_RESPONSE, MICROPUB_CONFIG_RESPONSE, CONVERSATION_RESPONSE

runner = CliRunner()


class _FrozenDateTime:
    @classmethod
    def now(cls, tz=None):
        current = datetime(2026, 3, 12, 12, 0, 0, tzinfo=timezone.utc)
        if tz is None:
            return current
        return current.astimezone(tz)

    @classmethod
    def fromisoformat(cls, value):
        return datetime.fromisoformat(value)


def _mock_transport(routes: dict | None = None):
    """Build a mock transport that covers common endpoints."""
    default_routes = {
        "/account/verify": ("POST", 200, VERIFY_RESPONSE),
        "/micropub": ("GET", 200, MICROPUB_LIST_RESPONSE),
    }
    if routes:
        default_routes.update(routes)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        params = dict(request.url.params)

        if method == "POST" and path == "/account/verify":
            return httpx.Response(200, json=VERIFY_RESPONSE)

        if method == "GET" and path == "/micropub":
            q = params.get("q", "source")
            if q == "config":
                return httpx.Response(200, json=MICROPUB_CONFIG_RESPONSE)
            if q == "category":
                return httpx.Response(200, json={"categories": ["journal", "reference"]})
            return httpx.Response(200, json=MICROPUB_LIST_RESPONSE)

        if method == "POST" and path == "/micropub/media":
            return httpx.Response(
                201, text="",
                headers={"Location": "https://cdn.micro.blog/photos/test-upload.jpg"},
            )

        if method == "POST" and path == "/micropub":
            return httpx.Response(
                201, text="",
                headers={"Location": "https://testuser.micro.blog/2026/02/28/newpost.html"},
            )

        if method == "GET" and path == "/posts/conversation":
            if params.get("id") == "20004":
                return httpx.Response(200, json={"items": [
                    {
                        "id": "20003",
                        "content_html": "<p>My original post</p>",
                        "date_published": "2026-03-12T00:00:00+00:00",
                        "url": "https://micro.blog/testuser/20003",
                        "author": {"name": "testuser", "url": "https://micro.blog/testuser", "_microblog": {"username": "testuser"}},
                        "_microblog": {},
                    },
                    {
                        "id": "20004",
                        "content_html": "<p>@testuser New mention</p>",
                        "date_published": "2026-03-12T01:00:00+00:00",
                        "url": "https://micro.blog/dave/20004",
                        "author": {"name": "dave", "url": "https://micro.blog/dave", "_microblog": {"username": "dave"}},
                        "_microblog": {"reply_to_id": "20003"},
                    },
                ]})
            if params.get("id") in {"20001", "20002", "20003"}:
                post_id = params.get("id")
                author = {"20001": "alice", "20002": "bob", "20003": "carol"}[post_id]
                return httpx.Response(200, json={"items": [
                    {
                        "id": post_id,
                        "content_html": f"<p>Post {post_id}</p>",
                        "date_published": "2026-03-12T00:00:00+00:00",
                        "url": f"https://micro.blog/{author}/{post_id}",
                        "author": {"name": author, "url": f"https://micro.blog/{author}", "_microblog": {"username": author}},
                        "_microblog": {},
                    }
                ]})
            return httpx.Response(200, json=CONVERSATION_RESPONSE)

        if method == "GET" and path == "/posts/all":
            since_id = params.get("since_id")
            items = [
                {
                    "id": "20003",
                    "content_html": "<p>Newest timeline post</p>",
                    "date_published": "2026-03-12T00:00:00+00:00",
                    "author": {"name": "carol", "url": "https://micro.blog/carol"},
                },
                {
                    "id": "20002",
                    "content_html": "<p>Second timeline post</p>",
                    "date_published": "2026-03-11T12:00:00+00:00",
                    "author": {"name": "bob", "url": "https://micro.blog/bob"},
                },
                {
                    "id": "20001",
                    "content_html": "<p>Third timeline post</p>",
                    "date_published": "2026-03-10T12:00:00+00:00",
                    "author": {"name": "alice", "url": "https://micro.blog/alice"},
                },
            ]
            if since_id is not None:
                items = [item for item in items if int(item["id"]) > int(since_id)]
            count = int(params.get("count", len(items)))
            return httpx.Response(200, json={"items": items[:count]})

        if method == "GET" and path == "/posts/mentions":
            return httpx.Response(200, json={"items": [
                {
                    "id": "20004",
                    "content_html": "<p>@testuser New mention</p>",
                    "date_published": "2026-03-12T01:00:00+00:00",
                    "author": {"name": "dave", "url": "https://micro.blog/dave"},
                },
                {
                    "id": "19999",
                    "content_html": "<p>@testuser Old mention</p>",
                    "date_published": "2026-03-09T01:00:00+00:00",
                    "author": {"name": "erin", "url": "https://micro.blog/erin"},
                },
            ]})

        if method == "GET" and path == "/posts/check":
            since_id = int(params.get("since_id", 0))
            timeline_ids = [20003, 20002, 20001]
            return httpx.Response(200, json={
                "count": len([item_id for item_id in timeline_ids if item_id > since_id]),
                "check_seconds": 20,
            })

        if method == "GET" and path == "/posts/discover":
            return httpx.Response(200, json={"items": []})

        if method == "GET" and path == "/posts/discover/books":
            return httpx.Response(200, json={"items": [{
                "id": 30001,
                "content_html": "<p>Book post</p>",
                "date_published": "2026-03-12T00:00:00+00:00",
                "author": {"name": "carol", "url": "https://micro.blog/carol"},
            }]})

        if method == "GET" and path == "/posts/alice":
            return httpx.Response(200, json={
                "username": "alice",
                "items": [{
                    "id": 20001,
                    "date_published": "2000-01-01T00:00:00+00:00",
                    "content_html": "<p>Alice post</p>",
                }],
            })

        if method == "GET" and path == "/posts/bob":
            return httpx.Response(200, json={
                "username": "bob",
                "items": [{
                    "id": 20002,
                    "date_published": "2100-01-01T00:00:00+00:00",
                    "content_html": "<p>Bob post</p>",
                }],
            })

        if method == "POST" and path == "/posts/reply":
            return httpx.Response(200, json={
                "id": 103,
                "url": "https://micro.blog/testuser/103",
                "content_html": "<p>reply</p>",
            })

        if method == "GET" and path == "/users/following/testuser":
            return httpx.Response(200, json=[
                {"username": "alice"},
                {"username": "bob"},
            ])

        if method == "GET" and path == "/users/discover/testuser":
            return httpx.Response(200, json=[
                {"username": "carol"},
                {"username": "dave"},
            ])

        if method == "POST" and path == "/users/follow":
            return httpx.Response(200, json={})

        if method == "POST" and path == "/users/unfollow":
            return httpx.Response(200, json={})

        return httpx.Response(404, json={"error": "Not found"})

    return httpx.MockTransport(handler)


def _patch_config(token="test-token", username="testuser", blog=None):
    """Return a stack of patches for config functions."""
    return [
        patch("mb.config.get_token", return_value=token),
        patch("mb.config.get_username", return_value=username),
        patch("mb.config.get_blog", return_value=blog),
    ]


def _invoke(args, token="test-token", username="testuser", blog=None):
    """Invoke the CLI with mocked config and HTTP transport."""
    transport = _mock_transport()
    patches = _patch_config(token=token, username=username, blog=blog)
    args = list(args)
    if "--format" not in args and "--human" not in args:
        args = ["--format", "json", *args]
    with patches[0], patches[1], patches[2], \
         patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)):
        return runner.invoke(app, args)


def _make_mock_init(transport):
    """Create a mock __init__ that injects the mock transport."""
    def mock_init(self, token="", base_url="https://micro.blog"):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.default_destination = None
        self.username = None
        self._client = httpx.Client(
            transport=transport,
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
    return mock_init


class TestWhoami:
    def test_default_format_is_agent(self):
        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)):
            result = runner.invoke(app, ["whoami"])

        assert result.exit_code == 0
        assert "@testuser" in result.output

    def test_success_json(self):
        result = _invoke(["whoami"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True
        assert data["data"]["username"] == "testuser"

    def test_no_token_error(self):
        result = _invoke(["whoami"], token=None)
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["ok"] is False
        assert "token" in data["error"].lower()

    def test_human_format(self):
        result = _invoke(["--human", "whoami"])
        assert result.exit_code == 0
        assert "testuser" in result.output
        # Should NOT be JSON
        try:
            json.loads(result.output)
            is_json = True
        except json.JSONDecodeError:
            is_json = False
        assert not is_json

    def test_agent_format(self):
        result = _invoke(["--format", "agent", "whoami"])
        assert result.exit_code == 0
        assert "@testuser" in result.output


class TestProfiles:
    def test_list_profiles(self):
        with patch("mb.config.list_profiles", return_value=[
            {"name": "default", "username": "testuser", "blog": ""},
            {"name": "test", "username": "ottoai", "blog": "https://ottoai-test.micro.blog/"},
        ]):
            result = runner.invoke(app, ["--format", "json", "profiles"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True
        assert len(data["data"]["profiles"]) == 2


class TestPostNew:
    def test_dry_run(self):
        result = _invoke(["post", "new", "--dry-run", "Hello test"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True
        assert data["data"]["dry_run"] is True
        assert data["data"]["content"] == "Hello test"

    def test_missing_content_error(self):
        result = _invoke(["post", "new"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["ok"] is False
        assert "content" in data["error"].lower()

    def test_dry_run_with_title(self):
        result = _invoke(["post", "new", "--dry-run", "--title", "My Title", "Body content"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["title"] == "My Title"
        assert data["data"]["content"] == "Body content"

    def test_dry_run_with_content_option(self):
        result = _invoke(["post", "new", "--dry-run", "--content", "Body content"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["content"] == "Body content"

    def test_dry_run_with_categories(self):
        result = _invoke(["post", "new", "--dry-run", "-c", "journal", "-c", "test", "Tagged post"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["categories"] == ["journal", "test"]

    def test_conflicting_content_sources_error(self):
        result = _invoke(["post", "new", "--dry-run", "--content", "Body content", "Positional content"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["ok"] is False
        assert "exactly one content source" in data["error"].lower()


class TestPostShort:
    def test_dry_run_short_post(self):
        result = _invoke(["post", "short", "--dry-run", "Small thought"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True
        assert data["data"]["short"] is True
        assert data["data"]["char_count"] == len("Small thought")
        assert data["data"]["warnings"] == []

    def test_short_post_warns_when_over_300(self):
        long_text = "x" * 301
        result = _invoke(["post", "short", "--dry-run", long_text])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["short"] is True
        assert "exceeds 300 characters" in data["data"]["warnings"][0]

    def test_short_post_strict_300_errors(self):
        long_text = "x" * 301
        result = _invoke(["post", "short", "--strict-300", long_text])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "300 characters or fewer" in data["error"]

    def test_short_post_rejects_two_photo_sources(self):
        result = _invoke([
            "post", "short", "--dry-run",
            "--photo", "image.jpg",
            "--photo-url", "https://cdn.example/test.jpg",
            "hello",
        ])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "one photo source" in data["error"].lower()


class TestGlobalFlagOrdering:
    """Verify global flags work both before and after the subcommand."""

    def test_profile_before_subcommand(self):
        result = _invoke(["-p", "default", "whoami"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True

    def test_profile_after_subcommand(self):
        result = _invoke(["whoami", "-p", "default"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True

    def test_format_after_subcommand(self):
        result = _invoke(["whoami", "--format", "agent"])
        assert result.exit_code == 0
        assert "@testuser" in result.output

    def test_human_flag_after_subcommand(self):
        result = _invoke(["whoami", "--human"])
        assert result.exit_code == 0
        # Human output should not be JSON
        try:
            json.loads(result.output)
            is_json = True
        except json.JSONDecodeError:
            is_json = False
        assert not is_json

    def test_nested_subcommand_with_global_flag(self):
        result = _invoke(["post", "new", "--dry-run", "test", "-p", "default"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True


class TestPostReply:
    def test_reply_bare_id_uses_native_api(self):
        """Bare ID should reply via POST /posts/reply (native API)."""
        result = _invoke(["post", "reply", "100", "Nice post!"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True

    def test_reply_url_extracts_id(self):
        """micro.blog URL should extract numeric ID and use native API."""
        result = _invoke(["post", "reply", "https://micro.blog/alice/100", "Great!"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True

    def test_reply_empty_content_error(self):
        result = _invoke(["post", "reply", "100", ""])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["ok"] is False
        assert "empty" in data["error"].lower()

    def test_reply_not_found_error(self):
        """Reply to a post ID not in the conversation should fail."""
        result = _invoke(["post", "reply", "99999", "Hello"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["ok"] is False
        assert "not found" in data["error"].lower()

    def test_reply_invalid_url_error(self):
        """Blog URL with no numeric ID should fail."""
        result = _invoke(["post", "reply", "https://alice.micro.blog/2026/02/28/hello.html", "Hi"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["ok"] is False
        assert "cannot extract" in data["error"].lower()


class TestTimelineCheckpoint:
    def test_checkpoint_save_and_read(self, tmp_path):
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text('[default]\ntoken = "test-token"\nusername = "testuser"\n')

        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)), \
             patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            # Save checkpoint
            result = runner.invoke(app, ["--format", "json", "timeline", "checkpoint", "85444200"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["ok"] is True
            assert data["data"]["checkpoint"] == 85444200

            # Read checkpoint back
            result = runner.invoke(app, ["--format", "json", "timeline", "checkpoint"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["ok"] is True
            assert data["data"]["checkpoint"] == 85444200

    def test_checkpoint_no_saved(self, tmp_path):
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text('[default]\ntoken = "test-token"\n')

        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)), \
             patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            result = runner.invoke(app, ["--format", "json", "timeline", "checkpoint"])
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert data["ok"] is False
            assert "no checkpoint" in data["error"].lower()


class TestHeartbeat:
    def test_heartbeat_bootstrap_snapshot(self, tmp_path):
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text('[default]\ntoken = "test-token"\nusername = "testuser"\n')

        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)), \
             patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            result = runner.invoke(app, ["--format", "json", "heartbeat", "--count", "2", "--mention-count", "1"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True
        assert data["data"]["kind"] == "heartbeat"
        assert data["data"]["mode"] == "bootstrap"
        assert data["data"]["new_timeline_count"] == 2
        assert data["data"]["new_mentions_count"] == 2
        assert [item["id"] for item in data["data"]["timeline"]] == ["20003", "20002"]
        assert [item["id"] for item in data["data"]["mentions"]] == ["20004"]

    def test_heartbeat_filters_since_saved_checkpoint(self, tmp_path):
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text(
            '[default]\n'
            'token = "test-token"\n'
            'username = "testuser"\n'
            'heartbeat_checkpoint = 20002\n'
        )

        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)), \
             patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            result = runner.invoke(app, ["--format", "json", "heartbeat"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["mode"] == "since-checkpoint"
        assert data["data"]["checkpoint"] == 20002
        assert data["data"]["new_timeline_count"] == 1
        assert [item["id"] for item in data["data"]["timeline"]] == ["20003"]
        assert data["data"]["new_mentions_count"] == 1
        assert [item["id"] for item in data["data"]["mentions"]] == ["20004"]

    def test_heartbeat_advances_by_default(self, tmp_path):
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text('[default]\ntoken = "test-token"\nusername = "testuser"\n')

        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)), \
             patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            result = runner.invoke(app, ["--format", "json", "heartbeat"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["advanced"] is True
        saved = config_file.read_text()
        assert 'heartbeat_checkpoint = 20004' in saved

    def test_heartbeat_no_advance_suppresses_save(self, tmp_path):
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text('[default]\ntoken = "test-token"\nusername = "testuser"\n')

        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)), \
             patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            result = runner.invoke(app, ["--format", "json", "heartbeat", "--no-advance"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["advanced"] is False
        saved = config_file.read_text()
        assert 'heartbeat_checkpoint' not in saved

    def test_heartbeat_mentions_only_skips_timeline_items(self, tmp_path):
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text('[default]\ntoken = "test-token"\nusername = "testuser"\nheartbeat_checkpoint = 20002\n')

        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)), \
             patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            result = runner.invoke(app, ["--format", "json", "heartbeat", "--mentions-only"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["timeline"] == []
        assert data["data"]["new_timeline_count"] == 0
        assert [item["id"] for item in data["data"]["mentions"]] == ["20004"]

    def test_heartbeat_default_advance_considers_unsampled_mentions(self, tmp_path):
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text('[default]\ntoken = "test-token"\nusername = "testuser"\n')

        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)), \
             patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            result = runner.invoke(app, ["--format", "json", "heartbeat", "--mention-count", "0"])

        assert result.exit_code == 0
        saved = config_file.read_text()
        assert 'heartbeat_checkpoint = 20004' in saved


class TestCatchup:
    def test_catchup_bootstrap_snapshot(self, tmp_path):
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text('[default]\ntoken = "test-token"\nusername = "testuser"\n')

        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)), \
             patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            result = runner.invoke(app, ["--format", "json", "catchup", "--count", "2"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["kind"] == "catchup"
        assert data["data"]["mode"] == "bootstrap"
        assert data["data"]["new_count"] == 2
        assert [item["id"] for item in data["data"]["items"]] == ["20003", "20002"]

    def test_catchup_filters_since_saved_checkpoint(self, tmp_path):
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text('[default]\ntoken = "test-token"\nusername = "testuser"\ncatchup_checkpoint = 20002\n')

        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)), \
             patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            result = runner.invoke(app, ["--format", "json", "catchup"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["mode"] == "since-checkpoint"
        assert data["data"]["checkpoint"] == 20002
        assert data["data"]["new_count"] == 1
        assert [item["id"] for item in data["data"]["items"]] == ["20003"]

    def test_catchup_advance_saves_latest_seen_id(self, tmp_path):
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text('[default]\ntoken = "test-token"\nusername = "testuser"\n')

        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)), \
             patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            result = runner.invoke(app, ["--format", "json", "catchup", "--advance", "--count", "1"])

        assert result.exit_code == 0
        saved = config_file.read_text()
        assert 'catchup_checkpoint = 20003' in saved


class TestInbox:
    def test_inbox_bootstrap_snapshot(self, tmp_path):
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text('[default]\ntoken = "test-token"\nusername = "testuser"\n')

        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)), \
             patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            result = runner.invoke(app, ["--format", "json", "inbox", "--count", "1"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["kind"] == "inbox"
        assert data["data"]["new_count"] == 2
        assert data["data"]["items"][0]["reason"] == "thread-reply"
        assert data["data"]["items"][0]["thread_has_self_post"] is True

    def test_inbox_filters_since_saved_checkpoint(self, tmp_path):
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text('[default]\ntoken = "test-token"\nusername = "testuser"\ninbox_checkpoint = 20003\n')

        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)), \
             patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            result = runner.invoke(app, ["--format", "json", "inbox"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["new_count"] == 1
        assert [entry["item"]["id"] for entry in data["data"]["items"]] == ["20004"]

    def test_inbox_advance_saves_latest_seen_id(self, tmp_path):
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text('[default]\ntoken = "test-token"\nusername = "testuser"\n')

        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)), \
             patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            result = runner.invoke(app, ["--format", "json", "inbox", "--advance"])

        assert result.exit_code == 0
        saved = config_file.read_text()
        assert 'inbox_checkpoint = 20004' in saved

    def test_inbox_reason_filter(self, tmp_path):
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text('[default]\ntoken = "test-token"\nusername = "testuser"\n')

        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)), \
             patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            result = runner.invoke(app, ["--format", "json", "inbox", "--reason", "thread-reply"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["new_count"] == 1
        assert data["data"]["filters"]["reason"] == ["thread-reply"]
        assert [entry["item"]["id"] for entry in data["data"]["items"]] == ["20004"]

    def test_inbox_fresh_hours_filter(self, tmp_path):
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text('[default]\ntoken = "test-token"\nusername = "testuser"\n')

        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)), \
             patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file), \
             patch("mb.commands.inbox.datetime", _FrozenDateTime):
            result = runner.invoke(app, ["--format", "json", "inbox", "--fresh-hours", "24"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["new_count"] == 1
        assert data["data"]["filters"]["fresh_hours"] == 24
        assert [entry["item"]["id"] for entry in data["data"]["items"]] == ["20004"]

    def test_inbox_rejects_advance_with_selective_filters(self, tmp_path):
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text('[default]\ntoken = "test-token"\nusername = "testuser"\n')

        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)), \
             patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            result = runner.invoke(app, ["--format", "json", "inbox", "--reason", "thread-reply", "--advance"])

        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "cannot combine --advance" in data["error"].lower()


class TestCheckpointCommands:
    def test_checkpoint_list(self, tmp_path):
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text(
            '[default]\n'
            'token = "test-token"\n'
            'username = "testuser"\n'
            'checkpoint = 100\n'
            'heartbeat_checkpoint = 200\n'
            'inbox_checkpoint = 300\n'
        )

        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)), \
             patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            result = runner.invoke(app, ["--format", "json", "checkpoint", "list"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["checkpoints"] == {"timeline": 100, "heartbeat": 200, "inbox": 300}

    def test_checkpoint_get_set_and_clear(self, tmp_path):
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text('[default]\ntoken = "test-token"\nusername = "testuser"\n')

        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)), \
             patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            set_result = runner.invoke(app, ["--format", "json", "checkpoint", "set", "heartbeat", "20004"])
            get_result = runner.invoke(app, ["--format", "json", "checkpoint", "get", "heartbeat"])
            clear_result = runner.invoke(app, ["--format", "json", "checkpoint", "clear", "heartbeat"])

        assert set_result.exit_code == 0
        assert get_result.exit_code == 0
        assert clear_result.exit_code == 0
        assert json.loads(set_result.output)["data"]["checkpoint"] == 20004
        assert json.loads(get_result.output)["data"]["checkpoint"] == 20004
        cleared = json.loads(clear_result.output)
        assert cleared["data"]["cleared"] is True

    def test_checkpoint_clear_all(self, tmp_path):
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text(
            '[default]\n'
            'token = "test-token"\n'
            'username = "testuser"\n'
            'checkpoint = 100\n'
            'heartbeat_checkpoint = 200\n'
        )

        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)), \
             patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            result = runner.invoke(app, ["--format", "json", "checkpoint", "clear", "--all"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["cleared"] == 2
        assert data["data"]["checkpoints"] == {}


class TestBlogs:
    def test_list_blogs(self):
        result = _invoke(["blogs"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True
        assert "blogs" in data["data"]
        assert len(data["data"]["blogs"]) == 2


class TestUserPipelines:
    def test_following_defaults_to_current_user(self):
        result = _invoke(["user", "following"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True
        assert len(data["data"]) == 2

    def test_lookup_users_last_post(self):
        result = _invoke(["lookup", "users", "--last-post", "alice"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True
        assert [entry["username"] for entry in data["data"]["users"]] == ["alice"]
        assert data["data"]["users"][0]["last_post_date"] == "2000-01-01T00:00:00+00:00"
        assert data["data"]["users"][0]["last_post_content_text"] == "Alice post"

    def test_discover_lists_candidates(self):
        result = _invoke(["user", "discover"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True
        assert [entry["username"] for entry in data["data"]] == ["carol", "dave"]

    def test_unfollow_reads_usernames_from_stdin(self):
        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)):
            result = runner.invoke(app, ["--format", "json", "user", "unfollow", "-"], input="@alice\nbob\n")

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True
        assert data["data"]["count"] == 2
        assert data["data"]["action"] == "unfollow"

    def test_follow_reads_usernames_from_stdin(self):
        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)):
            result = runner.invoke(app, ["--format", "json", "user", "follow", "-"], input="@carol\ndave\n")

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True
        assert data["data"]["count"] == 2
        assert data["data"]["action"] == "follow"

    def test_follow_reads_agent_format_lines_from_stdin(self):
        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)):
            result = runner.invoke(
                app,
                ["--format", "json", "user", "follow", "-"],
                input="[12345] @carol (2h): Post text\n[67890] @carol (1h): Another post\n[22222] @dave (3h): Hello\n",
            )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True
        assert data["data"]["count"] == 2
        assert [item["username"] for item in data["data"]["results"]] == ["carol", "dave"]

    def test_follow_reads_dotted_usernames_from_stdin(self):
        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)):
            result = runner.invoke(
                app,
                ["--format", "json", "user", "follow", "-"],
                input="[12345] @bapsi.micro.blog (2h): Post text\n[67890] @mitchw.bsky.social (1h): Another post\n",
            )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert [item["username"] for item in data["data"]["results"]] == [
            "bapsi.micro.blog",
            "mitchw.bsky.social",
        ]

    def test_follow_single_username_uses_batch_envelope(self):
        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)):
            result = runner.invoke(app, ["--format", "json", "user", "follow", "carol"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True
        assert data["data"]["count"] == 1
        assert data["data"]["results"][0]["username"] == "carol"

    def test_lookup_users_collects_lookup_errors(self):
        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)), \
             patch("mb.commands.lookup._fetch_user_lookup", side_effect=[
                 {"ok": True, "username": "alice", "last_post_date": "2000-01-01T00:00:00+00:00", "last_post_content_text": "Alice post"},
                 {"ok": False, "username": "bob", "error": "lookup failed", "code": 503},
             ]):
            result = runner.invoke(app, ["--format", "json", "lookup", "users", "--last-post", "alice", "bob"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert [entry["username"] for entry in data["data"]["users"]] == ["alice"]
        assert data["data"]["errors"][0]["username"] == "bob"

    def test_lookup_users_reads_from_stdin(self):
        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)):
            result = runner.invoke(app, ["--format", "json", "lookup", "users", "--days-since-posting"], input="@alice\nbob\n")

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert [entry["username"] for entry in data["data"]["users"]] == ["alice", "bob"]
        assert "inactive_days" in data["data"]["users"][0]

    def test_lookup_users_requires_lookup_flag(self):
        result = _invoke(["lookup", "users", "alice"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "choose at least one lookup" in data["error"].lower()

    def test_lookup_posts_post(self):
        result = _invoke(["lookup", "posts", "--post", "20003"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["posts"][0]["id"] == "20003"
        assert data["data"]["posts"][0]["content_text"] == "Post 20003"

    def test_lookup_posts_conversation_from_stdin_agent_lines(self):
        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)):
            result = runner.invoke(
                app,
                ["--format", "json", "lookup", "posts", "--conversation", "-"],
                input="[20004] @dave (1h): @testuser New mention\n",
            )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["posts"][0]["id"] == "20004"
        assert data["data"]["posts"][0]["conversation_count"] == 2

    def test_lookup_posts_ignores_non_identifier_stdin_lines(self):
        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)):
            result = runner.invoke(
                app,
                ["--format", "json", "lookup", "posts", "--conversation", "-"],
                input="@testuser inbox mode=bootstrap latest=20004\nnew_count=1\nthread-reply: [20004] @dave (1h): @testuser New mention\n",
            )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["data"]["posts"]) == 1
        assert data["data"]["errors"] == []


class TestTopLevelPipelineAliases:
    def test_following_alias(self):
        result = _invoke(["following"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True
        assert [entry["username"] for entry in data["data"]] == ["alice", "bob"]

    def test_unfollow_alias_reads_stdin(self):
        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)):
            result = runner.invoke(app, ["--format", "json", "unfollow", "-"], input="@alice\nbob\n")

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True
        assert data["data"]["action"] == "unfollow"

    def test_discover_alias(self):
        result = _invoke(["discover", "--collection", "books"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True

    def test_discover_list(self):
        result = _invoke(["discover", "--list"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["kind"] == "discover_collections"
        assert any(entry["slug"] == "books" for entry in data["data"]["collections"])

    def test_discover_unknown_collection_errors(self):
        result = _invoke(["discover", "--collection", "notarealcollection"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "unknown discover collection" in data["error"].lower()

    def test_lookup_users_command(self):
        result = _invoke(["lookup", "users", "--days-since-posting", "alice"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True
        assert data["data"]["users"][0]["username"] == "alice"


class TestUpload:
    def test_upload_local_file(self, tmp_path):
        photo = tmp_path / "otter.jpg"
        photo.write_bytes(b"fake-image")

        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)):
            result = runner.invoke(app, ["--format", "json", "upload", str(photo)])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["url"] == "https://cdn.micro.blog/photos/test-upload.jpg"

    def test_upload_remote_url(self):
        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)), \
             patch("mb.commands.upload._download_image", return_value=("otter.jpg", b"fake-image", "image/jpeg")):
            result = runner.invoke(app, ["--format", "json", "upload", "https://example.com/otter.jpg"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["source"] == "https://example.com/otter.jpg"
