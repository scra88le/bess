"""Time-series step loop, constraint enforcement & logging.

The DispatchEngine orchestrates time and applies external-system overrides
(planned outages, grid constraints) around the Battery's physical model.
"""

from __future__ import annotations

import sys
from typing import List, Optional

from .battery import Battery
from .config_loader import Config
from .telemetry import Telemetry


class DispatchEngine:
    """Drives the 1-second discrete step loop over a dispatch signal."""

    def __init__(self, config: Config, battery: Battery,
                 telemetry: Optional[Telemetry] = None) -> None:
        self.config = config
        self.battery = battery
        self.telemetry = telemetry or Telemetry()

    def run(self, dispatch_mw: List[float]) -> Telemetry:
        """Execute the full dispatch series, one second per sample."""
        raise NotImplementedError

    def _pre_step_clamp(self, t: int, target_mw: float) -> float:
        """Apply planned-outage masking and hard grid export/import clips."""
        raise NotImplementedError

    def _is_outage(self, t: int) -> bool:
        """True if timestep t falls within a planned maintenance window."""
        raise NotImplementedError

    @staticmethod
    def _log_violation(t: int, desired: float, enforced: float, reason: str) -> None:
        """Emit a standard alarm block to stderr when physics diverge from signal."""
        print(
            f"[VIOLATION][{t}] Desired: {desired:.1f} MW | "
            f"Enforced Limit: {enforced:.1f} MW | Reason: [{reason}]",
            file=sys.stderr,
        )
