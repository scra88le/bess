"""Tests for the io_layout path contract and fsspec read/write seam."""

from __future__ import annotations

import datetime as dt

import pytest

from src import io_layout


def test_path_builders_follow_contract() -> None:
    root = "/tmp/data"
    d = dt.date(2026, 6, 13)
    ext = io_layout.TABLE_EXT
    assert io_layout.prices_path(root, d) == f"/tmp/data/prices/date=2026-06-13/forecast.{ext}"
    assert io_layout.schedule_path(root, "2026-06-13") == \
        f"/tmp/data/schedules/date=2026-06-13/dispatch.{ext}"
    assert io_layout.telemetry_path(root, d, 7) == \
        f"/tmp/data/telemetry/date=2026-06-13/part-0007.{ext}"
    assert io_layout.state_path(root) == "/tmp/data/state/battery_state.json"


def test_trailing_slash_normalised() -> None:
    assert io_layout.prices_path("/tmp/data/", "2026-06-13").startswith("/tmp/data/prices/")


def test_table_roundtrip_local(tmp_path) -> None:
    path = io_layout.telemetry_path(str(tmp_path), "2026-06-13", 0)
    rows = [{"a": 1, "b": 2.5, "c": "x"}, {"a": 3, "b": 4.0, "c": "y"}]
    io_layout.write_table(path, rows)
    assert io_layout.exists(path)
    back = io_layout.read_table(path)
    assert back == rows


def test_table_roundtrip_memory() -> None:
    """Proves S3-style parity without S3 (in-memory fsspec backend)."""
    path = io_layout.schedule_path("memory://run1", "2026-06-13")
    rows = [{"period": 0, "power_mw": -5.0}, {"period": 1, "power_mw": 10.0}]
    io_layout.write_table(path, rows)
    assert io_layout.read_table(path) == rows


def test_write_table_overwrites(tmp_path) -> None:
    path = io_layout.schedule_path(str(tmp_path), "2026-06-13")
    io_layout.write_table(path, [{"period": 0, "power_mw": 1.0}])
    io_layout.write_table(path, [{"period": 0, "power_mw": 2.0}])   # re-optimise
    assert io_layout.read_table(path) == [{"period": 0, "power_mw": 2.0}]


def test_read_missing_raises_missing_artifact(tmp_path) -> None:
    path = io_layout.schedule_path(str(tmp_path), "2099-01-01")
    with pytest.raises(io_layout.MissingArtifactError):
        io_layout.read_table(path)


def test_json_roundtrip_and_absent(tmp_path) -> None:
    path = io_layout.state_path(str(tmp_path))
    assert io_layout.read_json(path) is None          # absent -> None
    obj = {"battery_state": {"soc": 0.4}, "engine": {"prev_power_mw": 1.2}}
    io_layout.write_json(path, obj)
    assert io_layout.read_json(path) == obj
