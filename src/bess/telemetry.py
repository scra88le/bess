from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .battery import StepResult
from .config import SiteSpec

TELEMETRY_COLUMNS = [
    "timestamp",
    "price",
    "p_setpoint_mw",
    "p_actual_mw",
    "soc_mwh",
    "soc_frac",
    "revenue_period",
    "clipped",
]


@dataclass
class TelemetryRow:
    timestamp: pd.Timestamp
    price: float
    p_setpoint_mw: float
    p_actual_mw: float
    soc_mwh: float
    soc_frac: float
    revenue_period: float
    clipped: bool


class TelemetryWriter:
    def __init__(self) -> None:
        self._rows: list[TelemetryRow] = []

    def append(
        self,
        timestamp: pd.Timestamp,
        price: float,
        step: StepResult,
        timestep_hours: float,
    ) -> None:
        self._rows.append(
            TelemetryRow(
                timestamp=timestamp,
                price=price,
                p_setpoint_mw=step.power_setpoint_mw,
                p_actual_mw=step.power_actual_mw,
                soc_mwh=step.soc_mwh,
                soc_frac=step.soc_frac,
                revenue_period=price * step.power_actual_mw * timestep_hours,
                clipped=step.clipped,
            )
        )

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame([r.__dict__ for r in self._rows], columns=TELEMETRY_COLUMNS)

    def write_parquet(self, path: Path) -> pd.DataFrame:
        df = self.to_dataframe()
        df.to_parquet(path, index=False)
        return df


def summarise_kpis(
    telemetry: pd.DataFrame,
    site: SiteSpec,
    timestep_hours: float,
) -> dict:
    p_actual = telemetry["p_actual_mw"].to_numpy()
    energy_discharged = (p_actual.clip(min=0) * timestep_hours).sum()
    energy_charged = (-p_actual.clip(max=0) * timestep_hours).sum()
    throughput = energy_discharged + energy_charged
    usable_mwh = (site.soc_max_frac - site.soc_min_frac) * site.energy_mwh
    cycles = throughput / (2 * usable_mwh) if usable_mwh > 0 else 0.0
    return {
        "total_revenue_gbp": float(telemetry["revenue_period"].sum()),
        "energy_discharged_mwh": float(energy_discharged),
        "energy_charged_mwh": float(energy_charged),
        "throughput_mwh": float(throughput),
        "equivalent_full_cycles": float(cycles),
        "soc_frac_max": float(telemetry["soc_frac"].max()),
        "soc_frac_min": float(telemetry["soc_frac"].min()),
        "hours_clipped": float(telemetry["clipped"].sum() * timestep_hours),
        "n_steps": int(len(telemetry)),
    }


def write_summary(path: Path, summary: dict) -> None:
    with path.open("w") as f:
        json.dump(summary, f, indent=2, default=str)
