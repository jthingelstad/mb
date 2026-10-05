"""Write results report the post URL and never invent an ID from a Location slug."""

import httpx
import pytest

from mb.api import MicroblogClient
from mb.formatters import output
from tests.test_cli_write_safety import BLOG, Harness


def client_returning(response):
    client = MicroblogClient("synthetic")
    client._client.close()
    client._client = httpx.Client(
        base_url="https://micro.blog", transport=httpx.MockTransport(lambda request: response)
    )
    return client


@pytest.mark.parametrize(
    "body,expected",
    [
        ({}, None),
        ({"id": 12345}, "12345"),
        ({"id": "678"}, "678"),
        ({"id": "hello.html"}, None),
        ({"id": True}, None),
    ],
)
def test_created_post_id_only_when_numeric(body, expected):
    response = httpx.Response(201, json=body, headers={"Location": BLOG + "2026/10/05/hello.html"})
    result = client_returning(response).micropub_create(content="Hello")
    assert result["ok"] and result["data"]["url"] == BLOG + "2026/10/05/hello.html"
    assert result["data"].get("id") == expected


def test_cli_create_reports_url_without_fake_id(tmp_path):
    harness = Harness(tmp_path)
    _, data = harness.invoke(["post", "new", "Hello", "--operation-id", "made"])
    assert data["data"]["url"] == BLOG + "created.html" and "id" not in data["data"]
    _, receipt = harness.invoke(["operation-status", "made"])
    assert "id" not in receipt["data"]


def test_agent_and_human_write_lines(capsys):
    result = {
        "ok": True,
        "operation_id": "made",
        "outcome": "applied",
        "data": {"url": BLOG + "created.html", "preview": BLOG + "preview/1"},
    }
    output(result, "agent")
    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        "operation_id=made outcome=applied",
        f"OK url={BLOG}created.html preview={BLOG}preview/1",
    ]
    output(result, "human")
    human = capsys.readouterr().out
    assert f"OK url={BLOG}created.html" in human and "id=" not in human.replace("operation_id=", "")
    output({**result, "data": {"id": "42", "url": BLOG + "x"}}, "agent")
    assert f"OK id=42 url={BLOG}x" in capsys.readouterr().out
