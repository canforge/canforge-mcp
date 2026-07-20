# Large-log benchmarks

This opt-in suite measures the four full-scan paths used by canforge-mcp:
`log_stats`, `decode_log`, `log_signal_inventory`, and `signal_timeseries`.
Generated candump captures are deterministic and intentionally ignored by Git;
only the small benchmark DBC and result summaries are committed.

The generator uses a fixed seed, a one-millisecond timestamp cadence, four
DBC-matched IDs, and eight unmatched IDs. The sparse profile matches 4% of
frames and contains `EngineData` in 1%; the dense profile matches 95% and
contains `EngineData` in 70%. Signal and multiplexer values cycle through 64
distinct values, so the inventory's 50-value caps are exercised and then the
values repeat.

## Commands

Run the 10,000-frame smoke matrix used by the regression test:

```bash
python -m benchmarks.run --preset smoke
```

Regenerate the committed v0.2.0 100k/1M baseline and both Markdown/JSON
artifacts with one command:

```bash
python -m benchmarks.run \
  --preset full \
  --output benchmarks/results/v0.2.0.json
```

Captures are written below `benchmarks/generated/`. They are recreated on each
run and can also be generated without running benchmarks:

```bash
python -m benchmarks.generate --sizes smoke,100k,1m
```

Use `--warmups` and `--repetitions` to change the recorded policy. Every
warm-up and measured repetition launches a fresh subprocess for exactly one
tool/case. The committed reference baseline uses zero warm-ups and one measured
repetition so the full matrix stays practical and includes DBC parsing in each
measurement.

## Measurements and regression policy

Each case records `time.perf_counter()` wall time, `tracemalloc` peak Python
allocations, and `resource.getrusage()` peak RSS normalized to bytes. The
report also captures Python, OS, machine, canforge-mcp, capkit, and dbckit
versions; input frames and bytes; arguments; result counts; and all structural
invariants.

Timing and RSS values are informational and never gate CI. Fast tests and
worker invariants enforce exact totals, truncation metadata, output caps,
first/last timeseries preservation, bounded decode calls, one inventory scan,
and distinct-value/multiplexer caps.

The scaling table intentionally documents two current characteristics instead
of changing their contracts inside benchmark work: `log_stats` retains per-ID
cycle-time deltas, and `signal_timeseries` retains all selected points before
final downsampling.
