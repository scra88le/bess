"""Ramping, thermal, and degradation edge-case tests."""

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
        "thermal_mass": 1.0e9,  # large -> temperature is a non-factor here
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


def test_ramp_limit_enforced(capsys) -> None:
    """A step jump in dispatch is held to ramping_limit_mw_per_sec."""
    engine = make_engine()  # ramp = 2.0 MW/s, prev starts at 0
    engine.run([10.0])
    row = engine.telemetry.rows[0]
    assert row["actual_mw"] == pytest.approx(2.0, abs=1e-6)
    assert "Ramp Limit Exceeded" in capsys.readouterr().err


def test_ramp_limit_allows_gradual_change() -> None:
    """Within the ramp limit the setpoint passes through untouched."""
    engine = make_engine()
    engine.run([2.0, 4.0, 6.0])  # each step is exactly +2 MW
    actuals = [r["actual_mw"] for r in engine.telemetry.rows]
    assert actuals == pytest.approx([2.0, 4.0, 6.0], abs=1e-6)


def test_grid_export_import_clipped(capsys) -> None:
    """Actual power is hard-clipped to the grid max export/import."""
    # Open the ramp limit so the grid clip is the binding constraint.
    engine = make_engine(ramping_limit_mw_per_sec=1000.0)
    engine.run([100.0])  # well above max_export 45
    assert engine.telemetry.rows[0]["actual_mw"] == pytest.approx(45.0, abs=1e-6)
    assert "Grid Constrained" in capsys.readouterr().err

    engine = make_engine(ramping_limit_mw_per_sec=1000.0)
    engine.run([-100.0])  # below -max_import 45
    assert engine.telemetry.rows[0]["actual_mw"] == pytest.approx(-45.0, abs=1e-6)


def test_planned_outage_masks_dispatch(capsys) -> None:
    """Dispatch is forced to 0 MW during a maintenance window."""
    engine = make_engine(ramping_limit_mw_per_sec=1000.0, planned_outages=[(0, 1)])
    engine.run([10.0, 10.0, 10.0])
    rows = engine.telemetry.rows
    assert rows[0]["actual_mw"] == 0.0
    assert rows[1]["actual_mw"] == 0.0
    assert rows[2]["actual_mw"] == pytest.approx(10.0, abs=1e-3)
    assert "Planned Outage" in capsys.readouterr().err


def test_ramp_measured_against_actual_not_setpoint() -> None:
    """After a clip/outage, ramping resumes from the actual delivered power."""
    engine = make_engine(planned_outages=[(0, 0)])
    engine.run([10.0, 10.0])  # t0 outage -> 0; t1 ramps from 0
    rows = engine.telemetry.rows
    assert rows[0]["actual_mw"] == 0.0
    assert rows[1]["actual_mw"] == pytest.approx(2.0, abs=1e-6)


def test_negative_efficiency_raises(tmp_path) -> None:
    """A physically impossible parameter raises ConfigError at startup."""
    from src.config_loader import ConfigError, load_config

    cfg = tmp_path / "bad.yaml"
    cfg.write_text(_render_config(efficiency=-0.5))
    with pytest.raises(ConfigError):
        load_config(str(cfg))


def _render_config(**overrides) -> str:
    """Serialise BASE (with overrides) back to YAML for loader tests."""
    import yaml

    data = {
        "nominal_capacity_mwh": BASE.nominal_capacity_mwh,
        "initial_soc": BASE.initial_soc,
        "efficiency": BASE.efficiency,
        "ramping_limit_mw_per_sec": BASE.ramping_limit_mw_per_sec,
        "thermal": dict(BASE.thermal),
        "soc_non_linearity": dict(BASE.soc_non_linearity),
        "auxiliary_load_kw": dict(BASE.auxiliary_load_kw),
        "grid_constraints": dict(BASE.grid_constraints),
        "warranty": dict(BASE.warranty),
        "degradation": dict(BASE.degradation),
    }
    data.update(overrides)
    return yaml.safe_dump(data)
