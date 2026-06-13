"""Fold per-second engine telemetry rows into one record per minute.

Reduces 86,400 rows/day to 1,440 — far friendlier for a dashboard — while
keeping a fixed, stable column schema (important for partitioned ingestion).
"""

from __future__ import annotations

from typing import Any, Dict, List

# Map each engine ``limit_reason`` to a stable output column; anything else
# falls into ``violations_other``. Fixed set ⇒ identical schema every minute.
_REASON_COLUMNS: Dict[str, str] = {
    "Ramp Limit Exceeded": "violations_ramp_limit",
    "Grid Constrained": "violations_grid_constrained",
    "Planned Outage": "violations_planned_outage",
    "Thermal Trip": "violations_thermal_trip",
    "SoC Non-Linear Limit": "violations_soc_nonlinear",
    "SoC Floor": "violations_soc_floor",
    "SoC Ceiling": "violations_soc_ceiling",
    "SoC Limit": "violations_soc_limit",
}
_VIOLATION_COLUMNS: List[str] = list(_REASON_COLUMNS.values()) + ["violations_other"]


class MinuteAggregator:
    """Accumulates per-second rows and flushes a single minute record."""

    def __init__(self) -> None:
        self._rows: List[Dict[str, Any]] = []

    def add(self, row: Dict[str, Any]) -> None:
        self._rows.append(row)

    def is_empty(self) -> bool:
        return not self._rows

    def flush(self, date: str, minute_index: int, ts_utc: str) -> Dict[str, Any]:
        """Produce the minute record and reset. dt is 1 s, so energy = Σ MW / 3600."""
        rows = self._rows
        n = len(rows)
        power = [r["actual_mw"] for r in rows]
        last = rows[-1]

        record: Dict[str, Any] = {
            "date": date,
            "minute_index": minute_index,
            "ts_utc": ts_utc,
            "soc_end": last["soc"],
            "cell_temp_c_end": last["cell_temp_c"],
            "mwh_discharged": sum(p for p in power if p > 0) / 3600.0,
            "mwh_charged": sum(-p for p in power if p < 0) / 3600.0,
            "mean_power_mw": sum(power) / n,
            "peak_discharge_mw": max(0.0, max(power)),
            "peak_charge_mw": max(0.0, -min(power)),
            "mean_target_mw": sum(r["target_mw"] for r in rows) / n,
            "mean_aux_load_mw": sum(r["aux_load_mw"] for r in rows) / n,
            "mean_resistive_loss_mw": sum(r["resistive_loss_mw"] for r in rows) / n,
            "equivalent_full_cycles_end": last["equivalent_full_cycles"],
            "capacity_loss_fraction_end": last["capacity_loss_fraction"],
            "cumulative_throughput_mwh_end": last["cumulative_throughput_mwh"],
            "warranty_breached": float(max(r["warranty_breached"] for r in rows)),
        }
        for col in _VIOLATION_COLUMNS:
            record[col] = 0
        for r in rows:
            reason = r.get("limit_reason") or ""
            if reason:
                record[_REASON_COLUMNS.get(reason, "violations_other")] += 1

        self._rows = []
        return record
