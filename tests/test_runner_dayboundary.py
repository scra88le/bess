"""Integration tests for the runner loop: telemetry, day roll, no-fallback."""

from __future__ import annotations

import datetime as dt

import pytest

from src import io_layout
from src.config_loader import Config
from src.optimiser.schedule import Schedule
from src.runtime import RunnerConfig, run

BASE = Config(
    nominal_capacity_mwh=50.0,
    initial_soc=0.50,
    efficiency=0.92,
    ramping_limit_mw_per_sec=2.0,
    thermal={
        "initial_temp_c": 25.0,
        "ambient_temp_c": 20.0,
        "thermal_mass": 3.0e8,
        "hvac_cooling_rate_c_per_sec": 0.05,
        "optimal_temp_c": 20.0,
        "max_cell_temp_c": 60.0,
    },
    soc_non_linearity={
        "lower_threshold": 0.10,
        "upper_threshold": 0.90,
        "exponential_factor": 2.5,
    },
    auxiliary_load_kw={"base": 50.0, "hvac_per_degree": 10.0},
    grid_constraints={"max_export_mw": 45.0, "max_import_mw": 45.0},
    warranty={"max_equivalent_full_cycles": 3000},
    degradation={"cycle_loss_per_efc": 0.0000667, "calendar_loss_per_year": 0.02},
)

FAST = 1_000_000.0  # time_scale: no real waiting


def _write_schedule(root: str, date: str, power: float = 10.0) -> None:
    Schedule(
        date=date, resolution_minutes=30, power_mw=[power] * 48, terminal_soc=0.5
    ).write(root)


def test_runner_writes_minute_telemetry(tmp_path) -> None:
    """Five sim-minutes before midnight produce five minute records."""
    root = str(tmp_path)
    _write_schedule(root, "2026-06-13", power=10.0)

    summary = run(
        BASE,
        RunnerConfig(root=root, time_scale=FAST, days=1),
        start=dt.datetime(2026, 6, 13, 23, 55, 0),
    )

    assert summary["days_run"] == 1
    assert summary["minutes_written"] == 5
    # Minutes 1435..1439 written; check the last one's content.
    last = io_layout.telemetry_path(root, "2026-06-13", 1439)
    assert io_layout.exists(last)
    rec = io_layout.read_table(last)[0]
    assert rec["minute_index"] == 1439
    assert rec["mwh_discharged"] > 0  # discharging at +10 MW
    assert rec["soc_end"] < 0.50  # drained slightly
    assert summary["final_soc"] < 0.50


def test_runner_rolls_to_next_day_and_raises_on_missing(tmp_path) -> None:
    """After day 1 it loads day 2's schedule; absent ⇒ MissingArtifactError."""
    root = str(tmp_path)
    _write_schedule(root, "2026-06-13", power=10.0)  # day 1 only; day 2 missing

    with pytest.raises(io_layout.MissingArtifactError):
        run(
            BASE,
            RunnerConfig(root=root, time_scale=FAST, days=2),
            start=dt.datetime(2026, 6, 13, 23, 59, 0),
        )

    # Day 1's final minute still got written before the roll failed.
    assert io_layout.exists(io_layout.telemetry_path(root, "2026-06-13", 1439))


def test_runner_resumes_from_checkpoint(tmp_path) -> None:
    """A checkpoint is written and re-applied (resumes sim time, not `start`)."""
    root = str(tmp_path)
    _write_schedule(root, "2026-06-13", power=10.0)
    run(
        BASE,
        RunnerConfig(root=root, time_scale=FAST, days=1),
        start=dt.datetime(2026, 6, 13, 23, 59, 0),
    )

    ckpt = io_layout.read_json(io_layout.state_path(root))
    assert ckpt is not None
    # Last checkpoint points at the next day's start (after the final tick).
    assert ckpt["clock"]["sim_now_iso"].startswith("2026-06-14")
    assert ckpt["battery_state"]["soc"] < 0.50
