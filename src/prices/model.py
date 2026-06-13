"""Day-ahead price forecast models.

``PriceModel`` is the plug point: anything that can produce a per-period price
series for a date satisfies it, so a real market feed can drop in later behind
the same interface. ``SyntheticPriceModel`` is the default — a deterministic
diurnal arbitrage-shaped profile (overnight trough, morning + evening peaks)
with seeded per-date noise.
"""

from __future__ import annotations

import datetime as dt
from typing import List, Protocol, Union

import numpy as np

DateLike = Union[str, dt.date]
MINUTES_PER_DAY = 24 * 60


def _as_date(date: DateLike) -> dt.date:
    return date if isinstance(date, dt.date) else dt.date.fromisoformat(date)


def _periods_per_day(resolution_minutes: int) -> int:
    if resolution_minutes <= 0 or MINUTES_PER_DAY % resolution_minutes != 0:
        raise ValueError(
            f"resolution_minutes must divide {MINUTES_PER_DAY}, got {resolution_minutes}"
        )
    return MINUTES_PER_DAY // resolution_minutes


class PriceModel(Protocol):
    """Produces a £/MWh price for each period of a day."""

    def prices(self, date: DateLike, resolution_minutes: int) -> List[float]:
        ...


def _gaussian(x: np.ndarray, mu: float, sigma: float) -> np.ndarray:
    return np.exp(-0.5 * ((x - mu) / sigma) ** 2)


class SyntheticPriceModel:
    """Deterministic synthetic DA price forecast with a daily arbitrage shape."""

    def __init__(self, seed: int = 0, base: float = 50.0,
                 morning_peak: float = 40.0, evening_peak: float = 60.0,
                 overnight_dip: float = 15.0, noise_std: float = 4.0) -> None:
        self.seed = seed
        self.base = base
        self.morning_peak = morning_peak
        self.evening_peak = evening_peak
        self.overnight_dip = overnight_dip
        self.noise_std = noise_std

    def prices(self, date: DateLike, resolution_minutes: int) -> List[float]:
        periods = _periods_per_day(resolution_minutes)
        # Hour-of-day at the centre of each period.
        hour = (np.arange(periods) * resolution_minutes + resolution_minutes / 2) / 60.0

        profile = (
            self.base
            + self.morning_peak * _gaussian(hour, 8.0, 2.5)
            + self.evening_peak * _gaussian(hour, 18.5, 2.0)
            - self.overnight_dip * _gaussian(hour, 3.0, 3.0)
        )

        rng = np.random.default_rng(self._seed_for(date))
        noise = rng.normal(0.0, self.noise_std, size=periods)
        return [round(float(v), 4) for v in (profile + noise)]

    def _seed_for(self, date: DateLike) -> int:
        """Per-date seed: a given (seed, date) always yields the same series."""
        return (self.seed * 1_000_003 + _as_date(date).toordinal()) % (2 ** 32)
