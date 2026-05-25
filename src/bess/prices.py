from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .config import CsvPriceConfig, PriceConfig, SyntheticPriceConfig


def load_prices(config: PriceConfig, timestep_minutes: int) -> pd.Series:
    if isinstance(config, CsvPriceConfig):
        return load_csv(config.path, config.timestamp_column, config.price_column)
    if isinstance(config, SyntheticPriceConfig):
        return synthetic_sine(
            days=config.days,
            timestep_minutes=timestep_minutes,
            peak=config.peak_price,
            trough=config.trough_price,
            start=config.start,
        )
    raise TypeError(f"Unknown price config: {type(config).__name__}")


def load_csv(path: Path, timestamp_column: str, price_column: str) -> pd.Series:
    return _read_price_csv(path, timestamp_column, price_column, name="price")


def _read_price_csv(
    path: Path, timestamp_column: str, price_column: str, name: str
) -> pd.Series:
    df = pd.read_csv(path)
    ts = pd.to_datetime(df[timestamp_column])
    series = pd.Series(df[price_column].astype(float).to_numpy(), index=ts, name=name)
    series.index.name = "timestamp"
    return series.sort_index()


def load_service_price_csv(
    path: Path, timestamp_column: str, price_column: str, name: str
) -> pd.Series:
    """Load a service (e.g. DC) price CSV with the same shape as wholesale prices."""
    return _read_price_csv(path, timestamp_column, price_column, name=name)


def align_to_index(series: pd.Series, energy_index: pd.DatetimeIndex, label: str) -> pd.Series:
    """Confirm `series` shares `energy_index` exactly; raise if not.

    The optimiser needs one service price per timestep aligned 1-1 with the energy series.
    """
    if not series.index.equals(energy_index):
        missing = energy_index.difference(series.index)
        extra = series.index.difference(energy_index)
        raise ValueError(
            f"{label} price index does not match energy price index "
            f"(missing={len(missing)}, extra={len(extra)}, "
            f"first_missing={missing[0] if len(missing) else None}, "
            f"first_extra={extra[0] if len(extra) else None})"
        )
    return series


def synthetic_sine(
    days: int,
    timestep_minutes: int,
    peak: float,
    trough: float,
    start: str = "2025-01-01",
) -> pd.Series:
    """Daily sinusoid with a small evening bump so peak ≠ trough exactly antiphase.

    Lowest prices around 04:00, highest around 18:00.
    """
    n = days * 24 * 60 // timestep_minutes
    index = pd.date_range(start=start, periods=n, freq=f"{timestep_minutes}min")
    hours = index.hour + index.minute / 60.0
    midline = (peak + trough) / 2
    amplitude = (peak - trough) / 2
    base = midline - amplitude * np.cos(2 * np.pi * (hours - 18) / 24)
    evening_bump = 0.15 * amplitude * np.exp(-((hours - 18) ** 2) / (2 * 1.5**2))
    values = base + evening_bump
    series = pd.Series(values, index=index, name="price")
    series.index.name = "timestamp"
    return series
