"""Tests for the synthetic price model and batch generator."""

from __future__ import annotations

import datetime as dt

import pytest

from src import io_layout
from src.prices import SyntheticPriceModel
from src.prices.generator import generate


def test_deterministic_for_same_date_and_seed() -> None:
    a = SyntheticPriceModel(seed=7).prices("2026-06-13", 30)
    b = SyntheticPriceModel(seed=7).prices("2026-06-13", 30)
    assert a == b


def test_different_dates_differ() -> None:
    a = SyntheticPriceModel(seed=7).prices("2026-06-13", 30)
    b = SyntheticPriceModel(seed=7).prices("2026-06-14", 30)
    assert a != b


def test_different_seeds_differ() -> None:
    a = SyntheticPriceModel(seed=1).prices("2026-06-13", 30)
    b = SyntheticPriceModel(seed=2).prices("2026-06-13", 30)
    assert a != b


@pytest.mark.parametrize("res, expected", [(30, 48), (60, 24), (15, 96), (5, 288)])
def test_period_count_matches_resolution(res, expected) -> None:
    assert len(SyntheticPriceModel().prices("2026-06-13", res)) == expected


@pytest.mark.parametrize("bad", [0, 7, 13, 50, -30])
def test_invalid_resolution_raises(bad) -> None:
    with pytest.raises(ValueError):
        SyntheticPriceModel().prices("2026-06-13", bad)


def test_profile_has_arbitrage_shape() -> None:
    """Evening peak should exceed the overnight trough (so arbitrage exists)."""
    prices = SyntheticPriceModel(noise_std=0.0).prices("2026-06-13", 60)
    overnight = prices[3]          # ~03:00
    evening = prices[18]           # ~18:00
    assert evening > overnight


def test_generate_writes_partitioned_files(tmp_path) -> None:
    paths = generate(str(tmp_path), "2026-06-13", days=3, resolution_minutes=30, seed=7)
    assert len(paths) == 3
    assert "date=2026-06-13" in paths[0]
    assert "date=2026-06-15" in paths[2]

    records = io_layout.read_table(paths[0])
    assert len(records) == 48
    assert set(records[0]) == {"period", "ts_utc", "price_per_mwh", "resolution_minutes"}
    assert records[0]["period"] == 0
    assert records[-1]["period"] == 47
    assert records[0]["resolution_minutes"] == 30
    # Timestamps advance by the resolution.
    assert records[0]["ts_utc"] == "2026-06-13T00:00:00"
    assert records[1]["ts_utc"] == "2026-06-13T00:30:00"


def test_generate_rejects_nonpositive_days(tmp_path) -> None:
    with pytest.raises(ValueError):
        generate(str(tmp_path), "2026-06-13", days=0)
