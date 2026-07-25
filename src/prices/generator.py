"""Batch generation of day-ahead price forecast files.

Produces one ``forecast`` table per day for ``days`` days starting at ``start``,
written to the date-partitioned layout via :mod:`src.io_layout`. This is the
"generate N days in advance" job; the optimiser later consumes one day at a time.
"""

from __future__ import annotations

import datetime as dt
from typing import List, Optional

from .. import io_layout
from .model import DateLike, PriceModel, SyntheticPriceModel, _as_date


def generate(
    root: str,
    start: DateLike,
    days: int,
    *,
    resolution_minutes: int = 30,
    seed: int = 0,
    model: Optional[PriceModel] = None,
) -> List[str]:
    """Generate ``days`` daily forecasts and write them under ``root``.

    Returns the list of paths written. Raises ``ValueError`` on bad inputs.
    """
    if days <= 0:
        raise ValueError(f"days must be > 0, got {days}")

    model = model or SyntheticPriceModel(seed=seed)
    start_date = _as_date(start)
    midnight = dt.time()
    written: List[str] = []

    for offset in range(days):
        day = start_date + dt.timedelta(days=offset)
        prices = model.prices(day, resolution_minutes)
        day_start = dt.datetime.combine(day, midnight)
        records = [
            {
                "period": period,
                "ts_utc": (
                    day_start + dt.timedelta(minutes=period * resolution_minutes)
                ).isoformat(),
                "price_per_mwh": float(price),
                "resolution_minutes": int(resolution_minutes),
            }
            for period, price in enumerate(prices)
        ]
        path = io_layout.prices_path(root, day)
        io_layout.write_table(path, records)
        written.append(path)

    return written
