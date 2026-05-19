# bess

A small Python runtime that simulates a grid-scale battery energy storage
system trading energy arbitrage. An LP optimiser plans charge/discharge
against a price series, an energy-bucket battery model executes the
schedule, and the run produces telemetry plus KPI summaries.

This MVP runs in **perfect-foresight** mode: the optimiser sees the same
prices the simulator executes against. Useful as a revenue upper bound and
to exercise the full pipeline.

## Quick start

```bash
uv sync
uv run pytest
uv run bess run examples/scenario.yaml
```

Outputs land in `runs/<timestamp>/`:
- `telemetry.parquet` — per-timestep state and dispatch
- `summary.json` — run-level KPIs
- `manifest.json` — config snapshot
