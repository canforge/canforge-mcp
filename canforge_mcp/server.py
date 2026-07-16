"""FastMCP server wiring and console entry point."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from canforge_mcp.tools import TOOLS

mcp = FastMCP(
    name="canforge-mcp",
    instructions=(
        "Inspect and decode local CAN DBC and capture-log files. "
        "Every tool is read-only, files remain on the local machine, and list outputs are bounded."
    ),
)

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

for tool in TOOLS:
    mcp.add_tool(tool, annotations=READ_ONLY, structured_output=True)


def main() -> None:
    """Run the server over stdio, the only transport supported in 0.1."""
    mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
