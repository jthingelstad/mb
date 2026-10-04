"""Run with an isolated base wheel installation, without development/MCP dependencies."""

import importlib.util
import json
import sys
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx
from typer.testing import CliRunner

from mb.api import MicroblogClient
from mb.cli import app

assert importlib.util.find_spec("mcp") is None
assert files("mb.guidance").joinpath("mcp.md").is_file()
runner = CliRunner()
help_result = runner.invoke(app, ["--help"])
assert help_result.exit_code == 0, help_result.exception
# Executes the global callback, which help deliberately bypasses.
guide = runner.invoke(app, ["guide"])
assert guide.exit_code == 0, guide.exception
missing_extra = runner.invoke(app, ["mcp"])
assert missing_extra.exit_code == 1 and "optional" in missing_extra.stderr
assert "mcp.server" not in sys.modules
print(
    "Installed base wheel: CLI callback/help, optional-extra error and packaged guidance verified."
)

# The installed CLI must enforce 2.0 write requirements without MCP or HTTP.
requests = []


def forbid_http(request):
    requests.append(request)
    raise AssertionError("Migration refusal must precede HTTP")


def synthetic_client(token):
    client = MicroblogClient(token)
    client._client.close()
    client._client = httpx.Client(
        base_url="https://micro.blog", transport=httpx.MockTransport(forbid_http)
    )
    return client


with (
    patch("mb.config.get_token", return_value="synthetic"),
    patch("mb.config.get_blog", return_value=None),
    patch("mb.cli.MicroblogClient", side_effect=synthetic_client),
):
    combined = runner.invoke(
        app, ["--format", "json", "post", "new", "Caption", "--photo", "x.png"]
    )
    assert (
        combined.exit_code == 1 and "media preview/upload" in json.loads(combined.output)["error"]
    )
    remote = runner.invoke(app, ["--format", "json", "upload", "https://example.test/image.png"])
    assert remote.exit_code == 1 and json.loads(remote.output)["outcome"] == "not_applied"
assert requests == []
print("Installed base wheel: removed implicit photo/URL paths verified.")

# Human writes use the installed shared service and temporary receipts, with mocked HTTP.


def human_client(token):
    def respond(request):
        if request.url.path == "/account/verify":
            return httpx.Response(200, json={"username": "synthetic"})
        if request.url.params.get("q") == "config":
            return httpx.Response(
                200, json={"destination": [{"uid": "https://synthetic.micro.blog/"}]}
            )
        assert request.method == "POST" and request.url.path == "/micropub"
        return httpx.Response(
            201, headers={"Location": "https://synthetic.micro.blog/created.html"}
        )

    client = MicroblogClient(token)
    client._client.close()
    client._client = httpx.Client(
        base_url="https://micro.blog", transport=httpx.MockTransport(respond)
    )
    return client


with (
    TemporaryDirectory() as directory,
    patch("mb.config.get_token", return_value="synthetic"),
    patch("mb.config.get_blog", return_value=None),
    patch("mb.cli.MicroblogClient", side_effect=human_client),
):
    args = ["--format", "json", "--state-file", str(Path(directory) / "receipts.sqlite")]
    posted = runner.invoke(app, [*args, "post", "new", "Synthetic"])
    assert posted.exit_code == 0, posted.exception
    receipt = json.loads(posted.output)
    assert receipt["operation_id"].startswith("cli-") and receipt["outcome"] == "applied"
    latest = runner.invoke(app, [*args, "operation-status", "--latest"])
    assert latest.exit_code == 0, latest.exception
    assert json.loads(latest.output)["operation_id"] == receipt["operation_id"]
print(
    "Installed base wheel: human write generates a durable receipt and --latest recovers it with mocked HTTP."
)
