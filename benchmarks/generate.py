"""Generate deterministic candump inputs for the benchmark suite."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Final, Literal

Profile = Literal["sparse", "dense"]

GENERATOR_VERSION: Final = 1
SEED: Final = 0xCF014
START_TIMESTAMP_US: Final = 1_700_000_000_000_000
CADENCE_US: Final = 1_000
PROFILE_PERIOD: Final = 100
SMOKE_FRAME_COUNT: Final = 10_000
FULL_FRAME_COUNTS: Final = (100_000, 1_000_000)

ENGINE_ID: Final = 0x0CFBFFDB
TRANSPORT_ID: Final = 0x18EBFF00
VEHICLE_ID: Final = 0x1F4
MUX_ID: Final = 0x321
MATCHED_IDS: Final = frozenset((ENGINE_ID, TRANSPORT_ID, VEHICLE_ID, MUX_ID))
UNMATCHED_IDS: Final = tuple(range(0x600, 0x608))
BENCHMARK_DBC: Final = Path(__file__).parent / "fixtures" / "benchmark.dbc"


def _arbitration_id(profile: Profile, index: int) -> int:
    position = index % PROFILE_PERIOD
    cycle = index // PROFILE_PERIOD
    if profile == "sparse":
        if position < 4:
            return (ENGINE_ID, TRANSPORT_ID, VEHICLE_ID, MUX_ID)[position]
        return UNMATCHED_IDS[(cycle * 96 + position - 4) % len(UNMATCHED_IDS)]
    if profile == "dense":
        if position < 70:
            return ENGINE_ID
        if position < 80:
            return VEHICLE_ID
        if position < 90:
            return TRANSPORT_ID
        if position < 95:
            return MUX_ID
        return UNMATCHED_IDS[(cycle * 5 + position - 95) % len(UNMATCHED_IDS)]
    raise ValueError(f"Unknown benchmark profile: {profile!r}")


def _payload(arbitration_id: int, occurrence: int, index: int) -> bytes:
    value = (occurrence + SEED) % 64
    if arbitration_id == ENGINE_ID:
        speed_raw = value
        coolant_raw = (value * 3) % 64
        return speed_raw.to_bytes(2, "little") + bytes((coolant_raw, value % 4, 0, 0, 0, 0))
    if arbitration_id == TRANSPORT_ID:
        return bytes((value, (value * 5) % 256, 0, 0, 0, 0, 0, 0))
    if arbitration_id == VEHICLE_ID:
        speed_raw = value * 10
        return speed_raw.to_bytes(2, "little") + bytes((value % 2, 0, 0, 0, 0, 0))
    if arbitration_id == MUX_ID:
        return bytes((value, (value * 7) % 256, 0, 0, 0, 0, 0, 0))
    noise = (index * 1_103_515_245 + SEED) & ((1 << 64) - 1)
    return noise.to_bytes(8, "little")


def _line(index: int, arbitration_id: int, occurrence: int) -> str:
    timestamp_us = START_TIMESTAMP_US + index * CADENCE_US
    seconds, micros = divmod(timestamp_us, 1_000_000)
    width = 8 if arbitration_id > 0x7FF else 3
    payload = _payload(arbitration_id, occurrence, index).hex().upper()
    return f"({seconds}.{micros:06d}) can0 {arbitration_id:0{width}X}#{payload} R\n"


def capture_path(output_dir: Path, profile: Profile, frame_count: int) -> Path:
    return output_dir / f"{profile}-{frame_count}.log"


def generate_capture(path: Path, *, profile: Profile, frame_count: int) -> dict[str, object]:
    """Write one deterministic capture and return its manifest row."""
    if frame_count < 1:
        raise ValueError("frame_count must be at least 1")
    path.parent.mkdir(parents=True, exist_ok=True)
    occurrences: Counter[int] = Counter()
    digest = hashlib.sha256()
    buffered: list[str] = []
    with path.open("w", encoding="ascii", newline="") as handle:
        for index in range(frame_count):
            arbitration_id = _arbitration_id(profile, index)
            occurrence = occurrences[arbitration_id]
            occurrences[arbitration_id] += 1
            buffered.append(_line(index, arbitration_id, occurrence))
            if len(buffered) == 8_192:
                text = "".join(buffered)
                handle.write(text)
                digest.update(text.encode("ascii"))
                buffered.clear()
        if buffered:
            text = "".join(buffered)
            handle.write(text)
            digest.update(text.encode("ascii"))

    return {
        "file": path.name,
        "profile": profile,
        "frame_count": frame_count,
        "file_size_bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
        "matched_frame_count": sum(count for arbitration_id, count in occurrences.items() if arbitration_id in MATCHED_IDS),
        "engine_frame_count": occurrences[ENGINE_ID],
        "id_counts": {f"0x{arbitration_id:X}": count for arbitration_id, count in sorted(occurrences.items())},
    }


def generate_all(output_dir: Path, frame_counts: Iterable[int]) -> dict[str, object]:
    """Generate both profiles for every requested size and write a manifest."""
    captures = [
        generate_capture(capture_path(output_dir, profile, frame_count), profile=profile, frame_count=frame_count)
        for frame_count in frame_counts
        for profile in ("sparse", "dense")
    ]
    manifest: dict[str, object] = {
        "schema_version": 1,
        "generator_version": GENERATOR_VERSION,
        "seed": SEED,
        "start_timestamp_us": START_TIMESTAMP_US,
        "cadence_us": CADENCE_US,
        "profile_period": PROFILE_PERIOD,
        "dbc": str(BENCHMARK_DBC.relative_to(Path(__file__).parent)),
        "captures": captures,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def expected_count(profile: Profile, frame_count: int, arbitration_ids: frozenset[int]) -> int:
    """Return an exact expected count without generating a capture."""
    cycles, remainder = divmod(frame_count, PROFILE_PERIOD)
    period_count = sum(_arbitration_id(profile, index) in arbitration_ids for index in range(PROFILE_PERIOD))
    partial_count = sum(_arbitration_id(profile, index) in arbitration_ids for index in range(remainder))
    return cycles * period_count + partial_count


def expected_last_index(profile: Profile, frame_count: int, arbitration_id: int) -> int | None:
    """Return the final matching frame index for a standard periodic matched ID."""
    if frame_count < 1:
        return None
    final_cycle_start = ((frame_count - 1) // PROFILE_PERIOD) * PROFILE_PERIOD
    for index in range(frame_count - 1, final_cycle_start - 1, -1):
        if _arbitration_id(profile, index) == arbitration_id:
            return index
    for index in range(final_cycle_start - 1, -1, -1):
        if _arbitration_id(profile, index) == arbitration_id:
            return index
    return None


def timestamp_for_index(index: int) -> float:
    return (START_TIMESTAMP_US + index * CADENCE_US) / 1_000_000


def _parse_sizes(value: str) -> tuple[int, ...]:
    aliases = {"smoke": SMOKE_FRAME_COUNT, "100k": 100_000, "1m": 1_000_000}
    sizes: list[int] = []
    for raw in value.split(","):
        token = raw.strip().lower()
        size = aliases.get(token)
        if size is None:
            size = int(token.replace("_", ""))
        if size < 1:
            raise argparse.ArgumentTypeError("sizes must be positive")
        sizes.append(size)
    return tuple(dict.fromkeys(sizes))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "generated")
    parser.add_argument("--sizes", type=_parse_sizes, default=(SMOKE_FRAME_COUNT,))
    args = parser.parse_args()
    manifest = generate_all(args.output_dir.resolve(), args.sizes)
    for capture in manifest["captures"]:  # type: ignore[index]
        print(f"generated {capture['file']}: {capture['frame_count']} frames")


if __name__ == "__main__":
    main()
