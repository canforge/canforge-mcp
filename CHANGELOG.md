# Changelog

All notable changes to canforge-mcp are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added

- Added `log_signal_inventory` for bounded, one-pass DBC/log analysis with
  exact and J1939 matching, explicit ambiguities, observed signals and
  multiplexer values, optional decoded values, lenient parse diagnostics, and
  per-message decode-safety reporting.

### Changed

- Bounded `decode_log` signal-decoding work to the returned frame limit while
  retaining exact `total` counts from matching DBC arbitration IDs.
- Raised the supported capkit runtime range from `>=0.2,<0.3` to
  `>=0.3,<0.4`.
- Delegated log ID and inclusive time-window filtering to capkit 0.3's lazy
  stream operations.
- Added raw J1939 priority, PGN, and source-address enrichment for observed
  extended IDs returned by `log_stats` and `log_signal_inventory`.

## [0.1.0] — 2026-07-16

Initial public release.

### Added

- Twelve local, read-only MCP tools for DBC inspection, CAN frame decoding,
  capture-log inspection, decoded log sampling, and signal timeseries.
- Bounded responses with explicit truncation metadata and deterministic
  timeseries downsampling.
- Parsed-DBC cache keyed by resolved path and modification time.
- Stdio console server available as `canforge-mcp` and through
  `uvx canforge-mcp`.
- Fixtures with documented provenance plus direct-function and MCP stdio tests.
- CI on Python 3.11–3.14 with lint, typing, 90% coverage, build, and wheel
  metadata checks.
- Tag-driven PyPI release workflow using trusted publishing (OIDC).
