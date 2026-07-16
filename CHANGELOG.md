# Changelog

All notable changes to canforge-mcp are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning will follow [Semantic Versioning](https://semver.org/) from 1.0.0 onward.

---

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
