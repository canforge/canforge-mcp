from __future__ import annotations

from pathlib import Path

import pytest

from canforge_mcp import tools


def test_probe_log_detects_candump_and_vector_metadata(candump_log: Path, asc_log: Path) -> None:
    candump = tools.probe_log(str(candump_log))
    asc = tools.probe_log(str(asc_log))

    assert candump["format"] == "candump"
    assert candump["start_time"] is None
    assert asc["format"] == "vector-asc"
    assert asc["start_time"].startswith("2017-09-30T15:06:13.191")


def test_probe_log_failure_lists_formats(tmp_path: Path) -> None:
    garbage = tmp_path / "capture.bin"
    garbage.write_text("not a CAN log", encoding="utf-8")

    with pytest.raises(ValueError, match=r"Available formats: .*candump"):
        tools.probe_log(str(garbage))


def test_log_stats_counts_span_and_cycle_time(candump_log: Path) -> None:
    result = tools.log_stats(str(candump_log), top=2)

    assert result["frame_count"] == 300
    assert result["unique_id_count"] == 66
    assert result["returned"] == 2
    assert result["truncated"] is True
    assert result["top_ids"][0]["id"] == "0xCFBFFDB"
    assert result["top_ids"][0]["count"] == 59
    assert result["top_ids"][0]["median_cycle_time"] == pytest.approx(0.0106039)
    assert result["time_span"] == pytest.approx(0.5894511)


def test_log_stats_caps_top_and_handles_single_frame(tmp_path: Path, candump_log: Path) -> None:
    capped = tools.log_stats(str(candump_log), top=99_999)
    one = tmp_path / "one.log"
    one.write_text(candump_log.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")
    single = tools.log_stats(str(one))

    assert capped["top"] == tools.MAX_LIST_LIMIT
    assert capped["truncated"] is False
    assert single["frame_count"] == 1
    assert single["time_span"] == 0.0
    assert single["top_ids"][0]["median_cycle_time"] is None


def test_log_stats_empty_log_returns_empty_shape(tmp_path: Path) -> None:
    empty = tmp_path / "empty.log"
    empty.write_text("# no frames\n", encoding="utf-8")

    result = tools.log_stats(str(empty))

    assert result["frame_count"] == 0
    assert result["start_timestamp"] is None
    assert result["end_timestamp"] is None
    assert result["time_span"] is None
    assert result["top_ids"] == []


def test_read_frames_filters_ids_and_time(candump_log: Path) -> None:
    result = tools.read_frames(
        str(candump_log),
        id_filter=["0xCFBFFDB"],
        time_start=1752624000.0,
        time_end=1752624000.02,
        limit=2,
    )

    assert result["total"] > 2
    assert result["returned"] == 2
    assert result["truncated"] is True
    assert {frame["id"] for frame in result["frames"]} == {"0xCFBFFDB"}
    assert result["frames"][0]["data_hex"] == "1B3120EBB3FFD9FF"
    assert result["frames"][0]["extended"] is True
    assert result["frames"][0]["rx"] is True


def test_read_frames_empty_filter_and_cap(candump_log: Path) -> None:
    empty = tools.read_frames(str(candump_log), id_filter=[])
    capped = tools.read_frames(str(candump_log), limit=99_999)

    assert empty["total"] == 0
    assert empty["frames"] == []
    assert capped["limit"] == tools.MAX_FRAME_LIMIT
    assert capped["returned"] == 300


def test_read_frames_hard_cap_reports_truncation(tmp_path: Path, candump_log: Path) -> None:
    first = candump_log.read_text(encoding="utf-8").splitlines()[0]
    large = tmp_path / "large.log"
    large.write_text("\n".join([first] * 501) + "\n", encoding="utf-8")

    result = tools.read_frames(str(large), limit=99_999)

    assert result["total"] == 501
    assert result["returned"] == tools.MAX_FRAME_LIMIT
    assert result["truncated"] is True


def test_read_frames_rejects_bad_filters_and_paths(candump_log: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="time_start"):
        tools.read_frames(str(candump_log), time_start=2.0, time_end=1.0)
    with pytest.raises(ValueError, match="Invalid arbitration ID"):
        tools.read_frames(str(candump_log), id_filter=["bad"])
    with pytest.raises(ValueError, match="limit must be at least 1"):
        tools.read_frames(str(candump_log), limit=0)
    with pytest.raises(ValueError, match="Log file not found"):
        tools.read_frames(str(tmp_path / "missing.log"))


def test_read_frames_maps_unknown_format_error(tmp_path: Path) -> None:
    garbage = tmp_path / "garbage.bin"
    garbage.write_text("not a log\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Cannot read log file"):
        tools.read_frames(str(garbage))


def test_decode_log_composes_capkit_and_dbckit(sample_dbc: Path, candump_log: Path) -> None:
    result = tools.decode_log(str(sample_dbc), str(candump_log), limit=2)

    assert result["total"] == 59
    assert result["returned"] == 2
    assert result["truncated"] is True
    first = result["frames"][0]
    assert first["message"] == "EngineData"
    assert first["signals"]["EngineSpeed"] == 1571.375
    assert first["signals"]["CoolantTemp"] == -8.0
    assert first["signal_count"] == 3
    assert first["signals_truncated"] is False


def test_decode_log_filters_by_name_id_and_intersection(sample_dbc: Path, candump_log: Path) -> None:
    by_name = tools.decode_log(str(sample_dbc), str(candump_log), messages=["EngineData"], limit=1)
    intersection = tools.decode_log(
        str(sample_dbc),
        str(candump_log),
        messages=["EngineData"],
        id_filter=["0x18EBFF00"],
    )

    assert by_name["total"] == 59
    assert by_name["frames"][0]["id"] == "0xCFBFFDB"
    assert intersection["total"] == 0


def test_decode_log_bounds_signal_maps(sample_dbc: Path, candump_log: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools, "MAX_SIGNALS_PER_MESSAGE", 1)

    result = tools.decode_log(str(sample_dbc), str(candump_log), limit=1)

    assert result["frames"][0]["signal_count"] == 3
    assert len(result["frames"][0]["signals"]) == 1
    assert result["frames"][0]["signals_truncated"] is True


def test_decode_log_caps_limit_and_rejects_unknown_message(sample_dbc: Path, candump_log: Path) -> None:
    capped = tools.decode_log(str(sample_dbc), str(candump_log), limit=99_999)
    assert capped["limit"] == tools.MAX_FRAME_LIMIT

    with pytest.raises(ValueError, match="No message named"):
        tools.decode_log(str(sample_dbc), str(candump_log), messages=["Missing"])


def test_signal_timeseries_decodes_and_downsamples(sample_dbc: Path, candump_log: Path) -> None:
    result = tools.signal_timeseries(
        str(sample_dbc),
        str(candump_log),
        "EngineData",
        "EngineSpeed",
        max_points=3,
    )

    assert result["message_id"] == "0xCFBFFDB"
    assert result["unit"] == "rpm"
    assert result["total"] == 59
    assert result["returned"] == 3
    assert result["truncated"] is True
    assert result["points"][0] == [1752624000.000139, 1571.375]
    assert result["points"][-1] == [1752624000.587478, 6425.875]


def test_signal_timeseries_time_filter_and_single_point(sample_dbc: Path, candump_log: Path) -> None:
    result = tools.signal_timeseries(
        str(sample_dbc),
        str(candump_log),
        "0xCFBFFDB",
        "EngineSpeed",
        time_end=1752624000.001,
        max_points=1,
    )

    assert result["total"] == 1
    assert result["returned"] == 1
    assert result["truncated"] is False


def test_signal_timeseries_caps_points(monkeypatch: pytest.MonkeyPatch, sample_dbc: Path, candump_log: Path) -> None:
    monkeypatch.setattr(tools, "MAX_POINT_LIMIT", 2)

    result = tools.signal_timeseries(
        str(sample_dbc),
        str(candump_log),
        "EngineData",
        "EngineSpeed",
        max_points=99_999,
    )

    assert result["max_points"] == 2
    assert result["returned"] == 2
    assert result["truncated"] is True


def test_signal_timeseries_rejects_unknown_signal_and_bad_window(sample_dbc: Path, candump_log: Path) -> None:
    with pytest.raises(ValueError, match="No signal"):
        tools.signal_timeseries(str(sample_dbc), str(candump_log), "EngineData", "Missing")
    with pytest.raises(ValueError, match="time_start"):
        tools.signal_timeseries(
            str(sample_dbc),
            str(candump_log),
            "EngineData",
            "EngineSpeed",
            time_start=2.0,
            time_end=1.0,
        )
    with pytest.raises(ValueError, match="max_points"):
        tools.signal_timeseries(str(sample_dbc), str(candump_log), "EngineData", "EngineSpeed", max_points=0)


def test_downsample_handles_unbounded_exact_and_one_point() -> None:
    points = [[0.0, 1], [1.0, 2], [2.0, 3]]

    assert tools._downsample(points, 5) is points
    assert tools._downsample(points, 1) == [[0.0, 1]]
    assert tools._downsample(points, 2) == [[0.0, 1], [2.0, 3]]
