"""Plain tool functions exposed by the canforge MCP server."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from enum import Enum
from functools import lru_cache
from pathlib import Path
from statistics import median
from typing import Any, cast

import capkit
import dbckit
from capkit import Frame
from dbckit import Database, FrameLike, Message, Signal

DEFAULT_LIST_LIMIT = 50
DEFAULT_FRAME_LIMIT = 100
DEFAULT_POINT_LIMIT = 500

MAX_LIST_LIMIT = 200
MAX_FRAME_LIMIT = 500
MAX_POINT_LIMIT = 2_000
MAX_SIGNALS_PER_MESSAGE = 200
MAX_DIFF_MESSAGES = 100
MAX_DIFF_SIGNALS_PER_MESSAGE = 100
MAX_NODE_NAMES = 200


def _effective_limit(value: int, *, maximum: int, name: str) -> int:
    if value < 1:
        raise ValueError(f"{name} must be at least 1.")
    return min(value, maximum)


def _checked_path(path: str, *, kind: str) -> tuple[Path, int]:
    source = Path(path).expanduser()
    try:
        stat = source.stat()
    except FileNotFoundError:
        raise ValueError(f"{kind} file not found: {source}") from None
    except OSError as exc:
        raise ValueError(f"Cannot access {kind.lower()} file '{source}': {exc}") from None
    if not source.is_file():
        raise ValueError(f"{kind} path is not a file: {source}")
    return source.resolve(), stat.st_mtime_ns


@lru_cache(maxsize=16)
def _load_dbc_cached(path: str, mtime_ns: int) -> Database:
    del mtime_ns
    return dbckit.load(path)


def _database(path: str) -> tuple[Path, Database]:
    source, mtime_ns = _checked_path(path, kind="DBC")
    try:
        return source, _load_dbc_cached(str(source), mtime_ns)
    except Exception as exc:
        raise ValueError(f"Cannot load DBC file '{source}': {exc}") from None


def clear_dbc_cache() -> None:
    """Clear the process-local parsed-DBC cache (primarily useful in tests)."""
    _load_dbc_cached.cache_clear()


def _hex_id(arbitration_id: int) -> str:
    return f"0x{arbitration_id:X}"


def _parse_arbitration_id(value: str | int) -> int:
    if isinstance(value, int):
        arbitration_id = value
    else:
        raw = value.strip()
        if not raw:
            raise ValueError("Arbitration ID must not be empty.")
        try:
            arbitration_id = int(raw, 0)
        except ValueError:
            if raw.lower().startswith("0x"):
                raise ValueError(f"Invalid arbitration ID: {value!r}") from None
            try:
                arbitration_id = int(raw, 10)
            except ValueError:
                raise ValueError(
                    f"Invalid arbitration ID {value!r}; use a decimal integer or 0x-prefixed hex value."
                ) from None
    if arbitration_id < 0:
        raise ValueError("Arbitration ID must not be negative.")
    return arbitration_id


def _resolve_message(db: Database, reference: str | int) -> Message:
    if isinstance(reference, str):
        query = reference.strip()
        matches = [message for message in db.messages.values() if message.name.casefold() == query.casefold()]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"Message name {reference!r} is ambiguous; use its arbitration ID.")
    try:
        arbitration_id = _parse_arbitration_id(reference)
    except ValueError:
        raise ValueError(f"No message named {reference!r} was found in the DBC.") from None
    message = db.messages.get(arbitration_id)
    if message is None:
        raise ValueError(f"No message with arbitration ID {_hex_id(arbitration_id)} was found in the DBC.")
    return message


def _message_summary(message: Message) -> dict[str, Any]:
    return {
        "id": _hex_id(message.arbitration_id),
        "name": message.name,
        "dlc": message.length,
        "senders": message.senders,
        "signal_count": len(message.signals),
    }


def _signal_detail(signal: Signal) -> dict[str, Any]:
    choices = None
    if signal.value_table is not None:
        choices = {str(value): label for value, label in sorted(signal.value_table.values.items())}
    return {
        "name": signal.name,
        "start_bit": signal.start_bit,
        "length": signal.length,
        "byte_order": signal.byte_order.value,
        "signed": signal.is_signed,
        "factor": signal.factor,
        "offset": signal.offset,
        "minimum": signal.minimum,
        "maximum": signal.maximum,
        "unit": signal.unit,
        "choices": choices,
        "receivers": signal.receivers,
        "multiplex": signal.multiplex_indicator,
        "comment": signal.comment,
    }


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bytes):
        return value.hex().upper()
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "model_dump"):
        return _json_value(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _signal_changes(before: Signal, after: Signal) -> dict[str, dict[str, Any]]:
    before_values = before.model_dump(mode="json")
    after_values = after.model_dump(mode="json")
    return {
        field: {"before": _json_value(before_values[field]), "after": _json_value(after_values[field])}
        for field in before_values
        if before_values[field] != after_values[field]
    }


def _id_filter(values: list[str | int] | None) -> set[int] | None:
    if values is None:
        return None
    return {_parse_arbitration_id(value) for value in values}


def _message_filter(db: Database, values: list[str | int] | None) -> set[int] | None:
    if values is None:
        return None
    return {_resolve_message(db, value).arbitration_id for value in values}


def _combined_filter(
    db: Database,
    messages: list[str | int] | None,
    id_filter: list[str | int] | None,
) -> set[int] | None:
    message_ids = _message_filter(db, messages)
    requested_ids = _id_filter(id_filter)
    if message_ids is None:
        return requested_ids
    if requested_ids is None:
        return message_ids
    return message_ids & requested_ids


def _validate_time_window(time_start: float | None, time_end: float | None) -> None:
    if time_start is not None and time_end is not None and time_start > time_end:
        raise ValueError("time_start must be less than or equal to time_end.")


def _filtered_frames(
    path: Path,
    *,
    ids: set[int] | None,
    time_start: float | None,
    time_end: float | None,
) -> Iterator[Frame]:
    try:
        frames = capkit.read(path)
        for frame in frames:
            if ids is not None and frame.arbitration_id not in ids:
                continue
            if time_start is not None and frame.timestamp < time_start:
                continue
            if time_end is not None and frame.timestamp > time_end:
                continue
            yield frame
    except Exception as exc:
        raise ValueError(f"Cannot read log file '{path}': {exc}") from None


def _frame_row(frame: Frame) -> dict[str, Any]:
    return {
        "timestamp": frame.timestamp,
        "id": _hex_id(frame.arbitration_id),
        "data_hex": frame.data.hex().upper(),
        "channel": frame.channel,
        "extended": frame.is_extended_frame,
        "fd": frame.is_fd,
        "remote": frame.is_remote_frame,
        "error": frame.is_error_frame,
        "rx": frame.is_rx,
        "dlc": frame.dlc,
    }


def dbc_info(dbc_path: str) -> dict[str, Any]:
    """Summarize a local DBC file. Use this first to learn its size and node names."""
    path, db = _database(dbc_path)
    nodes = sorted(db.nodes)
    return {
        "path": str(path),
        "version": db.version,
        "message_count": len(db.messages),
        "signal_count": sum(len(message.signals) for message in db.messages.values()),
        "node_count": len(nodes),
        "node_names": nodes[:MAX_NODE_NAMES],
        "node_names_truncated": len(nodes) > MAX_NODE_NAMES,
    }


def list_messages(
    dbc_path: str,
    search: str | None = None,
    limit: int = DEFAULT_LIST_LIMIT,
) -> dict[str, Any]:
    """List DBC messages, optionally narrowing by name, ID, or sender. The server caps limit at 200."""
    _, db = _database(dbc_path)
    effective_limit = _effective_limit(limit, maximum=MAX_LIST_LIMIT, name="limit")
    messages = sorted(db.messages.values(), key=lambda item: item.arbitration_id)
    if search is not None:
        query = search.casefold()
        messages = [
            message
            for message in messages
            if query in message.name.casefold()
            or query in _hex_id(message.arbitration_id).casefold()
            or any(query in sender.casefold() for sender in message.senders)
        ]
    total = len(messages)
    items = [_message_summary(message) for message in messages[:effective_limit]]
    return {
        "total": total,
        "returned": len(items),
        "truncated": total > effective_limit,
        "limit": effective_limit,
        "messages": items,
    }


def get_message(dbc_path: str, message: str | int) -> dict[str, Any]:
    """Return one message and its signal layout. message accepts a name, decimal ID, or 0x-prefixed hex ID."""
    _, db = _database(dbc_path)
    selected = _resolve_message(db, message)
    signals = list(selected.signals.values())
    return {
        **_message_summary(selected),
        "extended": selected.is_extended_frame,
        "comment": selected.comment,
        "cycle_time_ms": selected.cycle_time,
        "signals": [_signal_detail(signal) for signal in signals[:MAX_SIGNALS_PER_MESSAGE]],
        "signals_truncated": len(signals) > MAX_SIGNALS_PER_MESSAGE,
    }


def search_signals(
    dbc_path: str,
    query: str,
    limit: int = DEFAULT_LIST_LIMIT,
) -> dict[str, Any]:
    """Search signal names and comments across a DBC. The server caps limit at 200."""
    _, db = _database(dbc_path)
    effective_limit = _effective_limit(limit, maximum=MAX_LIST_LIMIT, name="limit")
    matches = dbckit.search_signals(db, query)
    total = len(matches)
    items = [
        {
            "message_id": _hex_id(message.arbitration_id),
            "message_name": message.name,
            "signal_name": signal.name,
            "start_bit": signal.start_bit,
            "length": signal.length,
            "factor": signal.factor,
            "offset": signal.offset,
            "unit": signal.unit,
            "comment": signal.comment,
        }
        for message, signal in matches[:effective_limit]
    ]
    return {
        "total": total,
        "returned": len(items),
        "truncated": total > effective_limit,
        "limit": effective_limit,
        "signals": items,
    }


def decode_frame(dbc_path: str, arbitration_id: str | int, data_hex: str) -> dict[str, Any]:
    """Decode one CAN payload using a local DBC. data_hex is a hexadecimal byte string; no file is modified."""
    _, db = _database(dbc_path)
    parsed_id = _parse_arbitration_id(arbitration_id)
    try:
        data = bytes.fromhex(data_hex)
    except ValueError as exc:
        raise ValueError(f"Invalid data_hex value: {exc}") from None
    try:
        signals = dbckit.decode_frame(db, parsed_id, data)
    except Exception as exc:
        raise ValueError(f"Cannot decode frame {_hex_id(parsed_id)}: {exc}") from None
    return {
        "arbitration_id": _hex_id(parsed_id),
        "data_hex": data.hex().upper(),
        "signals": _json_value(signals),
    }


def validate_dbc(dbc_path: str, limit: int = DEFAULT_FRAME_LIMIT) -> dict[str, Any]:
    """Validate a DBC and return structured issues. The server caps limit at 200."""
    _, db = _database(dbc_path)
    effective_limit = _effective_limit(limit, maximum=MAX_LIST_LIMIT, name="limit")
    issues = dbckit.validate(db)
    items = [issue.model_dump(mode="json") for issue in issues[:effective_limit]]
    return {
        "total": len(issues),
        "returned": len(items),
        "truncated": len(issues) > effective_limit,
        "limit": effective_limit,
        "issues": items,
    }


def diff_dbcs(dbc_a_path: str, dbc_b_path: str) -> dict[str, Any]:
    """Compare two local DBC files and return bounded added, removed, and changed message/signal details."""
    _, db_a = _database(dbc_a_path)
    _, db_b = _database(dbc_b_path)
    result = dbckit.diff(db_a, db_b)

    added_messages = [_message_summary(item) for item in result.added_messages[:MAX_DIFF_MESSAGES]]
    removed_messages = [_message_summary(item) for item in result.removed_messages[:MAX_DIFF_MESSAGES]]
    changed_messages: list[dict[str, Any]] = []
    signal_truncated = False
    for item in result.modified_messages[:MAX_DIFF_MESSAGES]:
        signal_diffs = item.signal_diffs
        added_signals = [
            _signal_detail(change.after)
            for change in signal_diffs
            if change.change == "added" and change.after is not None
        ]
        removed_signals = [
            _signal_detail(change.before)
            for change in signal_diffs
            if change.change == "removed" and change.before is not None
        ]
        changed_signals = [
            {
                "name": change.signal_name,
                "changes": _signal_changes(change.before, change.after),
            }
            for change in signal_diffs
            if change.change == "modified" and change.before is not None and change.after is not None
        ]
        signal_total = len(added_signals) + len(removed_signals) + len(changed_signals)
        signal_truncated = signal_truncated or signal_total > MAX_DIFF_SIGNALS_PER_MESSAGE
        remaining = MAX_DIFF_SIGNALS_PER_MESSAGE
        bounded_added = added_signals[:remaining]
        remaining -= len(bounded_added)
        bounded_removed = removed_signals[:remaining]
        remaining -= len(bounded_removed)
        bounded_changed = changed_signals[:remaining]
        changed_messages.append(
            {
                "id": _hex_id(item.arbitration_id),
                "name": item.message_name,
                "field_changes": {
                    field: {"before": _json_value(values[0]), "after": _json_value(values[1])}
                    for field, values in item.field_changes.items()
                },
                "signal_diff_total": signal_total,
                "signals_truncated": signal_total > MAX_DIFF_SIGNALS_PER_MESSAGE,
                "added_signals": bounded_added,
                "removed_signals": bounded_removed,
                "changed_signals": bounded_changed,
            }
        )

    message_truncated = any(
        len(items) > MAX_DIFF_MESSAGES
        for items in (result.added_messages, result.removed_messages, result.modified_messages)
    )
    return {
        "summary": {
            "added_messages": len(result.added_messages),
            "removed_messages": len(result.removed_messages),
            "changed_messages": len(result.modified_messages),
        },
        "truncated": message_truncated or signal_truncated,
        "added_messages": added_messages,
        "removed_messages": removed_messages,
        "changed_messages": changed_messages,
    }


def probe_log(log_path: str) -> dict[str, Any]:
    """Detect a local CAN log's format and cheap header metadata without scanning all frames."""
    path, _ = _checked_path(log_path, kind="Log")
    try:
        meta = capkit.probe(path)
    except Exception as exc:
        try:
            formats = capkit.available_formats()
        except Exception:
            formats = []
        available = ", ".join(formats) or "(none)"
        raise ValueError(f"Cannot probe log file '{path}': {exc} Available formats: {available}") from None
    return {
        "path": str(path),
        "format": meta.format,
        "start_time": meta.start_time.isoformat() if meta.start_time is not None else None,
        "extra": meta.extra,
    }


def log_stats(log_path: str, top: int = 20) -> dict[str, Any]:
    """Scan a local CAN log for counts, span, top IDs, and median per-ID cycle times. top is capped at 200."""
    path, _ = _checked_path(log_path, kind="Log")
    effective_top = _effective_limit(top, maximum=MAX_LIST_LIMIT, name="top")
    counts: Counter[int] = Counter()
    previous: dict[int, float] = {}
    deltas: dict[int, list[float]] = defaultdict(list)
    first_timestamp: float | None = None
    last_timestamp: float | None = None

    for frame in _filtered_frames(path, ids=None, time_start=None, time_end=None):
        counts[frame.arbitration_id] += 1
        if first_timestamp is None or frame.timestamp < first_timestamp:
            first_timestamp = frame.timestamp
        if last_timestamp is None or frame.timestamp > last_timestamp:
            last_timestamp = frame.timestamp
        prior = previous.get(frame.arbitration_id)
        if prior is not None:
            deltas[frame.arbitration_id].append(frame.timestamp - prior)
        previous[frame.arbitration_id] = frame.timestamp

    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    top_ids = [
        {
            "id": _hex_id(arbitration_id),
            "count": count,
            "median_cycle_time": median(deltas[arbitration_id]) if deltas[arbitration_id] else None,
        }
        for arbitration_id, count in ranked[:effective_top]
    ]
    frame_count = sum(counts.values())
    return {
        "frame_count": frame_count,
        "start_timestamp": first_timestamp,
        "end_timestamp": last_timestamp,
        "time_span": (
            last_timestamp - first_timestamp
            if first_timestamp is not None and last_timestamp is not None
            else None
        ),
        "unique_id_count": len(counts),
        "returned": len(top_ids),
        "truncated": len(counts) > effective_top,
        "top": effective_top,
        "top_ids": top_ids,
    }


def read_frames(
    log_path: str,
    id_filter: list[str | int] | None = None,
    time_start: float | None = None,
    time_end: float | None = None,
    limit: int = DEFAULT_FRAME_LIMIT,
) -> dict[str, Any]:
    """Read a bounded raw-frame sample from a local log, with optional ID and timestamp filters. limit is capped at 500."""
    path, _ = _checked_path(log_path, kind="Log")
    _validate_time_window(time_start, time_end)
    ids = _id_filter(id_filter)
    effective_limit = _effective_limit(limit, maximum=MAX_FRAME_LIMIT, name="limit")
    rows: list[dict[str, Any]] = []
    total = 0
    for frame in _filtered_frames(path, ids=ids, time_start=time_start, time_end=time_end):
        total += 1
        if len(rows) < effective_limit:
            rows.append(_frame_row(frame))
    return {
        "total": total,
        "returned": len(rows),
        "truncated": total > effective_limit,
        "limit": effective_limit,
        "frames": rows,
    }


def decode_log(
    dbc_path: str,
    log_path: str,
    messages: list[str | int] | None = None,
    id_filter: list[str | int] | None = None,
    time_start: float | None = None,
    time_end: float | None = None,
    limit: int = DEFAULT_FRAME_LIMIT,
) -> dict[str, Any]:
    """Decode a bounded sample of local log frames through a local DBC. Filters combine by intersection; limit is capped at 500."""
    _, db = _database(dbc_path)
    path, _ = _checked_path(log_path, kind="Log")
    _validate_time_window(time_start, time_end)
    ids = _combined_filter(db, messages, id_filter)
    effective_limit = _effective_limit(limit, maximum=MAX_FRAME_LIMIT, name="limit")
    raw_frames = _filtered_frames(path, ids=ids, time_start=time_start, time_end=time_end)
    rows: list[dict[str, Any]] = []
    total = 0
    try:
        decoded_frames = dbckit.decode_frames(db, cast(Iterable[FrameLike], raw_frames))
        for frame in decoded_frames:
            total += 1
            if len(rows) >= effective_limit:
                continue
            message = db.messages[frame.arbitration_id]
            signal_items = list(frame.signals.items())
            bounded_signals = dict(signal_items[:MAX_SIGNALS_PER_MESSAGE])
            rows.append(
                {
                    "timestamp": frame.timestamp,
                    "id": _hex_id(frame.arbitration_id),
                    "message": message.name,
                    "data_hex": frame.raw.hex().upper(),
                    "channel": frame.channel,
                    "signals": _json_value(bounded_signals),
                    "signal_count": len(signal_items),
                    "signals_truncated": len(signal_items) > MAX_SIGNALS_PER_MESSAGE,
                }
            )
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Cannot decode log file '{path}': {exc}") from None
    return {
        "total": total,
        "returned": len(rows),
        "truncated": total > effective_limit,
        "limit": effective_limit,
        "frames": rows,
    }


def _downsample(points: list[list[Any]], max_points: int) -> list[list[Any]]:
    if len(points) <= max_points:
        return points
    if max_points == 1:
        return [points[0]]
    final_index = len(points) - 1
    return [points[round(index * final_index / (max_points - 1))] for index in range(max_points)]


def signal_timeseries(
    dbc_path: str,
    log_path: str,
    message: str | int,
    signal: str,
    time_start: float | None = None,
    time_end: float | None = None,
    max_points: int = DEFAULT_POINT_LIMIT,
) -> dict[str, Any]:
    """Return a bounded, evenly downsampled [timestamp, value] series for one DBC signal. max_points is capped at 2,000."""
    _, db = _database(dbc_path)
    path, _ = _checked_path(log_path, kind="Log")
    _validate_time_window(time_start, time_end)
    effective_max = _effective_limit(max_points, maximum=MAX_POINT_LIMIT, name="max_points")
    selected_message = _resolve_message(db, message)
    selected_signal = selected_message.signals.get(signal)
    if selected_signal is None:
        raise ValueError(f"No signal {signal!r} exists in message {selected_message.name!r}.")

    points: list[list[Any]] = []
    frames = _filtered_frames(
        path,
        ids={selected_message.arbitration_id},
        time_start=time_start,
        time_end=time_end,
    )
    try:
        for frame in frames:
            decoded = dbckit.decode_frame(db, frame.arbitration_id, frame.data)
            if signal in decoded:
                points.append([frame.timestamp, _json_value(decoded[signal])])
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Cannot decode signal timeseries from '{path}': {exc}") from None

    sampled = _downsample(points, effective_max)
    return {
        "message_id": _hex_id(selected_message.arbitration_id),
        "message": selected_message.name,
        "signal": selected_signal.name,
        "unit": selected_signal.unit,
        "total": len(points),
        "returned": len(sampled),
        "truncated": len(points) > effective_max,
        "max_points": effective_max,
        "points": sampled,
    }


TOOLS = (
    dbc_info,
    list_messages,
    get_message,
    search_signals,
    decode_frame,
    validate_dbc,
    diff_dbcs,
    probe_log,
    log_stats,
    read_frames,
    decode_log,
    signal_timeseries,
)

__all__ = [tool.__name__ for tool in TOOLS]
