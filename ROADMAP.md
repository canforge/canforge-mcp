# Roadmap

The 0.1 line is deliberately local, read-only, bounded, and stdio-only.

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
