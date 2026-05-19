from __future__ import annotations

import pandas as pd
import pytest

from bess.config import SiteSpec
from bess.optimiser import solve_perfect_foresight


def test_charges_in_cheap_discharges_in_expensive():
    # 4 half-hour periods: cheap, cheap, expensive, expensive.
    prices = pd.Series(
        [10.0, 10.0, 100.0, 100.0],
        index=pd.date_range("2025-01-01", periods=4, freq="30min"),
    )
    site = SiteSpec(
        power_mw=10.0,
        energy_mwh=20.0,
        eta_charge=0.95,
        eta_discharge=0.95,
        soc_min_frac=0.0,
        soc_max_frac=1.0,
        soc_initial_frac=0.5,
    )
    schedule = solve_perfect_foresight(prices, site, timestep_hours=0.5)

    # Expect non-zero charging in periods 0/1 and discharging in 2/3.
    assert schedule.iloc[0]["p_charge"] > 0
    assert schedule.iloc[2]["p_discharge"] > 0
    # Either-or per timestep (round-trip loss makes simultaneous suboptimal).
    for _, row in schedule.iterrows():
        assert row["p_charge"] * row["p_discharge"] == pytest.approx(0.0, abs=1e-6)
    # Terminal SoC pinned to initial.
    assert schedule.iloc[-1]["soc_planned"] == pytest.approx(10.0, abs=1e-3)


def test_revenue_positive_with_arbitrage_signal():
    prices = pd.Series(
        [20.0] * 24 + [120.0] * 24,
        index=pd.date_range("2025-01-01", periods=48, freq="30min"),
    )
    site = SiteSpec(
        power_mw=10.0, energy_mwh=20.0, eta_charge=0.9, eta_discharge=0.9,
    )
    schedule = solve_perfect_foresight(prices, site, timestep_hours=0.5)
    revenue = (schedule["price"] * schedule["p_net"] * 0.5).sum()
    assert revenue > 0
