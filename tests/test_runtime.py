from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from bess.config import (
    CsvPriceConfig,
    DcHighServiceConfig,
    DcLowServiceConfig,
    EfaConfig,
    ScenarioConfig,
    SiteSpec,
    SyntheticPriceConfig,
)
from bess.runtime import run


def test_end_to_end_smoke(tmp_path: Path):
    scenario = ScenarioConfig(
        site=SiteSpec(
            power_mw=10.0,
            energy_mwh=20.0,
            eta_charge=0.9,
            eta_discharge=0.9,
            soc_min_frac=0.05,
            soc_max_frac=0.95,
            soc_initial_frac=0.5,
        ),
        prices=SyntheticPriceConfig(days=2, peak_price=120.0, trough_price=20.0),
        timestep_minutes=30,
        output_dir=tmp_path,
    )
    result = run(scenario)

    assert (result.run_dir / "telemetry.parquet").exists()
    assert (result.run_dir / "summary.json").exists()
    assert (result.run_dir / "manifest.json").exists()

    assert result.summary["total_revenue_gbp"] > 0
    assert result.summary["throughput_mwh"] > 0

    # Perfect foresight: actuals should match setpoints (no clipping in a feasible plan).
    assert np.allclose(
        result.telemetry["p_actual_mw"], result.telemetry["p_setpoint_mw"], atol=1e-6
    )
    assert not result.telemetry["clipped"].any()


def test_end_to_end_with_dc_services(tmp_path: Path):
    repo_examples = Path(__file__).parent.parent / "examples"
    scenario = ScenarioConfig(
        site=SiteSpec(
            power_mw=50.0,
            energy_mwh=100.0,
            eta_charge=0.95,
            eta_discharge=0.95,
            soc_min_frac=0.05,
            soc_max_frac=0.95,
            soc_initial_frac=0.5,
        ),
        prices=CsvPriceConfig(path=repo_examples / "prices.csv"),
        services=[
            DcLowServiceConfig(path=repo_examples / "dc_low_prices.csv"),
            DcHighServiceConfig(path=repo_examples / "dc_high_prices.csv"),
        ],
        efa=EfaConfig(block_hours=4, block_start_hour=23),
        timestep_minutes=60,
        output_dir=tmp_path,
    )
    result = run(scenario)

    assert result.bid_curve is not None
    assert (result.run_dir / "bid_curve.parquet").exists()
    assert {"dc_low", "dc_high"}.issubset(set(result.bid_curve["service"].unique()))

    summary = result.summary
    total = summary["total_revenue_gbp"]
    parts = (
        summary["revenue_arbitrage_gbp"]
        + summary["revenue_dc_low_gbp"]
        + summary["revenue_dc_high_gbp"]
    )
    assert parts == pytest.approx(total, abs=1e-6)
    assert summary["revenue_dc_low_gbp"] > 0
    assert summary["revenue_dc_high_gbp"] > 0
