"""Tests for external per-step driving of the DispatchEngine."""

from __future__ import annotations

import copy

import pytest

from src.battery import Battery
from src.config_loader import Config
from src.dispatch_engine import DispatchEngine
from src.telemetry import Telemetry

BASE = Config(
    nominal_capacity_mwh=50.0,
    initial_soc=0.50,
    efficiency=0.92,
    ramping_limit_mw_per_sec=2.0,
    thermal={
        "initial_temp_c": 25.0,
        "ambient_temp_c": 20.0,
        "thermal_mass": 1.0e9,
        "hvac_cooling_rate_c_per_sec": 0.05,
        "optimal_temp_c": 20.0,
        "max_cell_temp_c": 60.0,
    },
    soc_non_linearity={
        "lower_threshold": 0.10,
        "upper_threshold": 0.90,
        "exponential_factor": 2.5,
    },
    auxiliary_load_kw={"base": 50.0, "hvac_per_degree": 10.0},
    grid_constraints={"max_export_mw": 45.0, "max_import_mw": 45.0},
    warranty={"max_equivalent_full_cycles": 3000},
    degradation={"cycle_loss_per_efc": 0.0000667, "calendar_loss_per_year": 0.02},
)


def make_engine(**overrides) -> DispatchEngine:
    cfg = copy.deepcopy(BASE)
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return DispatchEngine(cfg, Battery(cfg), Telemetry())


def test_step_matches_run() -> None:
    """Calling step() in a loop is identical to run() on a fresh engine."""
    signal = [5.0, 10.0, -3.0, 0.0, 8.0]

    via_run = make_engine()
    via_run.run(signal)

    via_step = make_engine()
    for mw in signal:
        via_step.step(mw)

    assert [r["actual_mw"] for r in via_step.telemetry.rows] == [
        r["actual_mw"] for r in via_run.telemetry.rows
    ]
    assert [r["timestamp_s"] for r in via_step.telemetry.rows] == [
        r["timestamp_s"] for r in via_run.telemetry.rows
    ]


def test_step_increments_and_timestamps() -> None:
    eng = make_engine()
    eng.step(1.0)
    eng.step(1.0)
    assert eng._t == 2
    assert [r["timestamp_s"] for r in eng.telemetry.rows] == [0.0, 1.0]


def test_prev_power_persists_across_steps() -> None:
    """Ramp state carries over between step() calls."""
    eng = make_engine()
    eng.step(40.0)  # ramps from 0 to 2.0
    assert eng._prev_power_mw == pytest.approx(2.0, abs=1e-6)
    eng.step(40.0)  # ramps from 2.0 to 4.0
    assert eng._prev_power_mw == pytest.approx(4.0, abs=1e-6)


def test_begin_day_resets_outage_clock_only() -> None:
    """begin_day() resets the within-day outage clock but not ramp/global state."""
    # High ramp so outage masking maps straight to actual=0 (isolates outage logic).
    eng = make_engine(planned_outages=[(0, 1)], ramping_limit_mw_per_sec=1000.0)
    eng.step(20.0)  # _day_t 0 -> outage -> 0 MW
    eng.step(20.0)  # _day_t 1 -> outage -> 0 MW
    assert eng.telemetry.rows[0]["actual_mw"] == 0.0
    assert eng.telemetry.rows[1]["actual_mw"] == 0.0
    eng.step(20.0)  # _day_t 2 -> clear of outage
    assert eng.telemetry.rows[2]["actual_mw"] > 0.0

    global_t_before = eng._t
    eng.begin_day()
    assert eng._day_t == 0
    assert eng._t == global_t_before  # global index untouched
    eng.step(20.0)  # _day_t back to 0 -> outage again
    assert eng.telemetry.rows[3]["actual_mw"] == 0.0


def test_outage_is_seconds_since_midnight() -> None:
    """Outage windows recur per simulated day via begin_day()."""
    eng = make_engine(planned_outages=[(0, 0)], ramping_limit_mw_per_sec=1000.0)
    eng.step(15.0)  # day 1, second 0: outage
    assert eng.telemetry.rows[-1]["actual_mw"] == 0.0
    for _ in range(5):
        eng.step(15.0)  # later in day 1: no outage
    assert eng.telemetry.rows[-1]["actual_mw"] > 0.0
    eng.begin_day()
    eng.step(15.0)  # day 2, second 0: outage recurs
    assert eng.telemetry.rows[-1]["actual_mw"] == 0.0
