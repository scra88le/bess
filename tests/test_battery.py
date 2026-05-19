from __future__ import annotations

import pytest

from bess.battery import EnergyBucketBattery
from bess.config import SiteSpec


def make_site(**overrides) -> SiteSpec:
    base = dict(
        power_mw=10.0,
        energy_mwh=20.0,
        eta_charge=0.9,
        eta_discharge=0.9,
        soc_min_frac=0.0,
        soc_max_frac=1.0,
        soc_initial_frac=0.5,
    )
    base.update(overrides)
    return SiteSpec(**base)


def test_charge_then_discharge_round_trip_loses_efficiency():
    site = make_site(eta_charge=0.9, eta_discharge=0.9, soc_initial_frac=0.5)
    bat = EnergyBucketBattery(site, timestep_hours=1.0)

    # Charge for 1h at 5 MW: grid in = 5 MWh, bucket gains 4.5 MWh.
    r1 = bat.step(-5.0)
    assert r1.power_actual_mw == pytest.approx(-5.0)
    assert r1.soc_mwh == pytest.approx(10.0 + 0.9 * 5.0)
    assert not r1.clipped

    # Discharge same period: bucket loses 5/0.9 MWh, grid out = 5 MWh.
    r2 = bat.step(5.0)
    assert r2.power_actual_mw == pytest.approx(5.0)
    assert r2.soc_mwh == pytest.approx(14.5 - 5.0 / 0.9)
    # Round-trip loss vs starting SoC of 10:
    assert r2.soc_mwh < 10.0


def test_clipped_when_soc_at_floor():
    site = make_site(soc_initial_frac=0.0)
    bat = EnergyBucketBattery(site, timestep_hours=1.0)
    result = bat.step(5.0)  # ask to discharge with empty bucket
    assert result.clipped
    assert result.power_actual_mw == pytest.approx(0.0)
    assert result.soc_mwh == pytest.approx(0.0)


def test_clipped_when_soc_at_ceiling():
    site = make_site(soc_initial_frac=1.0)
    bat = EnergyBucketBattery(site, timestep_hours=1.0)
    result = bat.step(-5.0)
    assert result.clipped
    assert result.power_actual_mw == pytest.approx(0.0)
    assert result.soc_mwh == pytest.approx(20.0)


def test_clipped_when_setpoint_exceeds_power_limit():
    # Big enough battery that the power limit binds, not the energy bound.
    site = make_site(power_mw=10.0, energy_mwh=200.0, soc_initial_frac=0.5)
    bat = EnergyBucketBattery(site, timestep_hours=1.0)
    result = bat.step(99.0)
    assert result.clipped
    assert result.power_actual_mw == pytest.approx(10.0)
