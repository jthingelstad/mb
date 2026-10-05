"""The workflow guide must describe commands that exist."""

from typer.testing import CliRunner

from mb.cli import app
from mb.commands.guide import GUIDE_TEXT


def test_guide_prints_reference():
    result = CliRunner().invoke(app, ["guide"])
    assert result.exit_code == 0
    assert "SESSION START" in result.output and "RECOVERY" in result.output


def test_guide_uses_real_draft_listing_and_recovery_commands():
    assert "blog posts --drafts" not in GUIDE_TEXT
    assert "mb post list --drafts" in GUIDE_TEXT
    for command in ("mb post publish", "mb post replies", "mb mcp", "mb doctor", "--resolve"):
        assert command in GUIDE_TEXT, command
    assert "candidate" not in GUIDE_TEXT.lower()
