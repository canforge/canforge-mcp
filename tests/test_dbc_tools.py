from __future__ import annotations

import os
from enum import Enum
from pathlib import Path

import pytest

from canforge_mcp import tools
from canforge_mcp.errors import UnparseableInputError


def test_dbc_info_counts_and_nodes(sample_dbc: Path) -> None:
    result = tools.dbc_info(str(sample_dbc))

    assert result["version"] == "1.0"
    assert result["message_count"] == 3
    assert result["signal_count"] == 7
    assert result["node_count"] == 2
    assert result["node_names"] == ["Cluster", "EngineECU"]
    assert result["node_names_truncated"] is False
    assert result["path"] == str(sample_dbc.resolve())


def test_dbc_info_bounds_node_names(sample_dbc: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools, "MAX_NODE_NAMES", 1)

    result = tools.dbc_info(str(sample_dbc))

    assert result["node_names"] == ["Cluster"]
    assert result["node_names_truncated"] is True


def test_list_messages_search_truncation_and_cap(sample_dbc: Path) -> None:
    truncated = tools.list_messages(str(sample_dbc), limit=1)
    searched = tools.list_messages(str(sample_dbc), search="engineecu")
    capped = tools.list_messages(str(sample_dbc), limit=99_999)

    assert truncated["total"] == 3
    assert truncated["returned"] == 1
    assert truncated["truncated"] is True
    assert truncated["messages"][0]["name"] == "VehicleStatus"
    assert {item["name"] for item in searched["messages"]} == {"EngineData", "TransportData"}
    assert capped["limit"] == tools.MAX_LIST_LIMIT
    assert capped["truncated"] is False


def test_list_messages_searches_name_and_hex_id(sample_dbc: Path) -> None:
    by_name = tools.list_messages(str(sample_dbc), search="vehicle")
    by_id = tools.list_messages(str(sample_dbc), search="0xcfb")

    assert [item["name"] for item in by_name["messages"]] == ["VehicleStatus"]
    assert [item["name"] for item in by_id["messages"]] == ["EngineData"]


def test_list_messages_rejects_non_positive_limit(sample_dbc: Path) -> None:
    with pytest.raises(ValueError, match="limit must be at least 1"):
        tools.list_messages(str(sample_dbc), limit=0)


@pytest.mark.parametrize("selector", ["EngineData", "enginedata", "0xCFBFFDB", 0x0CFBFFDB])
def test_get_message_accepts_name_and_id(sample_dbc: Path, selector: str | int) -> None:
    result = tools.get_message(str(sample_dbc), selector)

    assert result["name"] == "EngineData"
    assert result["id"] == "0xCFBFFDB"
    assert result["signal_count"] == 3
    assert result["signals"][0]["name"] == "EngineSpeed"
    assert result["signals"][0]["unit"] == "rpm"
    assert result["signals"][2]["choices"]["1"] == "First"
    assert result["signals_truncated"] is False


def test_get_message_bounds_signal_detail(sample_dbc: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools, "MAX_SIGNALS_PER_MESSAGE", 1)

    result = tools.get_message(str(sample_dbc), "EngineData")

    assert len(result["signals"]) == 1
    assert result["signals_truncated"] is True


def test_get_message_rejects_unknown_name_and_id(sample_dbc: Path) -> None:
    with pytest.raises(ValueError, match="No message named"):
        tools.get_message(str(sample_dbc), "Missing")
    with pytest.raises(ValueError, match="0x7FF"):
        tools.get_message(str(sample_dbc), "0x7ff")


def test_search_signals_returns_owner_and_bounds(sample_dbc: Path) -> None:
    result = tools.search_signals(str(sample_dbc), "engine", limit=1)

    assert result["total"] == 1
    assert result["returned"] == 1
    assert result["signals"][0]["message_name"] == "EngineData"
    assert result["signals"][0]["signal_name"] == "EngineSpeed"
    assert result["signals"][0]["factor"] == 0.125


def test_search_signals_empty_query_truncates_and_caps(sample_dbc: Path) -> None:
    result = tools.search_signals(str(sample_dbc), "", limit=2)
    capped = tools.search_signals(str(sample_dbc), "", limit=99_999)

    assert result["total"] == 7
    assert result["truncated"] is True
    assert capped["limit"] == tools.MAX_LIST_LIMIT


def test_decode_frame_resolves_physical_values_and_choices(sample_dbc: Path) -> None:
    result = tools.decode_frame(str(sample_dbc), "0x1f4", "10 27 01")

    assert result["arbitration_id"] == "0x1F4"
    assert result["data_hex"] == "102701"
    assert result["signals"] == {"VehicleSpeed": 100.0, "Ignition": "On"}


def test_decode_frame_maps_input_and_database_errors(sample_dbc: Path) -> None:
    with pytest.raises(ValueError, match="Invalid data_hex"):
        tools.decode_frame(str(sample_dbc), 500, "not-hex")
    with pytest.raises(ValueError, match="Cannot decode frame 0x7FF"):
        tools.decode_frame(str(sample_dbc), 0x7FF, "00")


def test_validate_dbc_returns_structured_and_truncated_issues(invalid_dbc: Path) -> None:
    result = tools.validate_dbc(str(invalid_dbc), limit=2)
    capped = tools.validate_dbc(str(invalid_dbc), limit=99_999)

    assert result["total"] == 3
    assert result["returned"] == 2
    assert result["truncated"] is True
    assert set(result["issues"][0]) == {"severity", "code", "location", "message"}
    assert capped["limit"] == tools.MAX_LIST_LIMIT


def test_diff_dbcs_summarizes_message_and_signal_changes(sample_dbc: Path, changed_dbc: Path) -> None:
    result = tools.diff_dbcs(str(sample_dbc), str(changed_dbc))

    assert result["summary"] == {"added_messages": 1, "removed_messages": 1, "changed_messages": 2}
    assert result["truncated"] is False
    assert result["added_messages"][0]["name"] == "GatewayStatus"
    assert result["removed_messages"][0]["name"] == "TransportData"
    engine = next(item for item in result["changed_messages"] if item["name"] == "EngineData")
    assert engine["signal_diff_total"] == 2
    assert engine["added_signals"][0]["name"] == "OilPressure"
    changed_speed = engine["changed_signals"][0]
    assert changed_speed["name"] == "EngineSpeed"
    assert changed_speed["changes"]["factor"] == {"before": 0.125, "after": 0.25}
    vehicle = next(item for item in result["changed_messages"] if item["name"] == "VehicleStatus")
    assert vehicle["field_changes"]["name"] == {"before": "VehicleStatus", "after": "VehicleState"}


def test_diff_dbcs_reports_bounded_categories(sample_dbc: Path, changed_dbc: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools, "MAX_DIFF_MESSAGES", 0)

    result = tools.diff_dbcs(str(sample_dbc), str(changed_dbc))

    assert result["truncated"] is True
    assert result["added_messages"] == []
    assert result["changed_messages"] == []


def test_diff_dbcs_bounds_per_message_signal_changes(
    sample_dbc: Path,
    changed_dbc: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tools, "MAX_DIFF_SIGNALS_PER_MESSAGE", 1)

    result = tools.diff_dbcs(str(sample_dbc), str(changed_dbc))
    engine = next(item for item in result["changed_messages"] if item["name"] == "EngineData")

    assert result["truncated"] is True
    assert engine["signals_truncated"] is True
    assert len(engine["added_signals"]) == 1
    assert engine["changed_signals"] == []


def test_parsed_database_cache_uses_path_and_mtime(
    sample_dbc: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied = tmp_path / "sample.dbc"
    copied.write_bytes(sample_dbc.read_bytes())
    real_load = tools.dbckit.load
    calls: list[str] = []

    def counting_load(path: str) -> tools.Database:
        calls.append(path)
        return real_load(path)

    monkeypatch.setattr(tools.dbckit, "load", counting_load)
    tools.dbc_info(str(copied))
    tools.list_messages(str(copied))
    assert len(calls) == 1

    current = copied.stat()
    os.utime(copied, ns=(current.st_atime_ns, current.st_mtime_ns + 1_000_000))
    tools.dbc_info(str(copied))
    assert len(calls) == 2


def test_missing_directory_and_garbage_dbc_errors(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="DBC file not found"):
        tools.dbc_info(str(tmp_path / "missing.dbc"))
    with pytest.raises(ValueError, match="DBC path is not a file"):
        tools.dbc_info(str(tmp_path))

    garbage = tmp_path / "garbage.dbc"
    garbage.write_text("not a dbc", encoding="utf-8")
    with pytest.raises(UnparseableInputError, match="Cannot parse DBC file") as captured:
        tools.dbc_info(str(garbage))

    error = captured.value
    assert error.to_payload() == {
        "code": "unparseable_dbc",
        "message": error.message,
        "retryable": False,
        "recommended_action": (
            "Report this failure and request a valid DBC export; "
            "do not rewrite, clean, convert, or copy the input."
        ),
    }
    assert str(garbage.resolve()) in error.message


@pytest.mark.parametrize("value", ["", "xyz", "0xxyz", -1])
def test_invalid_arbitration_ids_are_useful(value: str | int) -> None:
    with pytest.raises(ValueError, match="Arbitration ID|arbitration ID"):
        tools._parse_arbitration_id(value)


def test_json_value_normalizes_common_models() -> None:
    class Choice(Enum):
        on = "on"

    assert tools._json_value({1: [Choice.on, b"\x01", Path("x")]}) == {"1": ["on", "01", "x"]}
