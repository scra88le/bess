from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from .battery import EnergyBucketBattery
from .config import ScenarioConfig
from .optimiser import solve_perfect_foresight
from .prices import load_prices
from .telemetry import TelemetryWriter, summarise_kpis, write_summary


@dataclass
class RunResult:
    run_dir: Path
    telemetry: pd.DataFrame
    schedule: pd.DataFrame
    summary: dict


def run(scenario: ScenarioConfig) -> RunResult:
    started = time.time()
    run_id = datetime.now().strftime("%Y%m%dT%H%M%S")
    run_dir = scenario.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    timestep_hours = scenario.timestep_minutes / 60.0
    prices = load_prices(scenario.prices, scenario.timestep_minutes)

    schedule = solve_perfect_foresight(prices, scenario.site, timestep_hours)

    battery = EnergyBucketBattery(scenario.site, timestep_hours)
    writer = TelemetryWriter()
    for ts, row in schedule.iterrows():
        step = battery.step(float(row["p_net"]))
        writer.append(
            timestamp=ts,
            price=float(row["price"]),
            step=step,
            timestep_hours=timestep_hours,
        )

    telemetry = writer.write_parquet(run_dir / "telemetry.parquet")
    schedule.to_parquet(run_dir / "schedule.parquet")

    summary = summarise_kpis(telemetry, scenario.site, timestep_hours)
    summary["wall_time_seconds"] = time.time() - started
    write_summary(run_dir / "summary.json", summary)

    manifest = {
        "run_id": run_id,
        "scenario": scenario.model_dump(mode="json"),
    }
    with (run_dir / "manifest.json").open("w") as f:
        json.dump(manifest, f, indent=2, default=str)

    return RunResult(run_dir=run_dir, telemetry=telemetry, schedule=schedule, summary=summary)
