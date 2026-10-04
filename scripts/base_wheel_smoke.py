"""Run with an isolated base wheel installation, without development/MCP dependencies."""

import importlib.util
import sys
from importlib.resources import files

from typer.testing import CliRunner

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
