# Roadmap

The 0.1 line is deliberately local, read-only, bounded, and stdio-only.

## 0.2.0 — signal inventory (requires dbckit 1.1)

Driven by a real session: answering "which signals from this DBC occur in this log?"
took a long chain of low-level calls plus shell workarounds. 0.2.0 makes it one call.

- [x] `log_signal_inventory(dbc_path, log_path, match_mode="auto", include_values=False)`:
  parse once, scan once. The DBC is always parsed leniently with diagnostics surfaced in
  the response (strict validation stays `validate_dbc`'s job); `match_mode`
  (`"exact" | "j1939" | "auto"`) passes through to dbckit. Response covers log
  format/frame count/duration/unique IDs, the matching mode actually used, matched and
  unmatched IDs with per-ID frame counts, signals per matched message (observed
  multiplexer values for multiplexed ones), units and value labels, per-message
  decode-safety, ambiguities, and truncation metadata.
- [ ] Structured non-retryable errors for genuinely unparseable inputs: `code`,
  `retryable: false`, `recommended_action` — so clients report and stop instead of
  improvising workarounds.
- [ ] Strengthen server instructions: for signal-availability questions call
  `log_signal_inventory` first; never rewrite, clean, or copy input files; report
  degraded messages and continue with the safe ones; after a non-retryable error,
  relay it and the recommended action rather than falling back to shell or Python.
  (Advisory only — the durable protection is dbckit's lenient parsing.)
- [ ] `decode_log`: stop signal-decoding matching frames past the output limit — count
  `total` from ID membership alone and decode only the bounded sample.
- [ ] Pin `dbckit>=1.1,<2` and release as 0.2.0.

## Tool surface

- [ ] Encode physical signal values into payload bytes.
- [ ] Add opt-in structured exports once a safe write contract is established.
- [ ] Add comparisons for validation issue sets and selected signal metadata.

## Capture formats

- [ ] PCAN TRC support through capkit 0.3.
- [ ] Configurable CSV support through capkit 0.3.
- [ ] Adopt later capkit readers without adding heavyweight runtime dependencies.

## MCP surface

- [ ] Evaluate resources for stable DBC summaries when MCP client behavior is
  mature enough to justify a second surface.
- [ ] Evaluate prompts for common diagnostic workflows after the tool contracts
  have production use.
- [ ] Revisit transports only if a local-first use case needs more than stdio.

## Quality

- [ ] Benchmark large-log scans and timeseries extraction.
- [ ] Add bounded streaming quantile estimation if exact cycle-time medians use
  too much memory on production captures.
- [ ] Expand fixture coverage as new real-world dialects become available.
