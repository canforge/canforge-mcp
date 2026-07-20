from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

from canforge_mcp import tools
from canforge_mcp.errors import UnparseableInputError


def _write_candump(path: Path, frames: list[tuple[float, int, bytes]]) -> Path:
    path.write_text(
        "".join(
            f"({timestamp:.6f}) can0 "
            f"{arbitration_id:08X}#{data.hex().upper()} R\n"
            if arbitration_id > 0x7FF
            else f"({timestamp:.6f}) can0 {arbitration_id:03X}#{data.hex().upper()} R\n"
            for timestamp, arbitration_id, data in frames
        ),
        encoding="ascii",
    )
    return path


def _write_mux_dbc(path: Path) -> Path:
    path.write_text(
        '''VERSION ""
NS_ :
BS_ :
BU_ : ECU
BO_ 200 MuxMessage: 2 ECU
 SG_ Selector M : 0|4@1+ (1,0) [0|15] "" ECU
 SG_ Common : 4|4@1+ (1,0) [0|15] "count" ECU
 SG_ First m0 : 8|8@1+ (1,0) [0|255] "A" ECU
 SG_ Second m1 : 8|8@1+ (1,0) [0|255] "B" ECU
VAL_ 200 Selector 0 "Zero" 1 "One" ;
VAL_ 200 First 42 "Answer" ;
''',
        encoding="utf-8",
    )
    return path


def _write_j1939_dbc(path: Path, *, ambiguous: bool = False) -> Path:
    second = '''BO_ 2565866498 EngineVariant: 8 ECU
 SG_ OtherValue : 0|8@1+ (1,0) [0|255] "" ECU
BA_ "PGN" BO_ 418382850 61444;
''' if ambiguous else ""
    path.write_text(
        f'''VERSION ""
NS_ :
BS_ :
BU_ : ECU
BA_DEF_ BO_ "PGN" INT 0 262143;
BO_ 2565866497 EngineData: 8 ECU
 SG_ Value : 0|8@1+ (1,0) [0|255] "" ECU
BA_ "PGN" BO_ 418382849 61444;
{second}''',
        encoding="utf-8",
    )
    return path


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

    with pytest.raises(UnparseableInputError, match=r"Available formats: .*candump") as captured:
        tools.probe_log(str(garbage))

    assert captured.value.code == "unparseable_log"
    assert captured.value.retryable is False


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


def test_log_signal_inventory_summarizes_one_pass_exact_matches(
    sample_dbc: Path,
    candump_log: Path,
) -> None:
    result = tools.log_signal_inventory(str(sample_dbc), str(candump_log))

    assert result["log_format"] == "candump"
    assert result["frame_count"] == 300
    assert result["duration"] == pytest.approx(0.5894511)
    assert result["unique_id_count"] == 66
    assert result["matched_id_count"] == 1
    assert result["unmatched_id_count"] == 65
    assert result["ambiguity_count"] == 0
    assert result["match_mode_requested"] == "auto"
    assert result["match_modes_used"] == ["exact"]
    assert result["dbc_decode_safe"] is True
    assert result["diagnostic_count"] == 0
    assert result["truncated"] is False

    matched = result["matched_ids"][0]
    assert matched == {
        "id": "0xCFBFFDB",
        "frame_count": 59,
        "message_id": "0xCFBFFDB",
        "message": "EngineData",
        "match_mode": "exact",
    }
    message = result["messages"][0]
    assert message["frame_count"] == 59
    assert message["decode_safe"] is True
    assert message["observed_signal_count"] == 3
    assert [signal["name"] for signal in message["signals"]] == ["EngineSpeed", "CoolantTemp", "Gear"]
    gear = message["signals"][-1]
    assert gear["value_labels"] == {"0": "Neutral", "1": "First", "2": "Second", "3": "Third"}
    assert "observed_values" not in gear


def test_log_signal_inventory_handles_supported_log_without_frames(sample_dbc: Path, tmp_path: Path) -> None:
    empty = tmp_path / "empty.asc"
    empty.write_text("base hex  timestamps absolute\n", encoding="ascii")

    result = tools.log_signal_inventory(str(sample_dbc), str(empty))

    assert result["log_format"] == "vector-asc"
    assert result["frame_count"] == 0
    assert result["first_timestamp"] is None
    assert result["last_timestamp"] is None
    assert result["duration"] is None
    assert result["unique_ids"] == []
    assert result["match_modes_used"] == []


def test_log_signal_inventory_collects_values_and_mux_selectors(tmp_path: Path) -> None:
    dbc = _write_mux_dbc(tmp_path / "mux.dbc")
    log = _write_candump(
        tmp_path / "mux.log",
        [
            (1.0, 200, bytes.fromhex("202A")),
            (2.0, 200, bytes.fromhex("2107")),
            (3.0, 200, bytes.fromhex("202A")),
        ],
    )

    result = tools.log_signal_inventory(str(dbc), str(log), include_values=True)

    message = result["messages"][0]
    assert message["defined_signal_count"] == 4
    assert message["observed_signal_count"] == 4
    assert [signal["name"] for signal in message["signals"]] == ["Selector", "Common", "First", "Second"]
    selector = message["signals"][0]
    assert selector["observed_values"] == ["Zero", "One"]
    assert selector["value_labels"] == {"0": "Zero", "1": "One"}
    first = message["signals"][2]
    assert first["observed_values"] == ["Answer"]
    assert message["multiplexers"] == [
        {
            "signal": "Selector",
            "observed_values": [
                {"selector": 0, "value": 0.0, "label": "Zero"},
                {"selector": 1, "value": 1.0, "label": "One"},
            ],
            "returned_values": 2,
            "values_truncated": False,
        }
    ]


def test_log_signal_inventory_reports_exact_and_j1939_auto_matches(tmp_path: Path) -> None:
    dbc = _write_j1939_dbc(tmp_path / "j1939.dbc")
    log = _write_candump(
        tmp_path / "j1939.log",
        [
            (1.0, 0x0CF004AB, b"\x2a" + b"\x00" * 7),
            (2.0, 0x18F00401, b"\x2b" + b"\x00" * 7),
        ],
    )

    result = tools.log_signal_inventory(str(dbc), str(log))

    assert result["match_modes_used"] == ["exact", "j1939"]
    assert [(item["id"], item["match_mode"]) for item in result["matched_ids"]] == [
        ("0xCF004AB", "j1939"),
        ("0x18F00401", "exact"),
    ]
    assert result["messages"][0]["frame_count"] == 2
    assert result["messages"][0]["source_id_count"] == 2

    forced = tools.log_signal_inventory(str(dbc), str(log), match_mode="j1939")
    assert forced["match_modes_used"] == ["j1939"]
    assert {item["match_mode"] for item in forced["matched_ids"]} == {"j1939"}

    exact = tools.log_signal_inventory(str(dbc), str(log), match_mode="exact")
    assert exact["match_modes_used"] == ["exact"]
    assert exact["matched_id_count"] == 1
    assert exact["unmatched_id_count"] == 1


def test_log_signal_inventory_keeps_ambiguous_j1939_matches_explicit(tmp_path: Path) -> None:
    dbc = _write_j1939_dbc(tmp_path / "ambiguous.dbc", ambiguous=True)
    log = _write_candump(
        tmp_path / "ambiguous.log",
        [(1.0, 0x0CF004AB, b"\x2a" + b"\x00" * 7)],
    )

    result = tools.log_signal_inventory(str(dbc), str(log))

    assert result["matched_id_count"] == 0
    assert result["unmatched_id_count"] == 0
    assert result["ambiguity_count"] == 1
    assert result["ambiguous_frame_count"] == 1
    assert result["match_modes_used"] == ["j1939"]
    ambiguity = result["ambiguities"][0]
    assert ambiguity["id"] == "0xCF004AB"
    assert [candidate["message"] for candidate in ambiguity["candidates"]] == [
        "EngineData",
        "EngineVariant",
    ]


def test_log_signal_inventory_surfaces_lenient_diagnostics_and_safety(tmp_path: Path) -> None:
    dbc = tmp_path / "degraded.dbc"
    dbc.write_text(
        '''VERSION ""
NS_ :
BS_ :
BU_ : ECU
BO_ 100 ExtendedMux: 8 ECU
 SG_ Kept : 0|8@1+ (1,0) [0|255] "" ECU
 SG_ Variant m0M : 8|8@1+ (1,0) [0|255] "" ECU
CM_ SG_ 100 Missing "dangling";
SG_MUL_VAL_ 100 Kept Kept 0-1;
''',
        encoding="utf-8",
    )
    log = _write_candump(tmp_path / "degraded.log", [(1.0, 100, b"\x2a" + b"\x00" * 7)])

    result = tools.log_signal_inventory(str(dbc), str(log))

    assert result["dbc_decode_safe"] is False
    assert result["diagnostic_count"] == 3
    assert [item["construct"] for item in result["parse_diagnostics"]] == ["SG_", "CM_", "SG_MUL_VAL_"]
    assert result["parse_diagnostics"][0]["message_id"] == "0x64"
    message = result["messages"][0]
    assert message["decode_safe"] is False
    assert [signal["name"] for signal in message["signals"]] == ["Kept"]
    with pytest.raises(UnparseableInputError, match="Cannot parse DBC file") as captured:
        tools.dbc_info(str(dbc))
    assert captured.value.code == "unparseable_dbc"


def test_log_signal_inventory_maps_terminal_lenient_dbc_parse_failure(
    tmp_path: Path,
    candump_log: Path,
) -> None:
    garbage = tmp_path / "garbage.dbc"
    garbage.write_text("not a dbc", encoding="utf-8")

    with pytest.raises(UnparseableInputError) as captured:
        tools.log_signal_inventory(str(garbage), str(candump_log))

    assert captured.value.code == "unparseable_dbc"
    assert captured.value.retryable is False


def test_log_signal_inventory_parses_and_scans_only_once(
    sample_dbc: Path,
    candump_log: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_load = tools.dbckit.load
    real_read = tools.capkit.read
    load_calls = 0
    read_calls = 0

    def counting_load(path: str, **kwargs: object) -> tools.Database:
        nonlocal load_calls
        load_calls += 1
        return real_load(path, **kwargs)

    def counting_read(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal read_calls
        read_calls += 1
        return real_read(*args, **kwargs)

    monkeypatch.setattr(tools.dbckit, "load", counting_load)
    monkeypatch.setattr(tools.capkit, "read", counting_read)

    tools.log_signal_inventory(str(sample_dbc), str(candump_log))

    assert load_calls == 1
    assert read_calls == 1


def test_log_signal_inventory_reports_nested_truncation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dbc = _write_mux_dbc(tmp_path / "bounded.dbc")
    with dbc.open("a", encoding="utf-8") as handle:
        handle.write(
            '''BO_ 201 OtherMessage: 1 ECU
 SG_ Other : 0|8@1+ (1,0) [0|255] "" ECU
'''
        )
    log = _write_candump(
        tmp_path / "bounded.log",
        [
            (1.0, 200, bytes.fromhex("202A")),
            (2.0, 200, bytes.fromhex("2107")),
            (3.0, 201, b"\x01"),
            (4.0, 300, b"\x00"),
            (5.0, 301, b"\x00"),
        ],
    )
    monkeypatch.setattr(tools, "MAX_INVENTORY_IDS", 1)
    monkeypatch.setattr(tools, "MAX_INVENTORY_MESSAGES", 1)
    monkeypatch.setattr(tools, "MAX_SIGNALS_PER_MESSAGE", 1)
    monkeypatch.setattr(tools, "MAX_INVENTORY_VALUES_PER_SIGNAL", 1)
    monkeypatch.setattr(tools, "MAX_INVENTORY_VALUE_LABELS_PER_SIGNAL", 1)
    monkeypatch.setattr(tools, "MAX_INVENTORY_MUX_VALUES", 1)

    result = tools.log_signal_inventory(str(dbc), str(log), include_values=True)

    assert result["truncated"] is True
    assert result["unique_ids_truncated"] is True
    assert result["matched_ids_truncated"] is True
    assert result["unmatched_ids_truncated"] is True
    assert result["messages_truncated"] is True
    message = result["messages"][0]
    assert message["signals_truncated"] is True
    selector = message["signals"][0]
    assert selector["value_labels_truncated"] is True
    assert selector["values_truncated"] is True
    assert message["multiplexers"][0]["values_truncated"] is True


def test_log_signal_inventory_bounds_diagnostics_and_ambiguity_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dbc = _write_j1939_dbc(tmp_path / "ambiguous.dbc", ambiguous=True)
    with dbc.open("a", encoding="utf-8") as handle:
        handle.write('CM_ SG_ 418382849 Missing "dangling";\n')
        handle.write('CM_ SG_ 418382850 Missing "dangling";\n')
    log = _write_candump(
        tmp_path / "ambiguous.log",
        [(1.0, 0x0CF004AB, b"\x2a" + b"\x00" * 7)],
    )
    monkeypatch.setattr(tools, "MAX_INVENTORY_MESSAGES", 1)
    monkeypatch.setattr(tools, "MAX_INVENTORY_DIAGNOSTICS", 1)

    result = tools.log_signal_inventory(str(dbc), str(log))

    assert result["truncated"] is True
    assert result["diagnostic_count"] == 2
    assert result["returned_diagnostics"] == 1
    assert result["diagnostics_truncated"] is True
    ambiguity = result["ambiguities"][0]
    assert ambiguity["candidate_count"] == 2
    assert ambiguity["returned_candidates"] == 1
    assert ambiguity["candidates_truncated"] is True
    assert result["ambiguities_truncated"] is True


def test_log_signal_inventory_rejects_bad_modes_and_maps_decoder_errors(
    sample_dbc: Path,
    candump_log: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="match_mode"):
        tools.log_signal_inventory(str(sample_dbc), str(candump_log), match_mode="bad")  # type: ignore[arg-type]

    def fail_decode(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        raise RuntimeError("decoder failed")

    monkeypatch.setattr(tools.dbckit, "decode_frames", fail_decode)
    with pytest.raises(ValueError, match="Cannot inventory log file.*decoder failed"):
        tools.log_signal_inventory(str(sample_dbc), str(candump_log))


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

    with pytest.raises(UnparseableInputError, match="Cannot parse log file") as captured:
        tools.read_frames(str(garbage))

    assert captured.value.to_payload() == {
        "code": "unparseable_log",
        "message": captured.value.message,
        "retryable": False,
        "recommended_action": (
            "Report this failure and request a valid CAN log export; "
            "do not rewrite, clean, convert, or copy the input."
        ),
    }


def test_read_frames_maps_lazy_malformed_record_error(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.txt"
    malformed.write_text(
        "Chn Identifier Flg   DLC  D0...1...2...3...4...5...6..D7       Time     Dir\n"
        " 0    123             1  01       1.000000 R\n"
        " 0    123             2  01       2.000000 R\n",
        encoding="ascii",
    )

    with pytest.raises(UnparseableInputError, match=r"DLC 2 declares 2 data bytes, got 1") as captured:
        tools.read_frames(str(malformed))

    assert captured.value.code == "unparseable_log"
    assert captured.value.retryable is False


def test_reader_registry_failure_is_not_classified_as_unparseable(
    candump_log: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_read(*args: object, **kwargs: object) -> object:
        raise RuntimeError("reader plugin failed")

    monkeypatch.setattr(tools.capkit, "read", fail_read)

    with pytest.raises(ValueError, match="Cannot read log file.*reader plugin failed") as captured:
        tools.read_frames(str(candump_log))

    assert not isinstance(captured.value, UnparseableInputError)


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


def test_decode_log_decodes_only_bounded_sample(
    sample_dbc: Path,
    candump_log: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_decode_frames = tools.dbckit.decode_frames
    decoded_inputs: list[tools.FrameLike] = []

    def tracking_decode_frames(
        database: tools.Database,
        frames: Iterable[tools.FrameLike],
    ) -> object:
        sample = list(frames)
        decoded_inputs.extend(sample)
        return real_decode_frames(database, sample)

    monkeypatch.setattr(tools.dbckit, "decode_frames", tracking_decode_frames)

    result = tools.decode_log(str(sample_dbc), str(candump_log), limit=2)

    assert result["total"] == 59
    assert result["returned"] == 2
    assert len(decoded_inputs) == 2


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
