"""Generate captures and run the canforge-mcp benchmark matrix."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import statistics
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmarks.generate import (
    BENCHMARK_DBC,
    ENGINE_ID,
    FULL_FRAME_COUNTS,
    MATCHED_IDS,
    SMOKE_FRAME_COUNT,
    Profile,
    capture_path,
    expected_count,
    expected_last_index,
    generate_all,
    timestamp_for_index,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GENERATED_DIR = Path(__file__).parent / "generated"
DEFAULT_RESULTS_DIR = Path(__file__).parent / "results"


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def _environment() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "os": platform.platform(),
        "machine": platform.machine(),
        "canforge_mcp": _package_version("canforge-mcp"),
        "capkit": _package_version("capkit"),
        "dbckit": _package_version("dbckit"),
    }


def _case_matrix(frame_counts: tuple[int, ...], generated_dir: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for frame_count in frame_counts:
        for profile in ("sparse", "dense"):
            typed_profile: Profile = profile
            log_path = capture_path(generated_dir, typed_profile, frame_count)
            matched_count = expected_count(typed_profile, frame_count, MATCHED_IDS)
            engine_count = expected_count(typed_profile, frame_count, frozenset((ENGINE_ID,)))
            base = {
                "profile": profile,
                "frame_count": frame_count,
                "log_path": str(log_path.resolve()),
                "input_size_bytes": log_path.stat().st_size,
            }
            cases.append(
                {
                    **base,
                    "name": f"log_stats.{profile}.{frame_count}.top20",
                    "tool": "log_stats",
                    "arguments": {"top": 20},
                    "expected_total": frame_count,
                }
            )
            for limit in (1, 100, 500):
                cases.append(
                    {
                        **base,
                        "name": f"decode_log.{profile}.{frame_count}.limit{limit}",
                        "tool": "decode_log",
                        "dbc_path": str(BENCHMARK_DBC.resolve()),
                        "arguments": {"limit": limit},
                        "expected_total": matched_count,
                    }
                )
            for include_values in (False, True):
                suffix = "values" if include_values else "no-values"
                cases.append(
                    {
                        **base,
                        "name": f"log_signal_inventory.{profile}.{frame_count}.{suffix}",
                        "tool": "log_signal_inventory",
                        "dbc_path": str(BENCHMARK_DBC.resolve()),
                        "arguments": {"include_values": include_values},
                        "expected_total": frame_count,
                    }
                )
            last_engine_index = expected_last_index(typed_profile, frame_count, ENGINE_ID)
            if last_engine_index is None:
                raise ValueError(f"{profile}/{frame_count} contains no EngineData frames")
            cases.append(
                {
                    **base,
                    "name": f"signal_timeseries.{profile}.{frame_count}.max500",
                    "tool": "signal_timeseries",
                    "dbc_path": str(BENCHMARK_DBC.resolve()),
                    "arguments": {
                        "message": "EngineData",
                        "signal": "EngineSpeed",
                        "max_points": 500,
                    },
                    "expected_total": engine_count,
                    "expected_first_timestamp": timestamp_for_index(0),
                    "expected_last_timestamp": timestamp_for_index(last_engine_index),
                }
            )
    return cases


def _run_worker(case: dict[str, Any]) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "benchmarks.worker", "--case-json", json.dumps(case, separators=(",", ":"))],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Benchmark worker failed for {case['name']}:\n{completed.stderr.strip()}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Benchmark worker returned invalid JSON for {case['name']}") from exc


def _median_metrics(measurements: list[dict[str, float]]) -> dict[str, float]:
    return {
        f"{name}_median": statistics.median(measurement[name] for measurement in measurements)
        for name in (
            "wall_time_seconds",
            "python_peak_bytes",
            "peak_rss_bytes",
            "peak_rss_delta_bytes",
            "rss_before_bytes",
        )
    }


def _scaling(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_signature: dict[tuple[str, str, str], dict[int, dict[str, Any]]] = {}
    for case in cases:
        signature = (case["tool"], case["profile"], json.dumps(case["arguments"], sort_keys=True))
        by_signature.setdefault(signature, {})[case["frame_count"]] = case

    rows: list[dict[str, Any]] = []
    for (tool, profile, arguments), sizes in sorted(by_signature.items()):
        if 100_000 not in sizes or 1_000_000 not in sizes:
            continue
        small = sizes[100_000]["metrics"]
        large = sizes[1_000_000]["metrics"]

        def ratio(name: str) -> float | None:
            denominator = small[name]
            return large[name] / denominator if denominator else None

        expected = (
            "bounded retained sample/state"
            if tool in ("decode_log", "log_signal_inventory")
            else "linear retained per-frame data"
        )
        rows.append(
            {
                "tool": tool,
                "profile": profile,
                "arguments": json.loads(arguments),
                "expected_characteristic": expected,
                "wall_time_ratio_1m_to_100k": ratio("wall_time_seconds_median"),
                "python_peak_ratio_1m_to_100k": ratio("python_peak_bytes_median"),
                "peak_rss_delta_ratio_1m_to_100k": ratio("peak_rss_delta_bytes_median"),
            }
        )
    return rows


def run_benchmarks(
    *,
    frame_counts: tuple[int, ...],
    generated_dir: Path,
    warmups: int,
    repetitions: int,
    progress: bool = False,
) -> dict[str, Any]:
    if warmups < 0:
        raise ValueError("warmups must not be negative")
    if repetitions < 1:
        raise ValueError("repetitions must be at least 1")
    manifest = generate_all(generated_dir, frame_counts)
    records: list[dict[str, Any]] = []
    for case in _case_matrix(frame_counts, generated_dir):
        if progress:
            print(f"running {case['name']}", flush=True)
        for _ in range(warmups):
            _run_worker(case)
        runs = [_run_worker(case) for _ in range(repetitions)]
        invariant_runs = [run["invariants"] for run in runs]
        failed = sorted(
            name
            for invariants in invariant_runs
            for name, passed in invariants.items()
            if not passed
        )
        if failed:
            raise RuntimeError(f"Structural invariant failed for {case['name']}: {', '.join(set(failed))}")
        measurements = [run["measurement"] for run in runs]
        records.append(
            {
                "name": case["name"],
                "tool": case["tool"],
                "profile": case["profile"],
                "frame_count": case["frame_count"],
                "input_file": Path(case["log_path"]).name,
                "input_size_bytes": case["input_size_bytes"],
                "arguments": case["arguments"],
                "result": runs[0]["result"],
                "invariants": invariant_runs[0],
                "measurements": measurements,
                "metrics": _median_metrics(measurements),
            }
        )
    return {
        "schema_version": 1,
        "baseline_target": "v0.2.0",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "environment": _environment(),
        "policy": {
            "process_isolation": "one tool/case/repetition per fresh subprocess",
            "wall_clock": "time.perf_counter",
            "python_allocations": "tracemalloc peak",
            "process_memory": "resource.getrusage peak RSS normalized to bytes",
            "warmups": warmups,
            "repetitions": repetitions,
            "timing_is_informational": True,
        },
        "fixture_manifest": manifest,
        "cases": records,
        "scaling": _scaling(records),
    }


def _format_arguments(arguments: dict[str, Any]) -> str:
    return ", ".join(f"{key}={str(value).lower() if isinstance(value, bool) else value}" for key, value in arguments.items())


def _mib(value: float) -> str:
    return f"{value / (1024 * 1024):.2f}"


def markdown_report(report: dict[str, Any]) -> str:
    environment = report["environment"]
    policy = report["policy"]
    lines = [
        "# canforge-mcp v0.2.0 benchmark baseline",
        "",
        f"Generated: `{report['generated_at_utc']}`  ",
        f"Environment: Python `{environment['python']}` ({environment['python_implementation']}), `{environment['os']}`, `{environment['machine']}`  ",
        f"Packages: canforge-mcp `{environment['canforge_mcp']}`, capkit `{environment['capkit']}`, dbckit `{environment['dbckit']}`  ",
        f"Policy: {policy['warmups']} warm-up(s), {policy['repetitions']} measured repetition(s); {policy['process_isolation']}. Timing and RSS are informational.",
        "",
        "## Results",
        "",
        "| Tool | Profile | Frames | Arguments | Wall (s) | Python peak (MiB) | Peak RSS (MiB) | RSS delta (MiB) | Output |",
        "|---|---:|---:|---|---:|---:|---:|---:|---|",
    ]
    for case in report["cases"]:
        metrics = case["metrics"]
        result = case["result"]
        total = result.get("total", result.get("frame_count"))
        returned = result.get("returned", result.get("message_count", "-"))
        lines.append(
            f"| `{case['tool']}` | {case['profile']} | {case['frame_count']:,} | "
            f"`{_format_arguments(case['arguments'])}` | {metrics['wall_time_seconds_median']:.4f} | "
            f"{_mib(metrics['python_peak_bytes_median'])} | {_mib(metrics['peak_rss_bytes_median'])} | "
            f"{_mib(metrics['peak_rss_delta_bytes_median'])} | total={total}, returned={returned} |"
        )

    lines.extend(
        [
            "",
            "## 1M / 100k scaling",
            "",
            "| Tool | Profile | Arguments | Wall ratio | Python peak ratio | RSS delta ratio | Expected characteristic |",
            "|---|---:|---|---:|---:|---:|---|",
        ]
    )
    for row in report["scaling"]:
        rss_ratio = row["peak_rss_delta_ratio_1m_to_100k"]
        lines.append(
            f"| `{row['tool']}` | {row['profile']} | `{_format_arguments(row['arguments'])}` | "
            f"{row['wall_time_ratio_1m_to_100k']:.2f}x | {row['python_peak_ratio_1m_to_100k']:.2f}x | "
            f"{f'{rss_ratio:.2f}x' if rss_ratio is not None else 'n/a'} | {row['expected_characteristic']} |"
        )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `decode_log` scans the full input for an exact `total`, but only stores and decodes up to its effective limit.",
            "- `log_signal_inventory` scans once and caps retained distinct signal and multiplexer values at 50 per signal.",
            "- `log_stats` currently retains every per-ID cycle-time delta; allocation therefore scales with the number of frames at fixed ID cardinality.",
            "- `signal_timeseries` currently retains every matching point before deterministic downsampling; dense-match allocation therefore scales with selected-signal occurrences.",
            "- No wall-time or memory number is a CI pass/fail threshold. Structural contracts are checked separately.",
            "",
        ]
    )
    return "\n".join(lines)


def write_artifacts(report: dict[str, Any], json_path: Path) -> tuple[Path, Path]:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path = json_path.with_suffix(".md")
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(markdown_report(report), encoding="utf-8")
    return json_path, markdown_path


def _parse_frame_counts(value: str) -> tuple[int, ...]:
    counts = tuple(int(token.strip().replace("_", "")) for token in value.split(","))
    if not counts or any(count < 1 for count in counts):
        raise argparse.ArgumentTypeError("frame counts must be positive")
    return tuple(dict.fromkeys(counts))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", choices=("smoke", "full"), default="smoke")
    parser.add_argument("--frames", type=_parse_frame_counts)
    parser.add_argument("--generated-dir", type=Path, default=DEFAULT_GENERATED_DIR)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--warmups", type=int, default=0)
    parser.add_argument("--repetitions", type=int, default=1)
    args = parser.parse_args()

    frame_counts = args.frames or ((SMOKE_FRAME_COUNT,) if args.preset == "smoke" else FULL_FRAME_COUNTS)
    output = args.output or DEFAULT_RESULTS_DIR / ("smoke-latest.json" if args.preset == "smoke" else "v0.2.0.json")
    report = run_benchmarks(
        frame_counts=frame_counts,
        generated_dir=args.generated_dir.resolve(),
        warmups=args.warmups,
        repetitions=args.repetitions,
        progress=True,
    )
    json_path, markdown_path = write_artifacts(report, output.resolve())
    print(f"wrote {json_path}")
    print(f"wrote {markdown_path}")


if __name__ == "__main__":
    main()
