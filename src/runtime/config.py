"""Runner configuration — kept separate from the physics ``Config``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class RunnerConfig:
    """Parameters for the long-running runner service."""

    root: str                          # fsspec URL for the data layout (./data or s3://…)
    time_scale: float = 1.0            # sim-seconds per wall-second (1 = real time)
    days: Optional[int] = None         # number of sim-days to run; None = indefinitely
    checkpoint: bool = True            # persist state each minute for restart
