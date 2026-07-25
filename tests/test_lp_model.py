"""Tests for the day-ahead LP optimiser."""

from __future__ import annotations

import copy

import pytest

from src.config_loader import Config
from src.optimiser import OptimiseOptions, Schedule, optimise

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

# 24 hourly periods: cheap first half, expensive second half.
PRICES = [10.0] * 12 + [100.0] * 12
RES = 60


def cfg(**overrides) -> Config:
    c = copy.deepcopy(BASE)
    for k, v in overrides.items():
        setattr(c, k, v)
    return c


def _reconstruct_soc(config: Config, sched: Schedule):
    """Replay the LP's own SoC recurrence to check feasibility."""
    eta = config.efficiency
    cap = config.nominal_capacity_mwh
    h = sched.resolution_minutes / 60.0
    soc = config.initial_soc
    traj = []
    for p in sched.power_mw:
        dis = max(0.0, p)
        chg = max(0.0, -p)
        soc += (-(dis / eta) + chg * eta) * h / cap
        traj.append(soc)
    return traj


def test_solves_and_arbitrages() -> None:
    sched = optimise(cfg(), PRICES, RES)
    assert len(sched.power_mw) == 24
    assert sched.objective_value > 0  # captured arbitrage
    # Charges (power < 0) in the cheap half, discharges (> 0) in the expensive half.
    assert min(sched.power_mw[:12]) < 0
    assert max(sched.power_mw[12:]) > 0
    # Net discharge energy is concentrated in the expensive window.
    assert sum(p for p in sched.power_mw[12:] if p > 0) > 0


def test_respects_soc_band_and_power_limits() -> None:
    sched = optimise(cfg(), PRICES, RES)
    traj = _reconstruct_soc(cfg(), sched)
    s_lo, s_hi = 0.10, 0.90
    assert all(s_lo - 1e-6 <= s <= s_hi + 1e-6 for s in traj)
    assert all(-45.0 - 1e-6 <= p <= 45.0 + 1e-6 for p in sched.power_mw)


def test_returns_to_initial_soc_by_default() -> None:
    sched = optimise(cfg(), PRICES, RES)
    traj = _reconstruct_soc(cfg(), sched)
    assert traj[-1] == pytest.approx(BASE.initial_soc, abs=2e-3)


def test_custom_terminal_soc() -> None:
    sched = optimise(cfg(), PRICES, RES, OptimiseOptions(terminal_soc=0.30))
    traj = _reconstruct_soc(cfg(), sched)
    assert traj[-1] == pytest.approx(0.30, abs=2e-3)


def test_degradation_cost_reduces_throughput() -> None:
    free = optimise(cfg(), PRICES, RES, OptimiseOptions(degradation_cost=0.0))
    taxed = optimise(cfg(), PRICES, RES, OptimiseOptions(degradation_cost=1000.0))

    def tp(s):
        return sum(abs(p) for p in s.power_mw)

    assert tp(taxed) <= tp(free)


def test_flat_prices_no_arbitrage() -> None:
    """With flat prices and a degradation cost, the optimiser stays essentially idle.

    (CBC may leave a negligible amount of degenerate throughput within its
    tolerance, so compare against an 'active' arbitrage run rather than zero.)
    """
    flat = optimise(cfg(), [50.0] * 24, RES, OptimiseOptions(degradation_cost=0.1))
    active = optimise(cfg(), PRICES, RES)
    flat_tp = sum(abs(p) for p in flat.power_mw)
    active_tp = sum(abs(p) for p in active.power_mw)
    assert flat_tp < 1.0  # negligible vs ...
    assert active_tp > 20.0  # ... a real arbitrage cycle


def test_empty_prices_raises() -> None:
    from src.optimiser import OptimisationError

    with pytest.raises(OptimisationError):
        optimise(cfg(), [], RES)


def test_schedule_power_at_second() -> None:
    sched = Schedule(
        date="2026-06-13", resolution_minutes=60, power_mw=[5.0, -3.0], terminal_soc=0.5
    )
    assert sched.power_at_second(0) == 5.0
    assert sched.power_at_second(3599) == 5.0
    assert sched.power_at_second(3600) == -3.0
    assert sched.power_at_second(999999) == -3.0  # clamped to last period
