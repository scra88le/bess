# BESS example scenarios

Each subfolder is a self-contained scenario: a `config.yaml` (physical
parameters) plus a `dispatch.csv` (1 s-resolution setpoints) designed to
exercise one behaviour of the model. Run any of them by name:

```bash
.venv/bin/python main.py --scenario <name>
```

(equivalently, point `--config scenarios/<name>/config.yaml` and
`--dispatch scenarios/<name>/dispatch.csv` at the files directly).

Add `--visualize` for the live dashboard, or redirect the streams to inspect
them separately — telemetry goes to **stdout**, `[VIOLATION]` alarms to
**stderr**:

```bash
... --config scenarios/<name>/config.yaml --dispatch scenarios/<name>/dispatch.csv \
    > telemetry.csv 2> violations.log
```

These files are generated. To rebuild them (and re-verify each one triggers its
intended behaviour):

```bash
.venv/bin/python scripts/make_scenarios.py --verify
```

## The scenarios

| # | Scenario | Lever exercised | What to watch |
|---|----------|-----------------|---------------|
| 01 | `grid_clip` | Grid export/import clip | `actual_mw` pinned at ±45 though 60 is commanded; `Reason: [Grid Constrained]`. Ramp limit is opened up so the grid clip is what binds. |
| 02 | `ramp_limit` | Ramp rate (MW/s) | ±40 square wave; `actual_mw` sawtooths toward each target at 2 MW/s; `Reason: [Ramp Limit Exceeded]`. |
| 03 | `soc_saturation` | SoC non-linearity | Sustained 25 MW discharge; `actual_mw` derates below target as SoC falls past 0.10 (`SoC Non-Linear Limit`), settling near SoC ≈ 0.07 as resistance rises. |
| 04 | `efficiency_drain` | Round-trip + aux losses | Pure zero-mean 30 MW sine; **no violations**, but SoC drifts down each cycle (≈0.50 → 0.47 over the hour) purely from losses. |
| 05 | `aux_load` | Parasitic / HVAC load | Idle (0 MW) dispatch, hot 45 °C start, heavy aux; SoC bleeds down with no dispatch, and `aux_load_mw` decays as the cell cools toward optimal (Temp→Aux feedback). |
| 06 | `planned_outage` | Maintenance masking | Steady 20 MW with an outage window at t=1200–1800 s; `actual_mw` forced to 0 (`Planned Outage`), then ramps back up. |
| 07 | `warranty_breach` | Degradation / warranty | Heavy ±45 MW cycling with a low limit (0.3 EFC) and exaggerated fade; `equivalent_full_cycles` crosses the limit and `warranty_breached` → 1 mid-run. |
| 08 | `thermal_trip` | Thermal cutoff | Hot day + small thermal envelope; sustained 45 MW heats cells past 60 °C, battery trips to 0 (`Thermal Trip`), then chatters around the limit. |
| 09 | `compound_hot_gridclip` | Multiple at once | Hot day **and** a 60 MW over-command: grid clip, thermal trip, and ramp-limited recovery all interact in the same run. |

## Notes

- **Why some scenarios need a custom config.** The base `config.yaml` is tuned
  for realistic, well-behaved operation — its HVAC always out-cools dispatch
  heating, and the warranty limit (3000 EFC) is ~280 days away at full power. So
  the thermal-trip and warranty scenarios deliberately use adverse / scaled
  parameters (hot ambient, small thermal mass, low EFC limit, exaggerated fade)
  to make those limits reachable inside a short run. The relevant knobs are
  noted in each `config.yaml` header.
- **Startup ramp.** Constant-power scenarios log a few `Ramp Limit Exceeded`
  alarms at t=0 as power ramps from 0 to the setpoint — expected, not the point
  of the scenario.
