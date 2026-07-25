"""Tests for the wall-clock pacing SimClock."""

from __future__ import annotations

import datetime as dt
import time

from src.runtime.clock import SimClock


def test_accelerated_runs_fast() -> None:
    """A huge time_scale advances sim time without real waiting."""
    start = dt.datetime(2026, 6, 13)
    clock = SimClock(start, time_scale=1_000_000.0)
    wall0 = time.monotonic()
    for _ in range(600):  # 600 sim-seconds
        clock.tick()
    wall_elapsed = time.monotonic() - wall0
    sim_elapsed = (clock.sim_now - start).total_seconds()
    assert sim_elapsed == 600.0
    assert wall_elapsed < 0.5  # negligible real time


def test_second_minute_day_fields() -> None:
    clock = SimClock(dt.datetime(2026, 6, 13, 0, 0, 0), time_scale=1e9)
    assert clock.second_of_day == 0
    assert clock.minute_index == 0
    assert not clock.is_minute_end()
    for _ in range(59):
        clock.tick()
    assert clock.second_of_day == 59
    assert clock.is_minute_end()  # last second of minute 0
    assert clock.minute_index == 0
    clock.tick()
    assert clock.minute_index == 1
    assert clock.second_of_day == 60


def test_day_rolls_over() -> None:
    clock = SimClock(dt.datetime(2026, 6, 13, 23, 59, 59), time_scale=1e9)
    assert clock.date == dt.date(2026, 6, 13)
    clock.tick()
    assert clock.date == dt.date(2026, 6, 14)
    assert clock.second_of_day == 0


def test_minute_start() -> None:
    clock = SimClock(dt.datetime(2026, 6, 13, 8, 30, 59), time_scale=1e9)
    assert clock.minute_start() == dt.datetime(2026, 6, 13, 8, 30, 0)
