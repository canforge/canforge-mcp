"""Execute one benchmark case in an isolated process and emit JSON."""

from __future__ import annotations

import argparse
import gc
import json
import math
import platform
import resource
import time
import tracemalloc
from typing import Any

from canforge_mcp import tools


def _peak_rss_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if platform.system() == "Darwin" else peak * 1_024)


def _invoke(case: dict[str, Any]) -> dict[str, Any]:
    tool = case["tool"]
    arguments = case["arguments"]
    dbc_path = case.get("dbc_path")
    log_path = case["log_path"]
    if tool == "log_stats":
        return tools.log_stats(log_path, **arguments)
    if tool == "decode_log":
        return tools.decode_log(dbc_path, log_path, **arguments)
    if tool == "log_signal_inventory":
        return tools.log_signal_inventory(dbc_path, log_path, **arguments)
    if tool == "signal_timeseries":
        return tools.signal_timeseries(dbc_path, log_path, **arguments)
    raise ValueError(f"Unknown benchmark tool: {tool!r}")


def _inventory_summary(result: dict[str, Any]) -> dict[str, Any]:
    returned_values = [
        signal["returned_values"]
        for message in result["messages"]
        for signal in message["signals"]
        if "returned_values" in signal
    ]
    value_truncations = [
        signal["values_truncated"]
        for message in result["messages"]
        for signal in message["signals"]
        if "values_truncated" in signal
    ]
    returned_mux_values = [
        multiplexer["returned_values"]
        for message in result["messages"]
        for multiplexer in message["multiplexers"]
    ]
    mux_truncations = [
        multiplexer["values_truncated"]
        for message in result["messages"]
        for multiplexer in message["multiplexers"]
    ]
    return {
        "frame_count": result["frame_count"],
        "unique_id_count": result["unique_id_count"],
        "matched_id_count": result["matched_id_count"],
        "unmatched_id_count": result["unmatched_id_count"],
        "message_count": result["message_count"],
        "include_values": bool(returned_values),
        "max_returned_values_per_signal": max(returned_values, default=0),
        "value_collection_truncated": any(value_truncations),
        "max_returned_mux_values": max(returned_mux_values, default=0),
        "mux_collection_truncated": any(mux_truncations),
        "truncated": result["truncated"],
    }


def _summarize(case: dict[str, Any], result: dict[str, Any]) -> tuple[dict[str, Any], dict[str, bool]]:
    tool = case["tool"]
    expected_total = case["expected_total"]
    if tool == "log_stats":
        summary = {
            key: result[key]
            for key in ("frame_count", "unique_id_count", "returned", "truncated", "top")
        }
        invariants = {
            "exact_total": result["frame_count"] == expected_total,
            "top_cap_honored": result["returned"] <= result["top"],
        }
        return summary, invariants

    if tool == "decode_log":
        summary = {key: result[key] for key in ("total", "returned", "truncated", "limit")}
        invariants = {
            "exact_total": result["total"] == expected_total,
            "sample_bounded": result["returned"] <= result["limit"],
            "exact_returned": result["returned"] == min(expected_total, result["limit"]),
            "truncation_exact": result["truncated"] is (expected_total > result["limit"]),
        }
        return summary, invariants

    if tool == "log_signal_inventory":
        summary = _inventory_summary(result)
        include_values = case["arguments"]["include_values"]
        invariants = {
            "exact_total": result["frame_count"] == expected_total,
            "retained_values_bounded": summary["max_returned_values_per_signal"]
            <= tools.MAX_INVENTORY_VALUES_PER_SIGNAL,
            "retained_mux_values_bounded": summary["max_returned_mux_values"]
            <= tools.MAX_INVENTORY_MUX_VALUES,
            "value_cap_exercised": (not include_values) or summary["value_collection_truncated"],
            "mux_cap_exercised": summary["mux_collection_truncated"],
        }
        return summary, invariants

    if tool == "signal_timeseries":
        summary = {
            key: result[key]
            for key in ("total", "returned", "truncated", "max_points")
        }
        summary["first_point"] = result["points"][0] if result["points"] else None
        summary["last_point"] = result["points"][-1] if result["points"] else None
        first_timestamp = summary["first_point"][0] if summary["first_point"] else None
        last_timestamp = summary["last_point"][0] if summary["last_point"] else None
        expected_first = case["expected_first_timestamp"]
        expected_last = case["expected_last_timestamp"]
        def close(left: float, right: float) -> bool:
            return math.isclose(left, right, rel_tol=0.0, abs_tol=1e-6)

        invariants = {
            "exact_total": result["total"] == expected_total,
            "point_cap_honored": result["returned"] <= result["max_points"],
            "exact_returned": result["returned"] == min(expected_total, result["max_points"]),
            "first_point_preserved": first_timestamp is not None and close(first_timestamp, expected_first),
            "last_point_preserved": last_timestamp is not None and close(last_timestamp, expected_last),
        }
        return summary, invariants

    raise AssertionError(tool)


def execute(case: dict[str, Any]) -> dict[str, Any]:
    tools.clear_dbc_cache()
    gc.collect()
    rss_before = _peak_rss_bytes()
    tracemalloc.start()
    started = time.perf_counter()
    result = _invoke(case)
    wall_time = time.perf_counter() - started
    _, python_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    rss_after = _peak_rss_bytes()
    summary, invariants = _summarize(case, result)
    return {
        "measurement": {
            "wall_time_seconds": wall_time,
            "python_peak_bytes": python_peak,
            "peak_rss_bytes": rss_after,
            "peak_rss_delta_bytes": max(0, rss_after - rss_before),
            "rss_before_bytes": rss_before,
        },
        "result": summary,
        "invariants": invariants,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-json", required=True)
    args = parser.parse_args()
    print(json.dumps(execute(json.loads(args.case_json)), separators=(",", ":")))


if __name__ == "__main__":
    main()
