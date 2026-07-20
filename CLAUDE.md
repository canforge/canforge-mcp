# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

canforge-mcp is a local, read-only [MCP](https://modelcontextprotocol.io) server that exposes
13 bounded tools over CAN DBC files and capture logs. It is the third package in the canforge
family and the only one that composes the other two: **[dbckit](https://github.com/canforge/dbckit)**
parses and decodes DBC content, **[capkit](https://github.com/canforge/capkit)** reads capture
logs into frames, and canforge-mcp wires them into MCP tools. Published to PyPI as `canforge-mcp`
(github.com/canforge/canforge-mcp); runnable as `uvx canforge-mcp`.

Unlike capkit and dbckit — which never import each other — canforge-mcp depends on **both** at
runtime. It is the integration layer, so the coupling lives here on purpose. It never reimplements
what either library does: capkit owns log I/O and frame-side J1939 arithmetic, dbckit owns all
DBC-aware matching and signal decoding.

ROADMAP.md is the authority on what lands next; it mirrors the Linear `canforge-mcp` (CFM) team.

## Commands

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest                                              # full suite (direct + MCP stdio round-trips)
pytest tests/test_log_tools.py                      # one file
pytest --cov=canforge_mcp --cov-fail-under=90 -q    # the CI coverage gate
ruff check .                                         # lint (CI-blocking)
mypy canforge_mcp                                    # types (CI-blocking)
python -m build                                      # sdist+wheel (CI-blocking)
```

CI's build check asserts the wheel ships `canforge_mcp/py.typed` and the
`canforge-mcp = canforge_mcp.server:main` console-script entry point. The matrix is Python
3.11–3.14. Large-log benchmarks are **opt-in** and out of the normal suite — see below.

## Architecture

Three modules, one entry point:

```
canforge_mcp/tools.py   — 13 plain tool functions + shared helpers (the whole surface)
canforge_mcp/server.py  — FastMCP wiring, read-only annotations, error boundary, stdio main()
canforge_mcp/errors.py  — UnparseableInputError, the one typed terminal-error contract
```

- **`tools.py`** — every tool is a plain function returning a JSON-able dict; `TOOLS` is the
  registration tuple and `__all__` is derived from it. Tools never do I/O beyond reading the
  given paths. All list/frame tools return `total`/`returned`/`truncated`/`limit` and enforce a
  `MAX_*` cap; there is no unbounded output anywhere. Parsed DBCs are cached with an
  `lru_cache` keyed by resolved path + `st_mtime_ns` (+ parse mode); `clear_dbc_cache()` resets it
  for tests.
- **`server.py`** — `FastMCP` with server `instructions` that route signal-availability questions
  to `log_signal_inventory` first and encode the input-immutability / decode-safety / non-retryable
  error rules. Every tool is registered `READ_ONLY` (`readOnlyHint=True`, `destructiveHint=False`,
  …) with `structured_output=True`, wrapped by `_with_structured_terminal_errors`. `main()` runs
  stdio only.
- **`errors.py`** — `UnparseableInputError(ValueError)` carries `code`
  (`unparseable_dbc`/`unparseable_log`), `message`, `retryable=False`, `recommended_action`. The
  server turns it into a `CallToolResult(isError=True, structuredContent=…)` with a concise text
  fallback; all other exceptions take FastMCP's default path.

## Load-bearing invariants (don't break these)

- **`UnparseableInputError` must remain a `ValueError` subclass.** Tools that decode lazily
  (`decode_log`, `log_signal_inventory`, `signal_timeseries`) use `except ValueError: raise` ahead
  of a broad `except Exception` wrapper. A terminal parse error raised deep inside a lazy
  `dbckit.decode_frames(...)` iteration must re-raise intact rather than be flattened into a generic
  string. If you change the class hierarchy, that contract breaks silently.
- **Only genuinely terminal parse failures get the structured codes.** Missing files, bad
  arguments, unknown messages/signals, decoder failures on already-parsed input, and registry
  errors stay plain `ValueError`. Recoverable lenient-parse diagnostics are normal successful
  output, never errors.
- **Bounded means bounded.** New tools return `total`/`returned`/`truncated` and cap retained
  state by ID/signal cardinality, not frame count. A one-pass scan may read the whole log, but
  retained data must not grow with it (the known exceptions — `log_stats` cycle-time deltas and
  `signal_timeseries` pre-downsample points — are tracked in ROADMAP.md, not new precedent).
- **Never write, encode, or mutate input files.** Read-only is the product; the annotations and
  server instructions both promise it.

## Scope walls (policy, not gaps)

- No DBC parsing/decoding logic here — that is dbckit's job. No log format parsing — that is
  capkit's. canforge-mcp calls them; it does not reimplement them.
- Frame-side J1939 decomposition (priority/PGN/source address for observed extended IDs) comes
  from `capkit.decompose_j1939_id` and is descriptive only. DBC-aware J1939 *matching* stays in
  dbckit and must not be influenced by the enrichment.
- Stdio only through the 0.x line; no network transport or hosted service. Paths resolve on the
  machine running the server.
- No writers, encoders, or file-producing tools. Structured exports wait on a safe write contract
  (see ROADMAP.md).

## Testing conventions

- Two layers: direct function tests (`tests/test_dbc_tools.py`, `tests/test_log_tools.py`) and
  MCP-facing stdio round-trips (`tests/test_server.py`) that launch the real `canforge-mcp` console
  script and assert `isError`, `structuredContent`, and the server instructions end to end.
- **Subprocess coverage caveat:** `server.py`'s terminal-error path executes inside the spawned
  console-script process, so in-process coverage reports it as "missing" even though the stdio tests
  exercise it. Don't add a redundant in-process test to chase the number — the subprocess test is
  the stronger assertion.
- Fixtures carry documented provenance; anonymized/licensed captures only, never regenerated.
- Benchmarks (`benchmarks/`) are opt-in and generate their own deterministic captures (gitignored;
  only `results/*.{json,md}` summaries are committed). CI runs only the smoke preset via
  `tests/test_benchmarks.py`; the full 100k/1M matrix is a manual `python -m benchmarks.run`.

## Docs that must move together

A change to the tool surface touches: `docs/tools.md` (per-tool arguments, bounds, return shape,
errors), `README.md` (tool table, scope, caveats), `CHANGELOG.md` (Keep a Changelog; semver), and
`ROADMAP.md`. The version lives in **three** places that must agree: `pyproject.toml`,
`canforge_mcp/__init__.py`, and the assertion in `tests/test_server.py`.

## Releasing

Tag-driven, identical to the sister packages: bump the version in all three places, retitle the
CHANGELOG `[Unreleased]` section to the dated version, confirm the capkit/dbckit/mcp dependency
ranges still match what the release uses, commit, push `main`, then `git tag -a vX.Y.Z && git push
origin vX.Y.Z` — `.github/workflows/release.yml` builds and publishes to PyPI via trusted publishing
(OIDC, environment `pypi`, no tokens). Full checklist: docs/releasing.md.
