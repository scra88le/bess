"""Checkpoint and restore the simulator's state for restartable runs.

Persists the battery state, the engine's ramp memory, and the sim clock so a
restarted process resumes where it left off (relevant for a long-running service
that may be redeployed/restarted).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from typing import Any, Dict, Optional

from .. import io_layout
from ..battery import Battery, BatteryState
from ..dispatch_engine import DispatchEngine

SCHEMA_VERSION = 1


def save(
    root: str,
    battery: Battery,
    engine: DispatchEngine,
    sim_now: dt.datetime,
    time_scale: float,
) -> None:
    obj: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "battery_state": dataclasses.asdict(battery.state),
        "engine": {"prev_power_mw": engine._prev_power_mw, "global_t": engine._t},
        "clock": {"sim_now_iso": sim_now.isoformat(), "time_scale": time_scale},
    }
    io_layout.write_json(io_layout.state_path(root), obj)


def load(root: str) -> Optional[Dict[str, Any]]:
    """Return the checkpoint dict, or None if none exists (fresh start)."""
    return io_layout.read_json(io_layout.state_path(root))


def apply(
    checkpoint: Dict[str, Any], battery: Battery, engine: DispatchEngine
) -> dt.datetime:
    """Restore state onto fresh objects; return the saved sim time."""
    battery.state = BatteryState(**checkpoint["battery_state"])
    engine._prev_power_mw = checkpoint["engine"]["prev_power_mw"]
    engine._t = checkpoint["engine"].get("global_t", 0)
    return dt.datetime.fromisoformat(checkpoint["clock"]["sim_now_iso"])
