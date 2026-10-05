"""Write docs/mcp-schemas.json from the published tool output schemas."""

import json
from pathlib import Path

from mb.shapes import DATA_SCHEMAS, SCHEMA_VERSION, output_schema

TARGET = Path(__file__).resolve().parents[1] / "docs" / "mcp-schemas.json"


def render() -> str:
    schemas = {tool: output_schema(tool) for tool in sorted(DATA_SCHEMAS)}
    return json.dumps({"schema_version": SCHEMA_VERSION, "tools": schemas}, indent=2) + "\n"


if __name__ == "__main__":
    TARGET.write_text(render())
    print(f"wrote {TARGET}")
