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
    "c_dc_low_committed_mw",
    "c_dc_high_committed_mw",
    "dc_low_price",
    "dc_high_price",
    "revenue_dc_low_period",
    "revenue_dc_high_period",
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
    c_dc_low_committed_mw: float
    c_dc_high_committed_mw: float
    dc_low_price: float
    dc_high_price: float
    revenue_dc_low_period: float
    revenue_dc_high_period: float
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
        c_dc_low: float = 0.0,
        c_dc_high: float = 0.0,
        dc_low_price: float = 0.0,
        dc_high_price: float = 0.0,
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
                c_dc_low_committed_mw=c_dc_low,
                c_dc_high_committed_mw=c_dc_high,
                dc_low_price=dc_low_price,
                dc_high_price=dc_high_price,
                revenue_dc_low_period=c_dc_low * dc_low_price * timestep_hours,
                revenue_dc_high_period=c_dc_high * dc_high_price * timestep_hours,
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
    revenue_arbitrage = float(telemetry["revenue_period"].sum())
    revenue_dc_low = (
        float(telemetry["revenue_dc_low_period"].sum())
        if "revenue_dc_low_period" in telemetry.columns
        else 0.0
    )
    revenue_dc_high = (
        float(telemetry["revenue_dc_high_period"].sum())
        if "revenue_dc_high_period" in telemetry.columns
        else 0.0
    )
    return {
        "total_revenue_gbp": revenue_arbitrage + revenue_dc_low + revenue_dc_high,
        "revenue_arbitrage_gbp": revenue_arbitrage,
        "revenue_dc_low_gbp": revenue_dc_low,
        "revenue_dc_high_gbp": revenue_dc_high,
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
