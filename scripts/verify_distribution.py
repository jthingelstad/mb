"""Validate optional dependencies, metadata and contents of the built archives in dist/."""

import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path

wheel = next(Path("dist").glob("mb-*.whl"))
source = next(Path("dist").glob("mb-*.tar.gz"))
with zipfile.ZipFile(wheel) as archive:
    names = set(archive.namelist())
    assert {"mb/guidance/mcp.md", "mb/media.py", "mb/commands/media.py"} <= names
    # Commands removed in 2.0 must not reappear from a stale build directory.
    assert not {"mb/commands/notes.py", "mb/commands/memory.py"} & names, names
    metadata = BytesParser().parsebytes(
        archive.read(next(n for n in archive.namelist() if n.endswith("/METADATA")))
    )
    dependencies = metadata.get_all("Requires-Dist")
    assert any(d.startswith("mcp") and 'extra == "mcp"' in d for d in dependencies)
    assert not any(d.startswith("mcp") and "extra" not in d for d in dependencies)
    assert metadata.get("Description-Content-Type") == "text/markdown"
    assert metadata.get("License-Expression") == "MIT"
    assert any("github.com/jthingelstad/mb" in u for u in metadata.get_all("Project-URL") or [])
with tarfile.open(source) as archive:
    paths = {"/".join(p.split("/")[1:]) for p in archive.getnames()}
    assert {
        "tests/conftest.py",
        "tests/mcp_fixture.py",
        "docs/mcp.md",
        "docs/migration-2.0.md",
        "tests/test_cli_write_safety.py",
        "docs/content-index-plan.md",
        "docs/homebrew-release-plan.md",
        "tests/test_bounded_capabilities.py",
        "skills/mb-mcp/SKILL.md",
        "examples/codex-mcp.toml",
        "examples/openclaw-mcp.json",
        "examples/claude-desktop.json",
        "README.md",
        "LICENSE",
        "src/mb/guidance/mcp.md",
        "scripts/verify_distribution.py",
    } <= paths
print(
    "Wheel: optional MCP dependency and packaged guidance verified; source archive: tests, examples and skills included."
)
