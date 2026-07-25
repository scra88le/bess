"""The optimiser's output: a per-period power schedule + its file I/O."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .. import io_layout
from ..io_layout import DateLike


@dataclass
class Schedule:
    """Optimal grid-side power per market period (+ = discharge/export)."""

    date: Optional[str]
    resolution_minutes: int
    power_mw: List[float]
    terminal_soc: Optional[float] = None
    objective_value: Optional[float] = None

    @property
    def period_seconds(self) -> int:
        return self.resolution_minutes * 60

    def power_at_second(self, second_of_day: int) -> float:
        """Power setpoint for a given second within the day (held flat per period)."""
        period = second_of_day // self.period_seconds
        period = min(max(period, 0), len(self.power_mw) - 1)
        return self.power_mw[period]

    def write(self, root: str) -> str:
        """Persist to schedules/date=<date>/dispatch.<ext>; returns the path."""
        if self.date is None:
            raise ValueError("Schedule.date must be set before writing")
        records = [
            {
                "period": i,
                "power_mw": float(p),
                "resolution_minutes": self.resolution_minutes,
            }
            for i, p in enumerate(self.power_mw)
        ]
        path = io_layout.schedule_path(root, self.date)
        io_layout.write_table(path, records)
        return path

    @classmethod
    def read(cls, root: str, date: DateLike) -> "Schedule":
        """Load a schedule for a date (raises MissingArtifactError if absent)."""
        records = io_layout.read_table(io_layout.schedule_path(root, date))
        records.sort(key=lambda r: r["period"])
        return cls(
            date=date if isinstance(date, str) else date.isoformat(),
            resolution_minutes=int(records[0]["resolution_minutes"]),
            power_mw=[float(r["power_mw"]) for r in records],
        )
