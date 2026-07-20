# canforge-mcp

[![PyPI](https://img.shields.io/pypi/v/canforge-mcp)](https://pypi.org/project/canforge-mcp/)
[![CI](https://github.com/canforge/canforge-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/canforge/canforge-mcp/actions/workflows/ci.yml)
[![Python versions](https://img.shields.io/pypi/pyversions/canforge-mcp)](https://pypi.org/project/canforge-mcp/)
[![License: MIT](https://img.shields.io/pypi/l/canforge-mcp)](LICENSE)

`canforge-mcp` is a local, read-only MCP server for inspecting DBC files and
decoding CAN capture logs.

Files stay on the machine running the server. The server exposes bounded tools
instead of uploading captures or returning unbounded traces.

## Tools

| Tool | Purpose |
|---|---|
| `dbc_info` | DBC version, message/signal/node counts, and node names |
| `list_messages` | Bounded message summaries, with optional search |
| `get_message` | Full message and signal detail by name or arbitration ID |
| `search_signals` | Bounded signal search across a DBC |
| `decode_frame` | Decode one hexadecimal CAN payload |
| `validate_dbc` | Structured DBC validation issues |
| `diff_dbcs` | Added, removed, and changed messages and signals |
| `probe_log` | Detect a log format and read header metadata |
| `log_stats` | Frame count, span, ID counts, and median cycle times |
| `read_frames` | Bounded raw-frame samples with ID and time filters |
| `decode_log` | Bounded decoded frames from a DBC and log |
| `signal_timeseries` | Downsampled timestamp/value points for one signal |

See [the tool reference](docs/tools.md) for arguments, return shapes, and hard
caps.

## Install

Run directly with `uvx`:

```bash
uvx canforge-mcp
```

Or install with pip:

```bash
pip install canforge-mcp
canforge-mcp
```

Requires Python `>=3.11`.

## Configure

Claude Code:

```bash
claude mcp add canforge -- uvx canforge-mcp
```

Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "canforge": {
      "command": "uvx",
      "args": ["canforge-mcp"]
    }
  }
}
```

Restart Claude after changing its MCP configuration.

### ChatGPT (Secure MCP Tunnel)

ChatGPT cannot start a local stdio MCP server directly. Use OpenAI's
[Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
to keep Canforge running locally without exposing it to the public internet.

Before starting, enable developer mode in ChatGPT under **Settings → Security
and login**, then create a tunnel in the OpenAI Platform. You need its tunnel
ID, a runtime API key, and the `tunnel-client` binary. Make sure the tunnel is
associated with the ChatGPT workspace where you will use Canforge.

Configure and start the tunnel with placeholder credentials:

```bash
export CONTROL_PLANE_API_KEY="sk-..."

tunnel-client init \
  --sample sample_mcp_stdio_local \
  --profile canforge \
  --tunnel-id tunnel_your_id \
  --mcp-command "uvx canforge-mcp"

tunnel-client doctor --profile canforge --explain
tunnel-client run --profile canforge
```

Keep `tunnel-client run` running while using Canforge. In ChatGPT, open
**Settings → Plugins**, add a developer-mode app, choose **Tunnel** as the
connection, and select or paste the tunnel ID. Add the new app to a chat before
asking ChatGPT to use the Canforge tools.

Canforge resolves paths on the machine running `tunnel-client`. Files attached
directly to a ChatGPT conversation are not automatically available as local
filesystem paths; provide an accessible local path instead.

## Design

- Local-first: tools accept filesystem paths and do not send file content over
  the network.
- Read-only: no tool creates, edits, encodes, or overwrites a file.
- Bounded: list and frame tools enforce hard caps and report `total`,
  `returned`, and `truncated`; timeseries are downsampled server-side.
- Cached: parsed DBCs are cached by resolved path and nanosecond modification
  time for repeated inspection during one server session.
- Composable: [capkit](https://github.com/canforge/capkit) reads capture formats;
  [dbckit](https://github.com/canforge/dbckit) parses and decodes DBC content.
- Stdio-only: version 0.1 exposes no network transport or hosted service.

## Scope and Caveats

- Supported capture formats come from capkit 0.2: Kvaser CanKing TXT, candump
  text, and Vector ASC.
- DBC support and validation behavior follow dbckit 1.x.
- Timestamps are floats exactly as recorded by capkit; they are not rebased.
- Median cycle time is the median gap between consecutive occurrences of an ID.
- `signal_timeseries` uses deterministic, evenly spaced index sampling when a
  series exceeds `max_points`; it is intended for inspection, not resampling or
  signal processing.
- Paths are resolved by the machine running the MCP server. A remote client's
  filesystem is not visible to a server running elsewhere.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
ruff check .
mypy canforge_mcp
pytest --cov=canforge_mcp --cov-fail-under=90
python -m build
```

## License

MIT
