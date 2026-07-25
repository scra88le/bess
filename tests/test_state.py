"""Tests for checkpoint save/load/apply."""

from __future__ import annotations

import copy
import datetime as dt

from src.battery import Battery
from src.config_loader import Config
from src.dispatch_engine import DispatchEngine
from src.runtime import state
from src.runtime.sink import NullTelemetry

BASE = Config(
    nominal_capacity_mwh=50.0,
    initial_soc=0.50,
    efficiency=0.92,
    ramping_limit_mw_per_sec=2.0,
    thermal={
        "initial_temp_c": 25.0,
        "ambient_temp_c": 20.0,
        "thermal_mass": 3.0e8,
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


def test_load_absent_returns_none(tmp_path) -> None:
    assert state.load(str(tmp_path)) is None


def test_checkpoint_roundtrip(tmp_path) -> None:
    cfg = copy.deepcopy(BASE)
    battery = Battery(cfg)
    engine = DispatchEngine(cfg, battery, NullTelemetry())

    # Mutate state by stepping a bit.
    for _ in range(120):
        engine.step(30.0)
    battery.state.warranty_breached = True  # exercise the bool field
    sim_now = dt.datetime(2026, 6, 13, 0, 2, 0)

    state.save(str(tmp_path), battery, engine, sim_now, time_scale=60.0)

    # Restore into fresh objects.
    fresh_cfg = copy.deepcopy(BASE)
    fresh_battery = Battery(fresh_cfg)
    fresh_engine = DispatchEngine(fresh_cfg, fresh_battery, NullTelemetry())
    ckpt = state.load(str(tmp_path))
    restored_now = state.apply(ckpt, fresh_battery, fresh_engine)

    assert fresh_battery.state == battery.state  # dataclass equality, incl. warranty
    assert fresh_engine._prev_power_mw == engine._prev_power_mw
    assert fresh_engine._t == engine._t
    assert restored_now == sim_now
