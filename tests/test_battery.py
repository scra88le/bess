"""Physics & state boundary tests for the Battery model."""

from __future__ import annotations

import copy

import pytest

from src.battery import Battery
from src.config_loader import Config

BASE = Config(
    nominal_capacity_mwh=50.0,
    initial_soc=0.50,
    efficiency=0.92,
    ramping_limit_mw_per_sec=2.0,
    thermal={
        "initial_temp_c": 25.0,
        "ambient_temp_c": 20.0,
        # Large thermal mass keeps temps sane for directional assertions.
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


def make_battery(**overrides) -> Battery:
    cfg = copy.deepcopy(BASE)
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return Battery(cfg)


def test_soc_stays_within_bounds() -> None:
    """SoC must never leave [0, 1] regardless of how hard we push."""
    battery = make_battery(initial_soc=0.05)
    for _ in range(10_000):  # sustained heavy discharge
        battery.step(40.0)
        assert 0.0 <= battery.state.soc <= 1.0
    assert battery.state.soc == 0.0  # pinned at the floor

    battery = make_battery(initial_soc=0.95)
    for _ in range(10_000):  # sustained heavy charge
        battery.step(-40.0)
        assert 0.0 <= battery.state.soc <= 1.0
    assert battery.state.soc == 1.0


def test_efficiency_applied_per_direction() -> None:
    """Charging stores P*eta; discharging draws P/eta from the cells.

    For the same grid-side magnitude, a discharge drains the cells more than a
    charge fills them, purely from the efficiency asymmetry. Measure the
    battery's own action by netting out the parasitic aux drain.
    """
    p = 20.0
    dt = 1.0

    charger = make_battery()
    aux_charge = charger.auxiliary_load_mw()
    soc0 = charger.state.soc
    charger.step(-p, dt)
    cap = charger.config.nominal_capacity_mwh * (
        1.0 - charger.state.capacity_loss_fraction
    )
    # Δsoc = (-batt_in - aux) / cap  ->  batt cell energy gained:
    gained = (charger.state.soc - soc0) * cap + aux_charge * dt / 3600.0

    discharger = make_battery()
    aux_dis = discharger.auxiliary_load_mw()
    soc0 = discharger.state.soc
    discharger.step(p, dt)
    drawn = (soc0 - discharger.state.soc) * cap - aux_dis * dt / 3600.0

    expected_gain = p * 0.92 * dt / 3600.0
    expected_draw = p / 0.92 * dt / 3600.0
    assert gained == pytest.approx(expected_gain, rel=1e-6)
    assert drawn == pytest.approx(expected_draw, rel=1e-6)
    assert drawn > gained


def test_nonlinear_resistance_near_extremes() -> None:
    """Capability is full in the linear range and derated past the thresholds."""
    # Discharge limited near the bottom rail.
    low = make_battery(initial_soc=0.05)
    result = low.step(30.0)
    assert 0.0 < result["actual_mw"] < 30.0
    assert result["limit_reason"] == "SoC Non-Linear Limit"

    # Charge limited near the top rail.
    high = make_battery(initial_soc=0.95)
    result = high.step(-30.0)
    assert -30.0 < result["actual_mw"] < 0.0
    assert result["limit_reason"] == "SoC Non-Linear Limit"

    # No derate comfortably inside the linear range.
    mid = make_battery(initial_soc=0.50)
    result = mid.step(30.0)
    assert result["actual_mw"] == pytest.approx(30.0)
    assert result["limit_reason"] == ""


def test_thermal_trip_zeroes_power() -> None:
    """At/above the cutoff temperature the battery trips to 0 MW."""
    battery = make_battery()
    battery.state.cell_temp_c = 65.0
    result = battery.step(30.0)
    assert result["actual_mw"] == 0.0
    assert result["limit_reason"] == "Thermal Trip"


def test_discharge_heats_cells() -> None:
    """Resistive loss from throughput raises cell temperature."""
    battery = make_battery(initial_soc=0.80)
    # Small thermal mass so a single step is observable.
    battery.config.thermal["thermal_mass"] = 1.0e6
    battery.config.thermal["hvac_cooling_rate_c_per_sec"] = 0.0
    start = battery.state.cell_temp_c
    battery.step(40.0)
    assert battery.state.cell_temp_c > start


def test_degradation_and_warranty_flag() -> None:
    """Throughput accrues EFC and trips the warranty flag past the limit."""
    battery = make_battery()
    battery.config.warranty["max_equivalent_full_cycles"] = 0.0001
    result = battery.step(40.0)
    assert result["equivalent_full_cycles"] > 0.0
    assert result["cumulative_throughput_mwh"] > 0.0
    assert battery.state.warranty_breached is True
