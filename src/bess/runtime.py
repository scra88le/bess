from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from .battery import EnergyBucketBattery
from .config import DcHighServiceConfig, DcLowServiceConfig, ScenarioConfig
from .optimiser import (
    ServicePriceSeries,
    solve_perfect_foresight,
    solve_sequential,
)
from .prices import align_to_index, load_prices, load_service_price_csv
from .telemetry import TelemetryWriter, summarise_kpis, write_summary


@dataclass
class RunResult:
    run_dir: Path
    telemetry: pd.DataFrame
    schedule: pd.DataFrame
    summary: dict
    bid_curve: pd.DataFrame | None = None


def run(scenario: ScenarioConfig) -> RunResult:
    started = time.time()
    run_id = datetime.now().strftime("%Y%m%dT%H%M%S")
    run_dir = scenario.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    timestep_hours = scenario.timestep_minutes / 60.0
    prices = load_prices(scenario.prices, scenario.timestep_minutes)

    bid_curve_df: pd.DataFrame | None = None

    if scenario.services:
        services = _load_services(scenario, prices.index)
        sequential = solve_sequential(
            prices=prices,
            services=services,
            site=scenario.site,
            timestep_hours=timestep_hours,
            efa=scenario.efa,
        )
        schedule = sequential.schedule
        bid_curve_df = sequential.bid_curve
    else:
        schedule = solve_perfect_foresight(prices, scenario.site, timestep_hours)

    has_dc_columns = "c_dc_low" in schedule.columns
    battery = EnergyBucketBattery(scenario.site, timestep_hours)
    writer = TelemetryWriter()
    for ts, row in schedule.iterrows():
        step = battery.step(float(row["p_net"]))
        writer.append(
            timestamp=ts,
            price=float(row["price"]),
            step=step,
            timestep_hours=timestep_hours,
            c_dc_low=float(row["c_dc_low"]) if has_dc_columns else 0.0,
            c_dc_high=float(row["c_dc_high"]) if has_dc_columns else 0.0,
            dc_low_price=float(row["dc_low_price"]) if has_dc_columns else 0.0,
            dc_high_price=float(row["dc_high_price"]) if has_dc_columns else 0.0,
        )

    telemetry = writer.write_parquet(run_dir / "telemetry.parquet")
    schedule.to_parquet(run_dir / "schedule.parquet")
    if bid_curve_df is not None:
        bid_curve_df.to_parquet(run_dir / "bid_curve.parquet", index=False)

    summary = summarise_kpis(telemetry, scenario.site, timestep_hours)
    summary["wall_time_seconds"] = time.time() - started
    write_summary(run_dir / "summary.json", summary)

    manifest = {
        "run_id": run_id,
        "scenario": scenario.model_dump(mode="json"),
    }
    with (run_dir / "manifest.json").open("w") as f:
        json.dump(manifest, f, indent=2, default=str)

    return RunResult(
        run_dir=run_dir,
        telemetry=telemetry,
        schedule=schedule,
        summary=summary,
        bid_curve=bid_curve_df,
    )


def _load_services(
    scenario: ScenarioConfig, energy_index: pd.DatetimeIndex
) -> dict[str, ServicePriceSeries]:
    services: dict[str, ServicePriceSeries] = {}
    for svc in scenario.services:
        kind = svc.kind
        if kind in services:
            raise ValueError(f"Duplicate service '{kind}' in scenario.services")
        if isinstance(svc, (DcLowServiceConfig, DcHighServiceConfig)):
            series = load_service_price_csv(
                svc.path, svc.timestamp_column, svc.price_column, name=kind
            )
            series = align_to_index(series, energy_index, label=kind)
            services[kind] = ServicePriceSeries(
                prices=series,
                response_hours=svc.response_minutes / 60.0,
            )
        else:  # pragma: no cover - covered by pydantic discriminator
            raise TypeError(f"Unsupported service config: {type(svc).__name__}")
    return services
