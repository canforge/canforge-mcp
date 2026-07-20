from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import capkit
import pytest

from benchmarks import generate
from benchmarks.run import run_benchmarks, write_artifacts
from canforge_mcp import tools


@pytest.fixture(scope="module")
def benchmark_logs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    output_dir = tmp_path_factory.mktemp("benchmark-logs")
    generate.generate_all(output_dir, (generate.SMOKE_FRAME_COUNT,))
    return {
        profile: generate.capture_path(output_dir, profile, generate.SMOKE_FRAME_COUNT)
        for profile in ("sparse", "dense")
    }


def test_generated_capture_is_deterministic_and_has_expected_profiles(tmp_path: Path) -> None:
    first = generate.generate_capture(tmp_path / "first.log", profile="sparse", frame_count=1_000)
    second = generate.generate_capture(tmp_path / "second.log", profile="sparse", frame_count=1_000)
    dense = generate.generate_capture(tmp_path / "dense.log", profile="dense", frame_count=1_000)

    assert first["sha256"] == second["sha256"]
    assert first["matched_frame_count"] == 40
    assert first["engine_frame_count"] == 10
    assert dense["matched_frame_count"] == 950
    assert dense["engine_frame_count"] == 700
    assert sum(1 for _ in capkit.read(tmp_path / "first.log")) == 1_000


@pytest.mark.parametrize("limit", [1, 100, 500])
def test_benchmark_decode_work_is_bounded_by_effective_limit(
    benchmark_logs: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    limit: int,
) -> None:
    real_decode_frames = tools.dbckit.decode_frames
    decoded_input_count = 0

    def tracking_decode_frames(database: tools.Database, frames: Iterable[tools.FrameLike]) -> object:
        nonlocal decoded_input_count
        sample = list(frames)
        decoded_input_count += len(sample)
        return real_decode_frames(database, sample)

    monkeypatch.setattr(tools.dbckit, "decode_frames", tracking_decode_frames)
    result = tools.decode_log(
        str(generate.BENCHMARK_DBC),
        str(benchmark_logs["dense"]),
        limit=limit,
    )

    assert result["total"] == 9_500
    assert result["returned"] == limit
    assert result["truncated"] is True
    assert decoded_input_count == limit


def test_benchmark_inventory_scans_once_and_caps_retained_values(
    benchmark_logs: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_read = tools.capkit.read
    read_count = 0

    def tracking_read(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal read_count
        read_count += 1
        return real_read(*args, **kwargs)

    monkeypatch.setattr(tools.capkit, "read", tracking_read)
    result = tools.log_signal_inventory(
        str(generate.BENCHMARK_DBC),
        str(benchmark_logs["sparse"]),
        include_values=True,
    )

    signals = [signal for message in result["messages"] for signal in message["signals"]]
    multiplexers = [mux for message in result["messages"] for mux in message["multiplexers"]]
    assert read_count == 1
    assert result["frame_count"] == generate.SMOKE_FRAME_COUNT
    assert max(signal["returned_values"] for signal in signals) == tools.MAX_INVENTORY_VALUES_PER_SIGNAL
    assert any(signal["values_truncated"] for signal in signals)
    assert max(mux["returned_values"] for mux in multiplexers) == tools.MAX_INVENTORY_MUX_VALUES
    assert any(mux["values_truncated"] for mux in multiplexers)


@pytest.mark.parametrize(
    ("profile", "expected_total", "last_index"),
    [("sparse", 100, 9_900), ("dense", 7_000, 9_969)],
)
def test_benchmark_timeseries_preserves_ends_and_point_cap(
    benchmark_logs: dict[str, Path],
    profile: str,
    expected_total: int,
    last_index: int,
) -> None:
    result = tools.signal_timeseries(
        str(generate.BENCHMARK_DBC),
        str(benchmark_logs[profile]),
        "EngineData",
        "EngineSpeed",
        max_points=500,
    )

    assert result["total"] == expected_total
    assert result["returned"] == min(expected_total, 500)
    assert result["points"][0][0] == generate.timestamp_for_index(0)
    assert result["points"][-1][0] == generate.timestamp_for_index(last_index)


def test_smoke_benchmark_runs_full_matrix_and_writes_artifacts(tmp_path: Path) -> None:
    report = run_benchmarks(
        frame_counts=(generate.SMOKE_FRAME_COUNT,),
        generated_dir=tmp_path / "generated",
        warmups=0,
        repetitions=1,
    )
    json_path, markdown_path = write_artifacts(report, tmp_path / "results" / "smoke.json")

    assert len(report["cases"]) == 14
    assert all(all(case["invariants"].values()) for case in report["cases"])
    assert report["policy"]["timing_is_informational"] is True
    assert report["scaling"] == []
    assert json_path.is_file()
    assert markdown_path.is_file()
