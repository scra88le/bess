# Grid-Scale Battery (BESS) Physical Model

A standalone Python runtime that simulates the high-fidelity physical state and
operational constraints of a grid-scale battery energy storage system (BESS)
subjected to **1-second-resolution dispatch signals**.

Given a physical configuration (`config.yaml`) and a time series of power
setpoints (`dispatch.csv`), the runtime steps the battery one second at a time,
enforces every physical and grid constraint, and streams out detailed
telemetry plus a log of any point where the delivered power had to diverge from
what was commanded.

---

## Contents

- [Quick start](#quick-start)
- [Running the runtime](#running-the-runtime)
- [Input files](#input-files)
  - [`dispatch.csv`](#dispatchcsv)
  - [`config.yaml`](#configyaml-reference)
- [Output](#output)
  - [Telemetry (stdout)](#telemetry-stdout)
  - [Violation alarms (stderr)](#violation-alarms-stderr)
- [What the model simulates](#what-the-model-simulates)
- [Example scenarios](#example-scenarios)
- [Project layout](#project-layout)
- [Development](#development)

---

## Quick start

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt    # numpy, matplotlib, pyyaml, click

# 3. Run with the default config and a 24-hour sine dispatch
python main.py --config config.yaml --dispatch dispatch_sine.csv
```

> The repo already contains a `.venv/` with the dependencies installed, so you
> can also just call `.venv/bin/python main.py ...` without activating anything.
> All commands below use that form.

---

## Running the runtime

The entry point is `main.py`, a [`click`](https://click.palletsprojects.com/)
CLI:

```bash
.venv/bin/python main.py [--config PATH] [--dispatch PATH] [--visualize]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--config` | `config.yaml` | Physical parameters (validated at startup). |
| `--dispatch` | `dispatch.csv` | Time-series dispatch signal at 1 s resolution. |
| `--visualize` | *(off)* | Open a live matplotlib dashboard instead of printing CSV. |

**Telemetry is written to stdout; violation alarms to stderr.** Redirect them
independently:

```bash
# Save telemetry and alarms separately
.venv/bin/python main.py --config config.yaml --dispatch dispatch_sine.csv \
    > telemetry.csv 2> violations.log

# Only watch the constraint violations
.venv/bin/python main.py --config config.yaml --dispatch dispatch_sine.csv \
    2>&1 >/dev/null
```

With `--visualize` the runtime opens a four-panel dashboard of the recorded run:

1. **Power** — target (injected) vs. actual vs. grid limits
2. **State of Charge** — SoC %
3. **Temperature** — cell vs. ambient
4. **Degradation** — capacity loss % with equivalent full cycles on a twin axis

```bash
.venv/bin/python main.py --config config.yaml --dispatch dispatch_sine.csv --visualize
```

---

## Input files

### `dispatch.csv`

A two-column CSV at 1-second resolution. One row per second.

```csv
timestamp_s,dispatch_mw
0,0.0
1,5.0
2,10.0
```

| Column | Meaning |
|--------|---------|
| `timestamp_s` | Integer second offset from the start of the run (0, 1, 2, …). |
| `dispatch_mw` | Commanded grid-side power in MW. **Sign convention: positive = discharge / export to grid; negative = charge / import from grid.** |

The number of rows defines the run length (e.g. 3600 rows = 1 hour, 86 400 rows
= 24 hours).

### `config.yaml` reference

Every physical constant lives in one YAML file. **The loader validates it at
startup and raises a `ConfigError` on any missing key or physically impossible
value** (e.g. negative efficiency) — there are no silent fallbacks.

```yaml
nominal_capacity_mwh: 50.0          # usable energy capacity (MWh), must be > 0
initial_soc: 0.50                   # starting state of charge, 0..1
efficiency: 0.92                    # one-way efficiency, (0, 1]
ramping_limit_mw_per_sec: 2.0       # max change in power per second, > 0

thermal:
  initial_temp_c: 25.0              # starting cell temperature
  ambient_temp_c: 20.0              # surrounding air temperature
  thermal_mass: 300000000.0         # J/°C — how much heat raises temperature
  hvac_cooling_rate_c_per_sec: 0.05 # max cooling pull toward optimal, °C/s
  optimal_temp_c: 20.0              # (optional) HVAC target; aux scales above this
  max_cell_temp_c: 60.0             # (optional) hard cutoff — trips to 0 MW at/above

soc_non_linearity:
  lower_threshold: 0.10             # below this, resistance rises near the floor
  upper_threshold: 0.90             # above this, resistance rises near the ceiling
  exponential_factor: 2.5           # steepness of the resistance rise

auxiliary_load_kw:
  base: 50.0                        # constant parasitic load (controllers, etc.)
  hvac_per_degree: 10.0             # extra HVAC load per °C above optimal

grid_constraints:
  max_export_mw: 45.0               # hard cap on discharge to grid
  max_import_mw: 45.0               # hard cap on charge from grid

warranty:
  max_equivalent_full_cycles: 3000  # EFC limit; warranty_breached flag trips past it

degradation:                        # (optional) capacity-fade rates
  cycle_loss_per_efc: 0.0000667     # fade per equivalent full cycle
  calendar_loss_per_year: 0.02      # fade per year from pure aging

planned_outages: []                 # list of [start_s, end_s] maintenance windows
                                    # e.g. [[1200, 1800]] masks dispatch to 0 MW
```

> **YAML number gotcha:** PyYAML (YAML 1.1) does not parse unsigned-exponent
> forms like `3.0e8` as a float — it reads them as strings and validation will
> reject them. Write large numbers as plain floats (`300000000.0`) or with a
> signed exponent (`3.0e+8`).

---

## Output

### Telemetry (stdout)

A CSV with a header row and one row per simulated second:

| Column | Description |
|--------|-------------|
| `timestamp_s` | Second offset. |
| `injected_mw` | The raw commanded power from `dispatch.csv`. |
| `target_mw` | The setpoint after engine-stage clamps, fed to the battery. |
| `actual_mw` | The power actually delivered after all physics. |
| `grid_limit_export_mw` | Configured export cap (for plotting). |
| `grid_limit_import_mw` | Configured import cap, as a negative number. |
| `soc` | State of charge, 0..1. |
| `cell_temp_c` | Cell temperature. |
| `ambient_temp_c` | Ambient temperature. |
| `aux_load_mw` | Parasitic auxiliary load this step. |
| `resistive_loss_mw` | I²R / efficiency loss converted to heat. |
| `cumulative_throughput_mwh` | Total energy through the cells so far. |
| `equivalent_full_cycles` | Accumulated EFC (1 cycle = 2× capacity throughput). |
| `capacity_loss_fraction` | Fraction of nominal capacity lost to degradation. |
| `warranty_breached` | `1` once EFC exceeds the warranty limit, else `0`. |
| `limit_reason` | Why the battery limited power this step (battery-stage only; empty if unconstrained). |

### Violation alarms (stderr)

Whenever the delivered power diverges from what was commanded, the runtime
emits one alarm block per binding constraint:

```
[VIOLATION][267] Desired: 45.0 MW | Enforced Limit: 0.0 MW | Reason: [Thermal Trip]
```

Possible reasons, in the order they are applied:

| Stage | Reason | Meaning |
|-------|--------|---------|
| Pre-step | `Planned Outage` | Inside a maintenance window; dispatch masked to 0 MW. |
| Pre-step | `Grid Constrained` | Setpoint exceeded the export/import cap. |
| Intra-step | `Ramp Limit Exceeded` | Requested change exceeded MW/s ramp limit. |
| Battery | `Thermal Trip` | Cell temperature at/above the cutoff; power forced to 0. |
| Battery | `SoC Non-Linear Limit` | Power derated by rising resistance near a SoC rail. |
| Battery | `SoC Floor` / `SoC Ceiling` / `SoC Limit` | SoC hit a hard bound; power clamped. |

---

## What the model simulates

Each 1-second step runs this pipeline (the `DispatchEngine` orchestrates the
first three; the `Battery` handles the rest):

1. **Planned outage masking** — dispatch forced to 0 during maintenance windows.
2. **Grid constraints** — hard clip to max export/import, independent of battery
   capability.
3. **Ramp limiting** — change in power capped at `ramping_limit_mw_per_sec`,
   measured against the *previous actual* power (so it correctly ramps back up
   after a trip or outage).
4. **SoC non-linearity** — internal resistance rises exponentially past the
   thresholds, derating charge acceptance near 100 % and discharge capability
   near 0 %.
5. **Round-trip efficiency** — applied per direction: discharging draws `P/η`
   from the cells, charging stores `P·η`.
6. **Thermal dynamics** — I²R losses heat the cells (`ΔT = Q / thermal_mass`);
   HVAC cools toward the optimal temperature at a bounded rate.
7. **Auxiliary load** — a constant base plus HVAC load scaling with temperature
   deviation; drawn parasitically from the cells.
8. **Degradation** — cycle-based (per EFC) and calendar-based capacity fade;
   effective capacity shrinks over time and the warranty flag trips past the
   EFC limit.
9. **SoC clamping** — SoC is held within `[0, 1]`; the actual delivered power is
   back-solved from the clamped energy change.

---

## Example scenarios

The `scenarios/` directory contains nine ready-to-run cases, each a
self-contained `config.yaml` + `dispatch.csv` pair that isolates one behaviour.
Run any of them with:

```bash
.venv/bin/python main.py \
  --config scenarios/<name>/config.yaml \
  --dispatch scenarios/<name>/dispatch.csv          # add --visualize for the dashboard
```

| # | Scenario | What it demonstrates |
|---|----------|----------------------|
| 01 | `grid_clip` | Commands 60 MW with the ramp limit opened up; output is hard-clipped to the **±45 MW grid limit** (export then import). Watch `actual_mw` pinned at 45 and `Grid Constrained` alarms. |
| 02 | `ramp_limit` | A ±40 MW square wave the inverter can't follow; `actual_mw` **sawtooths** toward each target at 2 MW/s with `Ramp Limit Exceeded` alarms. |
| 03 | `soc_saturation` | Sustained 25 MW discharge drains SoC through the 10 % knee; power **derates** as resistance rises (`SoC Non-Linear Limit`), settling near SoC ≈ 0.07. |
| 04 | `efficiency_drain` | A pure zero-mean 30 MW sine. **No violations**, yet SoC drifts down (~0.50 → 0.47/hr) purely from round-trip + auxiliary losses. |
| 05 | `aux_load` | Idle (0 MW) dispatch with a hot 45 °C start and heavy aux load. SoC **bleeds down with no dispatch at all**, and `aux_load_mw` decays as the cell cools to optimal (Temp→Aux feedback). |
| 06 | `planned_outage` | Steady 20 MW with a maintenance window at t = 1200–1800 s; dispatch is **masked to 0** (`Planned Outage`), then ramps back up. |
| 07 | `warranty_breach` | Heavy ±45 MW cycling with a deliberately low limit (0.3 EFC) and exaggerated fade; **`warranty_breached` flips to 1** mid-run and capacity loss climbs. |
| 08 | `thermal_trip` | Hot day + small thermal envelope; sustained 45 MW heats cells **past 60 °C and trips to 0** (`Thermal Trip`), then chatters around the limit. |
| 09 | `compound_hot_gridclip` | Hot day **and** a 60 MW over-command: **grid clip, thermal trip, and ramp-limited recovery all interact** in one run. |

See [`scenarios/README.md`](scenarios/README.md) for per-scenario detail and what
to watch in the telemetry.

### Why some scenarios use custom configs

The default `config.yaml` is tuned for **realistic, well-behaved operation** —
its HVAC always out-cools dispatch heating, and the 3000-EFC warranty is ~280
days away at full power. The thermal-trip and warranty scenarios therefore use
deliberately adverse or scaled parameters (hot ambient, small thermal mass, low
EFC limit, exaggerated fade) to make those limits reachable inside a short run.
The relevant knobs are noted in each scenario's `config.yaml` header.

### Regenerating scenarios

All scenario files are generated by a script, which can also re-run each one to
confirm it still triggers its intended behaviour:

```bash
.venv/bin/python scripts/make_scenarios.py            # regenerate the files
.venv/bin/python scripts/make_scenarios.py --verify   # regenerate, run, and report
```

There are also two larger standalone dispatch files at the repo root:

- `dispatch_sine.csv` — a balanced 24-hour sine (charge-biased so SoC stays
  near 50 % all day with zero violations).
- `dispatch_thermal_trip.csv` — the sustained 45 MW discharge used by the
  thermal-trip scenario (pair with `config_hot.yaml`).

---

## Project layout

```text
.
├── main.py                 # CLI entry point
├── config.yaml             # default physical parameters
├── dispatch.csv            # short sample dispatch signal
├── dispatch_sine.csv       # 24-hour balanced sine
├── config_hot.yaml         # adverse-thermal scenario config
├── dispatch_thermal_trip.csv
├── requirements.txt
├── src/
│   ├── battery.py          # physical state machine & core math
│   ├── config_loader.py    # YAML loading + strict validation
│   ├── dispatch_engine.py  # time loop, constraint enforcement, alarm logging
│   └── telemetry.py        # CSV emission + matplotlib dashboard
├── scenarios/              # 9 self-contained example scenarios (+ README)
├── scripts/
│   └── make_scenarios.py   # scenario generator / verifier
└── tests/                  # pytest suite
```

**Design note:** the `Battery` class handles only immediate physical
transformations; the `DispatchEngine` owns time orchestration and external-system
overrides (outages, grid clips, ramping). This separation keeps the physics
unit-testable in isolation.

---

## Development

```bash
.venv/bin/python -m pytest          # run the test suite (37 tests)
```

The suite covers battery physics (SoC bounds, efficiency asymmetry, non-linear
derating, thermal trip, degradation), the dispatch-engine constraint pipeline
(ramp, grid clip, planned outage), config validation, and telemetry emission.

Dependencies are intentionally minimal: `numpy`, `matplotlib`, `pyyaml`,
`click`. The step loop is written in readable step-wise form rather than
vectorised, to keep the conditional feedback (temperature → aux load → available
power → SoC → temperature) easy to follow.
