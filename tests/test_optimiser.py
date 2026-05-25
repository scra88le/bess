from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bess.config import EfaConfig, SiteSpec
from bess.optimiser import (
    ServicePriceSeries,
    _assign_blocks,
    solve_perfect_foresight,
    solve_sequential,
)


def _site(**overrides) -> SiteSpec:
    base = dict(
        power_mw=50.0,
        energy_mwh=100.0,
        eta_charge=0.99,
        eta_discharge=0.99,
        soc_min_frac=0.05,
        soc_max_frac=0.95,
        soc_initial_frac=0.5,
    )
    base.update(overrides)
    return SiteSpec(**base)


def _flat_hourly_prices(hours: int = 24, value: float = 50.0) -> pd.Series:
    return pd.Series(
        [value] * hours,
        index=pd.date_range("2026-05-24T23:00", periods=hours, freq="60min"),
    )


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


def test_efa_block_partition_aligns_to_block_start_hour():
    # Index straddles 23:00 boundary: 21,22,23,00,01,02,03 → blocks 0,0,1,1,1,1,2.
    index = pd.date_range("2025-01-01T21:00", periods=7, freq="60min")
    blocks = _assign_blocks(index, block_hours=4, block_start_hour=23)
    assert list(blocks) == [0, 0, 1, 1, 1, 1, 2]


def test_sequential_with_no_services_matches_wholesale_only():
    prices = pd.Series(
        [20.0] * 4 + [120.0] * 4,
        index=pd.date_range("2026-05-24T23:00", periods=8, freq="60min"),
    )
    site = _site()
    wholesale = solve_perfect_foresight(prices, site, timestep_hours=1.0)
    result = solve_sequential(
        prices=prices,
        services={},
        site=site,
        timestep_hours=1.0,
        efa=EfaConfig(),
    )
    for col in ("price", "p_charge", "p_discharge", "p_net", "soc_planned"):
        assert np.allclose(result.schedule[col], wholesale[col], atol=1e-9)
    assert (result.schedule["c_dc_low"] == 0).all()
    assert (result.schedule["c_dc_high"] == 0).all()
    assert result.bid_curve.empty


def test_dc_low_cap_binds_on_power_when_soc_high():
    prices = _flat_hourly_prices(hours=8)  # flat → wholesale idle
    site = _site(energy_mwh=1000.0, soc_initial_frac=0.5)  # huge energy buffer
    dc_low = pd.Series([10.0] * 8, index=prices.index, name="dc_low")
    result = solve_sequential(
        prices=prices,
        services={"dc_low": ServicePriceSeries(dc_low, response_hours=0.25)},
        site=site,
        timestep_hours=1.0,
        efa=EfaConfig(),
    )
    cap = float(result.schedule["c_dc_low"].iloc[0])
    assert cap == pytest.approx(site.power_mw, abs=1e-6)
    assert (result.bid_curve["binding_constraint"] == "power").all()


def test_dc_low_cap_binds_on_energy_when_soc_low():
    prices = _flat_hourly_prices(hours=8)
    site = _site(energy_mwh=5.0, soc_min_frac=0.0, soc_max_frac=1.0, soc_initial_frac=0.5)
    dc_low = pd.Series([10.0] * 8, index=prices.index, name="dc_low")
    result = solve_sequential(
        prices=prices,
        services={"dc_low": ServicePriceSeries(dc_low, response_hours=0.25)},
        site=site,
        timestep_hours=1.0,
        efa=EfaConfig(),
    )
    # Energy headroom = (2.5 - 0) * 0.99 / 0.25 = 9.9 MW; power = 50 MW
    cap = float(result.schedule["c_dc_low"].iloc[0])
    assert cap == pytest.approx(2.5 * 0.99 / 0.25, abs=1e-6)
    assert cap < site.power_mw
    assert (result.bid_curve["binding_constraint"] == "energy").all()


def test_dc_high_symmetric_to_dc_low():
    prices = _flat_hourly_prices(hours=8)
    site = _site(energy_mwh=5.0, soc_min_frac=0.0, soc_max_frac=1.0, soc_initial_frac=0.5)
    dc_high = pd.Series([10.0] * 8, index=prices.index, name="dc_high")
    result = solve_sequential(
        prices=prices,
        services={"dc_high": ServicePriceSeries(dc_high, response_hours=0.25)},
        site=site,
        timestep_hours=1.0,
        efa=EfaConfig(),
    )
    # Energy headroom = (5 - 2.5) / (0.25 * 0.99) ≈ 10.10 MW
    cap = float(result.schedule["c_dc_high"].iloc[0])
    assert cap == pytest.approx(2.5 / (0.25 * 0.99), abs=1e-6)
    assert (result.bid_curve["binding_constraint"] == "energy").all()


def test_shared_rating_forces_priority_split_when_low_priced_higher():
    prices = _flat_hourly_prices(hours=8)
    # Tiny p_max forces shared rating to bind.
    site = _site(power_mw=20.0, energy_mwh=1000.0)
    dc_low = pd.Series([20.0] * 8, index=prices.index, name="dc_low")
    dc_high = pd.Series([5.0] * 8, index=prices.index, name="dc_high")
    result = solve_sequential(
        prices=prices,
        services={
            "dc_low": ServicePriceSeries(dc_low, response_hours=0.25),
            "dc_high": ServicePriceSeries(dc_high, response_hours=0.25),
        },
        site=site,
        timestep_hours=1.0,
        efa=EfaConfig(),
    )
    cap_low = float(result.schedule["c_dc_low"].iloc[0])
    cap_high = float(result.schedule["c_dc_high"].iloc[0])
    # DC-Low priority: takes full p_max, DC-High gets zero.
    assert cap_low == pytest.approx(site.power_mw, abs=1e-6)
    assert cap_high == pytest.approx(0.0, abs=1e-6)


def test_bid_curve_two_tranches_when_shared_rating_binds():
    prices = _flat_hourly_prices(hours=8)
    site = _site(power_mw=20.0, energy_mwh=1000.0)
    dc_low = pd.Series([20.0] * 8, index=prices.index, name="dc_low")
    dc_high = pd.Series([5.0] * 8, index=prices.index, name="dc_high")
    result = solve_sequential(
        prices=prices,
        services={
            "dc_low": ServicePriceSeries(dc_low, response_hours=0.25),
            "dc_high": ServicePriceSeries(dc_high, response_hours=0.25),
        },
        site=site,
        timestep_hours=1.0,
        efa=EfaConfig(),
    )
    low_curve = result.bid_curve[result.bid_curve["service"] == "dc_low"]
    # Two tranches per block; in this test there are 2 blocks (8h / 4h).
    counts = low_curve.groupby("block_start").size()
    assert (counts == 2).all()
    # First tranche always at price 0; second at the other service's forecast.
    first = low_curve.iloc[0]
    second = low_curve.iloc[1]
    assert first["price_threshold_gbp_per_mw_h"] == pytest.approx(0.0)
    assert second["price_threshold_gbp_per_mw_h"] == pytest.approx(5.0, abs=1e-6)
    assert second["mw_cumulative"] > first["mw_cumulative"]


def test_bid_curve_single_tranche_when_shared_rating_slack():
    prices = _flat_hourly_prices(hours=8)
    # Small battery limits each service's energy headroom; big p_max → shared rating slack.
    site = _site(
        power_mw=200.0,
        energy_mwh=20.0,
        soc_min_frac=0.0,
        soc_max_frac=1.0,
        soc_initial_frac=0.5,
    )
    dc_low = pd.Series([10.0] * 8, index=prices.index, name="dc_low")
    dc_high = pd.Series([10.0] * 8, index=prices.index, name="dc_high")
    result = solve_sequential(
        prices=prices,
        services={
            "dc_low": ServicePriceSeries(dc_low, response_hours=0.25),
            "dc_high": ServicePriceSeries(dc_high, response_hours=0.25),
        },
        site=site,
        timestep_hours=1.0,
        efa=EfaConfig(),
    )
    counts = result.bid_curve.groupby(["service", "block_start"]).size()
    assert (counts == 1).all()


def test_bid_curve_expected_revenue_matches_cap_times_price_times_hours():
    prices = _flat_hourly_prices(hours=8)
    site = _site(
        power_mw=200.0,
        energy_mwh=20.0,
        soc_min_frac=0.0,
        soc_max_frac=1.0,
        soc_initial_frac=0.5,
    )
    dc_low = pd.Series([10.0] * 8, index=prices.index, name="dc_low")
    dc_high = pd.Series([7.0] * 8, index=prices.index, name="dc_high")
    result = solve_sequential(
        prices=prices,
        services={
            "dc_low": ServicePriceSeries(dc_low, response_hours=0.25),
            "dc_high": ServicePriceSeries(dc_high, response_hours=0.25),
        },
        site=site,
        timestep_hours=1.0,
        efa=EfaConfig(),
    )
    # For each row, expected_revenue = mw_cumulative * forecast_price * block_hours
    # but mw_cumulative is the *bid* MW. The realised revenue corresponds to the
    # final tranche's MW (i.e., the `cap` allocated). With slack rating, single
    # tranche = the cap.
    for _, row in result.bid_curve.iterrows():
        expected = (
            row["mw_cumulative"]
            * row["forecast_price_gbp_per_mw_h"]
            * row["block_hours"]
        )
        assert row["expected_revenue_gbp"] == pytest.approx(expected, abs=1e-6)
