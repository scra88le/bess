"""Time-series step loop, constraint enforcement & logging.

The DispatchEngine orchestrates time and applies external-system overrides
around the Battery's physical model. It does not perform any physics itself;
it clamps the injected dispatch setpoint through a sequence of constraints and
hands the result to ``Battery.step``.

Constraint order (per the spec):
    pre-step   : planned outage masking, then hard grid export/import clips
    intra-step : power ramping, then the battery's own SoC/thermal limits

Any divergence between the injected dispatch signal and what was actually
enforced is logged as a standard alarm block to stderr.
"""

from __future__ import annotations

import sys
from typing import Dict, List, Optional

from .battery import Battery
from .config_loader import Config
from .telemetry import Telemetry

DT_SECONDS: float = 1.0
EPS: float = 1e-9


class DispatchEngine:
    """Drives the 1-second discrete step loop over a dispatch signal."""

    def __init__(self, config: Config, battery: Battery,
                 telemetry: Optional[Telemetry] = None) -> None:
        self.config = config
        self.battery = battery
        self.telemetry = telemetry or Telemetry()

        gc = config.grid_constraints
        self._max_export_mw = float(gc["max_export_mw"])
        self._max_import_mw = float(gc["max_import_mw"])
        self._ramp_mw = float(config.ramping_limit_mw_per_sec)
        # Previous *actual* delivered power; ramping is measured against it.
        # Persists across days/steps because physical ramp state is real.
        self._prev_power_mw = 0.0
        # Monotonic global step index (telemetry timestamp) and a within-day
        # second counter used only for planned-outage lookups.
        self._t = 0
        self._day_t = 0

    # ------------------------------------------------------------------ #
    # Main loop
    # ------------------------------------------------------------------ #
    def run(self, dispatch_mw: List[float], dt: float = DT_SECONDS) -> Telemetry:
        """Execute the full dispatch series, one ``dt`` per sample."""
        for injected in dispatch_mw:
            self.step(float(injected), dt)
        return self.telemetry

    def step(self, injected_mw: float, dt: float = DT_SECONDS) -> Dict[str, float]:
        """Advance one timestep externally (for the long-running runner).

        Returns the telemetry row. ``run()`` is just a loop over this.
        """
        row = self._step(self._t, float(injected_mw), dt)
        self._t += 1
        self._day_t += 1
        return row

    def begin_day(self) -> None:
        """Reset the within-day clock so outage windows recur each day."""
        self._day_t = 0

    def _step(self, t: int, injected_mw: float, dt: float) -> Dict[str, float]:
        """Clamp one setpoint through every constraint and advance the battery."""
        setpoint = injected_mw

        # --- Pre-step: planned outage, then grid constraints ----------- #
        setpoint = self._pre_step_clamp(t, setpoint)

        # --- Intra-step: ramping against the previous actual power ------ #
        ramped = self._apply_ramp(setpoint, dt)
        if abs(ramped - setpoint) > EPS:
            self._log_violation(t, setpoint, ramped, "Ramp Limit Exceeded")
        setpoint = ramped

        # --- Intra-step: battery physics (SoC non-linearity, thermal) -- #
        result = self.battery.step(setpoint, dt)
        actual = result["actual_mw"]
        if result["limit_reason"] and abs(actual - setpoint) > EPS:
            self._log_violation(t, setpoint, actual, result["limit_reason"])

        self._prev_power_mw = actual

        row: Dict[str, float] = {
            "timestamp_s": float(t),
            "injected_mw": injected_mw,
            "grid_limit_export_mw": self._max_export_mw,
            "grid_limit_import_mw": -self._max_import_mw,
            **result,
        }
        self.telemetry.record(row)
        return row

    # ------------------------------------------------------------------ #
    # Constraint helpers
    # ------------------------------------------------------------------ #
    def _pre_step_clamp(self, t: int, target_mw: float) -> float:
        """Apply planned-outage masking and hard grid export/import clips."""
        setpoint = target_mw

        if self._is_outage():
            if abs(setpoint) > EPS:
                self._log_violation(t, setpoint, 0.0, "Planned Outage")
            return 0.0

        clipped = min(self._max_export_mw, max(-self._max_import_mw, setpoint))
        if abs(clipped - setpoint) > EPS:
            self._log_violation(t, setpoint, clipped, "Grid Constrained")
        return clipped

    def _apply_ramp(self, target_mw: float, dt: float) -> float:
        """Restrict the step change in power to the configured MW/s limit."""
        max_delta = self._ramp_mw * dt
        upper = self._prev_power_mw + max_delta
        lower = self._prev_power_mw - max_delta
        return min(upper, max(lower, target_mw))

    def _is_outage(self) -> bool:
        """True if the current within-day second is in a maintenance window.

        Windows are interpreted as seconds-since-midnight, so they recur each
        simulated day (``_day_t`` is reset by ``begin_day``).
        """
        for window in self.config.planned_outages:
            start, end = window
            if start <= self._day_t <= end:
                return True
        return False

    @staticmethod
    def _log_violation(t: int, desired: float, enforced: float, reason: str) -> None:
        """Emit a standard alarm block to stderr when physics diverge from signal."""
        print(
            f"[VIOLATION][{t}] Desired: {desired:.1f} MW | "
            f"Enforced Limit: {enforced:.1f} MW | Reason: [{reason}]",
            file=sys.stderr,
        )
