# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A Python runtime that simulates a grid-scale battery energy storage system (BESS) trading energy arbitrage. An LP optimiser plans charge/discharge against a price series; an energy-bucket battery model executes the plan; the run produces parquet telemetry and a KPI summary.

**MVP scope** (current): perfect-foresight optimisation, energy arbitrage only, energy-bucket battery with constant charge/discharge efficiency, no degradation/thermal model. The optimiser sees the same prices the simulator executes against — this is intentional; rolling-horizon with forecast≠actual is deferred.

## Commands

`uv` is the project tool (Python 3.12 pinned via `.python-version`).

- Install / sync deps: `uv sync`
- Run all tests: `uv run pytest`
- Run a single test: `uv run pytest tests/test_battery.py::test_charge_then_discharge_round_trip_loses_efficiency`
- Lint: `uv run ruff check src tests`
- Lint + auto-fix: `uv run ruff check src tests --fix`
- Run a scenario: `uv run bess run examples/scenario.yaml`

Run outputs land in `runs/<timestamp>/` (`telemetry.parquet`, `schedule.parquet`, `summary.json`, `manifest.json`).

## Architecture

Pipeline (top-down in `src/bess/`):

1. **`config.py`** — pydantic v2 `ScenarioConfig` (site + prices + timestep + output_dir). `PriceConfig` is a discriminated union: `kind: "csv"` or `kind: "synthetic"`. `load_scenario(path)` reads YAML.
2. **`prices.py`** — returns a single `pd.Series` of £/MWh indexed by interval-start timestamp. `synthetic_sine` is a daily sinusoid with a small evening bump; `load_csv` reads a real series.
3. **`optimiser.py`** — `solve_perfect_foresight(prices, site, dt)` builds and solves an LP via **cvxpy + HiGHS**. Returns a DataFrame with columns `price, p_charge, p_discharge, p_net, soc_planned`. Sign convention on `p_net`: **positive = discharge to grid**.
4. **`battery.py`** — `EnergyBucketBattery.step(power_mw)` evolves SoC by one timestep. Same sign convention as optimiser. Charge efficiency multiplies energy *into* the bucket; discharge efficiency divides energy *out of* the bucket. `StepResult.clipped` flags when a real bound (power or SoC) had to bind. A small numerical tolerance (`_CLIP_TOL_MWH`) prevents spurious flags when the optimiser plans setpoints exactly at a bound.
5. **`runtime.py`** — `run(scenario)` ties it together: load prices → solve → step the battery through the schedule → write telemetry, summary, manifest.
6. **`telemetry.py`** — `TelemetryWriter` accumulates rows then writes `telemetry.parquet`. `summarise_kpis` computes revenue, throughput, equivalent full cycles, max/min SoC, hours clipped.
7. **`cli.py`** — typer app. `bess run <scenario.yaml>` is the entry point; a `version` command exists too (typer treats single-command apps as default-command, so a second command preserves `bess run …` syntax).

**Sign convention** (load-bearing across modules): positive power = discharge to grid, negative = charge from grid. Optimiser, battery, and telemetry all follow this.

**Why optimiser and battery share constraints exactly:** in perfect-foresight mode, any clipping in the runtime indicates a numerical/modelling mismatch between optimiser and simulator, not a forecast error. The `clipped` column is the diagnostic — it should be all-False in MVP runs. Once forecast≠actual lands, this column becomes the way you measure forecast-induced infeasibility.

## Deferred (not yet implemented)

Rolling-horizon optimisation with forecast/actual split, degradation/SoH, thermal, ancillary services (FCAS/frequency response), network constraints, streaming telemetry.
