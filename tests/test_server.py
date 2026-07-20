from __future__ import annotations

import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

from canforge_mcp import __version__
from canforge_mcp.server import main, mcp
from canforge_mcp.tools import TOOLS


def test_version_matches_release() -> None:
    assert __version__ == "0.1.0"


@pytest.mark.asyncio
async def test_server_registers_all_tools_with_read_only_annotations() -> None:
    listed = await mcp.list_tools()

    assert [tool.name for tool in listed] == [tool.__name__ for tool in TOOLS]
    assert len(listed) == 13
    for tool in listed:
        assert tool.description
        assert tool.inputSchema["type"] == "object"
        assert tool.outputSchema is not None
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.idempotentHint is True
        assert tool.annotations.openWorldHint is False


def test_main_runs_stdio_only(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(mcp, "run", lambda transport: calls.append(transport))

    main()

    assert calls == ["stdio"]


@pytest.mark.asyncio
async def test_installed_console_script_stdio_round_trip(sample_dbc: Path, candump_log: Path) -> None:
    executable = Path(sys.executable).with_name("canforge-mcp")
    assert executable.exists(), "editable install must expose the console script"
    params = StdioServerParameters(command=str(executable), args=[])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            result = await session.call_tool("dbc_info", {"dbc_path": str(sample_dbc)})
            inventory = await session.call_tool(
                "log_signal_inventory",
                {"dbc_path": str(sample_dbc), "log_path": str(candump_log)},
            )

    assert len(listed.tools) == 13
    assert result.isError is False
    assert result.structuredContent is not None
    assert result.structuredContent["message_count"] == 3
    assert inventory.isError is False
    assert inventory.structuredContent is not None
    assert inventory.structuredContent["frame_count"] == 300
    assert inventory.structuredContent["matched_id_count"] == 1


@pytest.mark.asyncio
async def test_stdio_tool_error_is_useful_without_traceback(tmp_path: Path) -> None:
    executable = Path(sys.executable).with_name("canforge-mcp")
    params = StdioServerParameters(command=str(executable), args=[])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("dbc_info", {"dbc_path": str(tmp_path / "missing.dbc")})

    assert result.isError is True
    assert result.content
    assert isinstance(result.content[0], TextContent)
    assert "DBC file not found" in result.content[0].text
    assert "Traceback" not in result.content[0].text
    assert result.structuredContent is None


@pytest.mark.asyncio
async def test_stdio_unparseable_dbc_returns_structured_terminal_error(tmp_path: Path) -> None:
    garbage = tmp_path / "garbage.dbc"
    garbage.write_text("not a dbc", encoding="utf-8")
    executable = Path(sys.executable).with_name("canforge-mcp")
    params = StdioServerParameters(command=str(executable), args=[])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("dbc_info", {"dbc_path": str(garbage)})

    assert result.isError is True
    assert result.structuredContent is not None
    assert result.structuredContent == {
        "code": "unparseable_dbc",
        "message": result.structuredContent["message"],
        "retryable": False,
        "recommended_action": (
            "Report this failure and request a valid DBC export; "
            "do not rewrite, clean, convert, or copy the input."
        ),
    }
    assert result.structuredContent["message"].startswith("Cannot parse DBC file")
    assert result.content
    assert isinstance(result.content[0], TextContent)
    assert "unparseable_dbc" in result.content[0].text
    assert "retryable: false" in result.content[0].text
    assert "Recommended action:" in result.content[0].text
    assert "Traceback" not in result.content[0].text
