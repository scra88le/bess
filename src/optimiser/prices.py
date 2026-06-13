"""Read a day's price forecast for the optimiser."""

from __future__ import annotations

from typing import List, Tuple

from .. import io_layout
from ..io_layout import DateLike


def read(root: str, date: DateLike) -> Tuple[List[float], int]:
    """Return (prices £/MWh per period, resolution_minutes) for a date.

    Raises ``MissingArtifactError`` if the day's forecast is absent — the
    optimiser must not silently fall back.
    """
    records = io_layout.read_table(io_layout.prices_path(root, date))
    records.sort(key=lambda r: r["period"])
    prices = [float(r["price_per_mwh"]) for r in records]
    resolution_minutes = int(records[0]["resolution_minutes"])
    return prices, resolution_minutes
