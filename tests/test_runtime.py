from __future__ import annotations

from pathlib import Path

import numpy as np

from bess.config import ScenarioConfig, SiteSpec, SyntheticPriceConfig
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
