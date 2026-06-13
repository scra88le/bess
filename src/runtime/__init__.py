"""Long-running runner: paces the simulator by wall clock, follows the
day-ahead schedule, emits 1-minute telemetry, and re-plans each day."""

from .config import RunnerConfig
from .runner import run

__all__ = ["RunnerConfig", "run"]
