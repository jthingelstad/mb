"""CLI integration tests exercising commands through Typer's CliRunner."""

import json
from unittest.mock import patch

import httpx
from typer.testing import CliRunner

from mb.cli import app
from tests.conftest import VERIFY_RESPONSE, MICROPUB_LIST_RESPONSE, MICROPUB_CONFIG_RESPONSE, CONVERSATION_RESPONSE

runner = CliRunner()


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
                return httpx.Response(200, json={"categories": ["notes", "test"]})
            return httpx.Response(200, json=MICROPUB_LIST_RESPONSE)

        if method == "POST" and path == "/micropub":
            return httpx.Response(
                201, text="",
                headers={"Location": "https://testuser.micro.blog/2026/02/28/newpost.html"},
            )

        if method == "GET" and path == "/posts/conversation":
            return httpx.Response(200, json=CONVERSATION_RESPONSE)

        if method == "POST" and path == "/posts/reply":
            return httpx.Response(200, json={
                "id": 103,
                "url": "https://micro.blog/testuser/103",
                "content_html": "<p>reply</p>",
            })

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
            result = runner.invoke(app, ["profiles"])
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
        result = _invoke(["post", "new", "--dry-run", "-c", "notes", "-c", "test", "Tagged post"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["categories"] == ["notes", "test"]

    def test_conflicting_content_sources_error(self):
        result = _invoke(["post", "new", "--dry-run", "--content", "Body content", "Positional content"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["ok"] is False
        assert "exactly one content source" in data["error"].lower()


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
            result = runner.invoke(app, ["timeline", "checkpoint", "85444200"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["ok"] is True
            assert data["data"]["checkpoint"] == 85444200

            # Read checkpoint back
            result = runner.invoke(app, ["timeline", "checkpoint"])
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
            result = runner.invoke(app, ["timeline", "checkpoint"])
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert data["ok"] is False
            assert "no checkpoint" in data["error"].lower()


class TestBlogs:
    def test_list_blogs(self):
        result = _invoke(["blogs"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True
        assert "blogs" in data["data"]
        assert len(data["data"]["blogs"]) == 2


class TestNotesRecall:
    def test_default_recall_uses_notes_category(self):
        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)), \
             patch("mb.api.MicroblogClient.get_blog_posts", return_value={"ok": True, "data": {"items": []}}) as get_blog_posts:
            result = runner.invoke(app, ["notes", "recall"])

        assert result.exit_code == 0
        assert get_blog_posts.call_args.kwargs["category"] == "notes"

    def test_search_without_category_searches_all_categories(self):
        transport = _mock_transport()
        patches = _patch_config()
        with patches[0], patches[1], patches[2], \
             patch("mb.api.MicroblogClient.__init__", _make_mock_init(transport)), \
             patch("mb.api.MicroblogClient.search_blog", return_value={"ok": True, "data": {"items": []}}) as search_blog:
            result = runner.invoke(app, ["notes", "recall", "--search", "keyword"])

        assert result.exit_code == 0
        assert search_blog.call_args.kwargs["category"] is None
