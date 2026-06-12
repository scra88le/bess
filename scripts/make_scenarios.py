"""Generate self-contained example scenarios for the BESS model.

Each scenario is written to ``scenarios/<name>/`` as a ``config.yaml`` +
``dispatch.csv`` pair, runnable directly with::

    python main.py --config scenarios/<name>/config.yaml \
                   --dispatch scenarios/<name>/dispatch.csv

Run this script from the repo root::

    .venv/bin/python scripts/make_scenarios.py            # generate
    .venv/bin/python scripts/make_scenarios.py --verify   # generate + run + report
"""

from __future__ import annotations

import copy
import csv
import math
import os
import sys
from typing import Callable, Dict, List

import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
SCENARIO_DIR = os.path.join(REPO_ROOT, "scenarios")

# --------------------------------------------------------------------- #
# Base configuration (mirrors the repo config.yaml). Scenarios deep-merge
# overrides onto this so each file is complete and self-validating.
# --------------------------------------------------------------------- #
BASE_CONFIG: Dict = {
    "nominal_capacity_mwh": 50.0,
    "initial_soc": 0.50,
    "efficiency": 0.92,
    "ramping_limit_mw_per_sec": 2.0,
    "thermal": {
        "initial_temp_c": 25.0,
        "ambient_temp_c": 20.0,
        "thermal_mass": 300000000.0,
        "hvac_cooling_rate_c_per_sec": 0.05,
        "optimal_temp_c": 20.0,
        "max_cell_temp_c": 60.0,
    },
    "soc_non_linearity": {
        "lower_threshold": 0.10,
        "upper_threshold": 0.90,
        "exponential_factor": 2.5,
    },
    "auxiliary_load_kw": {"base": 50.0, "hvac_per_degree": 10.0},
    "grid_constraints": {"max_export_mw": 45.0, "max_import_mw": 45.0},
    "warranty": {"max_equivalent_full_cycles": 3000},
    "degradation": {"cycle_loss_per_efc": 0.0000667, "calendar_loss_per_year": 0.02},
    "planned_outages": [],
}


# --------------------------------------------------------------------- #
# Dispatch signal builders (each returns MW for a given second t)
# --------------------------------------------------------------------- #
def constant(value: float) -> Callable[[int], float]:
    return lambda t: value


def square(amplitude: float, half_period_s: int) -> Callable[[int], float]:
    return lambda t: amplitude if (t // half_period_s) % 2 == 0 else -amplitude


def sine(amplitude: float, period_s: int, offset: float = 0.0) -> Callable[[int], float]:
    return lambda t: offset + amplitude * math.sin(2 * math.pi * t / period_s)


def step_then_reverse(value: float, switch_s: int) -> Callable[[int], float]:
    return lambda t: value if t < switch_s else -value


# --------------------------------------------------------------------- #
# Scenario definitions
# --------------------------------------------------------------------- #
class Scenario:
    def __init__(self, name: str, summary: str, overrides: Dict,
                 dispatch: Callable[[int], float], seconds: int) -> None:
        self.name = name
        self.summary = summary
        self.overrides = overrides
        self.dispatch = dispatch
        self.seconds = seconds


SCENARIOS: List[Scenario] = [
    Scenario(
        "01_grid_clip",
        "Command 60 MW with the ramp limit opened up; output is hard-clipped to the 45 MW grid limit (export then import).",
        {"ramping_limit_mw_per_sec": 1000.0},
        step_then_reverse(60.0, 600),
        1200,
    ),
    Scenario(
        "02_ramp_limit",
        "+/-40 MW square wave the inverter cannot follow; actual power sawtooths toward each target at 2 MW/s.",
        {},
        square(40.0, 120),
        1200,
    ),
    Scenario(
        "03_soc_saturation",
        "Sustained 25 MW discharge drains SoC through the 10% non-linear knee; output derates as resistance rises near the floor (SoC ~0.07).",
        {},
        constant(25.0),
        3600,
    ),
    Scenario(
        "04_efficiency_drain",
        "Pure zero-mean 30 MW sine (10 min cycles); SoC drifts down each cycle from round-trip + aux losses.",
        {},
        sine(30.0, 600),
        3600,
    ),
    Scenario(
        "05_aux_load",
        "Idle (0 MW) dispatch with a hot start and heavy aux load; SoC bleeds down and aux decays as the cell cools to optimal.",
        {
            "auxiliary_load_kw": {"base": 2000.0, "hvac_per_degree": 200.0},
            "thermal": {"initial_temp_c": 45.0, "ambient_temp_c": 20.0,
                        "optimal_temp_c": 20.0},
        },
        constant(0.0),
        3600,
    ),
    Scenario(
        "06_planned_outage",
        "Steady 20 MW discharge with a maintenance window at t=1200..1800 s; dispatch is masked to 0 then ramps back.",
        {"planned_outages": [[1200, 1800]]},
        constant(20.0),
        2400,
    ),
    Scenario(
        "07_warranty_breach",
        "Heavy +/-45 MW cycling with a deliberately low warranty limit (0.3 EFC) and exaggerated fade; the warranty flag trips mid-run.",
        {
            "warranty": {"max_equivalent_full_cycles": 0.3},
            "degradation": {"cycle_loss_per_efc": 0.05, "calendar_loss_per_year": 0.02},
        },
        square(45.0, 120),
        3600,
    ),
    Scenario(
        "08_thermal_trip",
        "Hot day + small thermal envelope; sustained 45 MW discharge heats the cells past 60 C and the battery trips, then cycles around the limit.",
        {"thermal": {"initial_temp_c": 40.0, "ambient_temp_c": 35.0,
                     "thermal_mass": 30000000.0, "optimal_temp_c": 35.0}},
        constant(45.0),
        3600,
    ),
    Scenario(
        "09_compound_hot_gridclip",
        "Hot day AND a 60 MW over-command: grid clip to 45 MW, thermal trip, and ramp-limited recovery all interact.",
        {"thermal": {"initial_temp_c": 40.0, "ambient_temp_c": 35.0,
                     "thermal_mass": 30000000.0, "optimal_temp_c": 35.0}},
        constant(60.0),
        1200,
    ),
]


# --------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------- #
def _deep_merge(base: Dict, overrides: Dict) -> Dict:
    out = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _write_scenario(sc: Scenario) -> None:
    folder = os.path.join(SCENARIO_DIR, sc.name)
    os.makedirs(folder, exist_ok=True)

    config = _deep_merge(BASE_CONFIG, sc.overrides)
    header = f"# Scenario: {sc.name}\n# {sc.summary}\n"
    with open(os.path.join(folder, "config.yaml"), "w") as fh:
        fh.write(header)
        yaml.safe_dump(config, fh, sort_keys=False, default_flow_style=False)

    with open(os.path.join(folder, "dispatch.csv"), "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["timestamp_s", "dispatch_mw"])
        for t in range(sc.seconds):
            writer.writerow([t, round(sc.dispatch(t), 4)])


def generate_all() -> None:
    os.makedirs(SCENARIO_DIR, exist_ok=True)
    for sc in SCENARIOS:
        _write_scenario(sc)
        print(f"generated scenarios/{sc.name}/  ({sc.seconds} s)")


# --------------------------------------------------------------------- #
# Verification: run each scenario and report the key signal
# --------------------------------------------------------------------- #
def verify_all() -> None:
    from contextlib import redirect_stderr
    import io
    import re

    from src.battery import Battery
    from src.config_loader import load_config
    from src.dispatch_engine import DispatchEngine
    from src.telemetry import Telemetry

    print(f"\n{'scenario':<26} {'reasons seen':<46} key metrics")
    print("-" * 110)
    for sc in SCENARIOS:
        folder = os.path.join(SCENARIO_DIR, sc.name)
        cfg = load_config(os.path.join(folder, "config.yaml"))
        disp = [float(r["dispatch_mw"])
                for r in csv.DictReader(open(os.path.join(folder, "dispatch.csv")))]
        eng = DispatchEngine(cfg, Battery(cfg), Telemetry())
        err = io.StringIO()
        with redirect_stderr(err):                     # capture alarm blocks
            eng.run(disp)
        rows = eng.telemetry.rows

        # Reasons come from two places: battery-stage limits land in each row's
        # limit_reason; engine-stage clamps (grid/ramp/outage) are logged to
        # stderr. Merge both so the report covers the whole pipeline.
        reasons = {r["limit_reason"] for r in rows if r["limit_reason"]}
        reasons |= set(re.findall(r"Reason: \[([^\]]+)\]", err.getvalue()))
        reasons = sorted(reasons)
        socs = eng.telemetry.column("soc")
        temps = eng.telemetry.column("cell_temp_c")
        metrics = (
            f"SoC {socs[0]:.2f}->{socs[-1]:.2f} (min {min(socs):.2f}) | "
            f"peakT {max(temps):.1f}C | "
            f"EFC {rows[-1]['equivalent_full_cycles']:.3f} | "
            f"warranty={'BREACHED' if rows[-1]['warranty_breached'] else 'ok'}"
        )
        print(f"{sc.name:<26} {', '.join(reasons) or '(none)':<46} {metrics}")


if __name__ == "__main__":
    generate_all()
    if "--verify" in sys.argv:
        verify_all()
