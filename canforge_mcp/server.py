"""FastMCP server wiring and console entry point."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from canforge_mcp.errors import UnparseableInputError
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


def _terminal_error_result(error: UnparseableInputError) -> CallToolResult:
    payload: dict[str, Any] = dict(error.to_payload())
    fallback = (
        f"{error.code}: {error.message} (retryable: false). "
        f"Recommended action: {error.recommended_action}"
    )
    return CallToolResult(
        content=[TextContent(type="text", text=fallback)],
        structuredContent=payload,
        isError=True,
    )


def _with_structured_terminal_errors(tool: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(tool)
    def registered_tool(*args: Any, **kwargs: Any) -> Any:
        try:
            return tool(*args, **kwargs)
        except UnparseableInputError as exc:
            return _terminal_error_result(exc)

    return registered_tool


for tool in TOOLS:
    mcp.add_tool(_with_structured_terminal_errors(tool), annotations=READ_ONLY, structured_output=True)


def main() -> None:
    """Run the server over stdio, the only transport supported in 0.1."""
    mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
