# Tool Reference

All paths refer to files on the machine running `canforge-mcp`. Every tool is
read-only. Arbitration IDs accept decimal integers or `0x`-prefixed hexadecimal
values; message selectors also accept case-insensitive message names.

Bounded tools clamp values above their hard cap and reject values below one.
When a result is incomplete it returns `truncated: true` together with `total`
and `returned` counts.

## DBC tools

### `dbc_info(dbc_path)`

Returns the DBC version, message count, signal count, node count, and sorted
node names. Node names are capped at 200.

### `list_messages(dbc_path, search?, limit=50)`

Returns messages ordered by arbitration ID. `search` matches message names,
hexadecimal IDs, and sender names case-insensitively. `limit` is capped at 200.

Each message includes `id`, `name`, `dlc`, `senders`, and `signal_count`.

### `get_message(dbc_path, message)`

Returns message metadata and signals. Each signal includes bit position,
length, byte order, signedness, scaling, range, unit, choices, receivers,
multiplexing information, and comment. Signals are capped at 200.

### `search_signals(dbc_path, query, limit=50)`

Searches signal names and comments case-insensitively. Results include owner
message metadata and signal layout/scaling fields. `limit` is capped at 200.

### `decode_frame(dbc_path, arbitration_id, data_hex)`

Decodes a hexadecimal byte string and returns a signal-name to physical-value
mapping. Whitespace between bytes is accepted. Value-table choices are returned
as labels.

### `validate_dbc(dbc_path, limit=100)`

Returns dbckit issues with `severity`, `code`, `location`, and `message`.
`limit` is capped at 200.

### `diff_dbcs(dbc_a_path, dbc_b_path)`

Returns added, removed, and changed messages. Changed messages contain field
changes plus added, removed, and changed signals. Each top-level category is
capped at 100 messages and each changed message at 100 signal differences.

## Log tools

### `probe_log(log_path)`

Returns the detected capkit format, optional ISO 8601 capture start time, and
format-specific header metadata. Detection failures include the registered
format names in the MCP error.

### `log_stats(log_path, top=20)`

Scans a log and returns frame count, first and last timestamps, time span,
unique-ID count, and top IDs by frame count. `median_cycle_time` is in seconds.
`top` is capped at 200.

### `read_frames(log_path, id_filter?, time_start?, time_end?, limit=100)`

Returns raw frames with hexadecimal payloads. ID and time filters are inclusive;
an empty ID list matches no frames. `limit` is capped at 500.

## Composition tools

### `decode_log(dbc_path, log_path, messages?, id_filter?, time_start?, time_end?, limit=100)`

Reads through capkit and decodes through dbckit. `messages` accepts names or IDs;
when both message and ID filters are supplied their intersection is used.
Frames not present in the DBC are skipped. `limit` is capped at 500, and signal
maps within a frame are capped at 200 entries.

### `signal_timeseries(dbc_path, log_path, message, signal, time_start?, time_end?, max_points=500)`

Returns `[timestamp, value]` pairs for one signal. Inactive multiplexed variants
are omitted. Series longer than `max_points` preserve the first and last point
and select evenly spaced indexes between them. `max_points` is capped at 2,000.

## Errors

Missing paths, unreadable files, parse errors, unknown formats, invalid IDs,
unknown messages or signals, invalid hexadecimal payloads, and reversed time
windows are surfaced as MCP tool errors. Error text is concise and does not
include Python stack traces.
