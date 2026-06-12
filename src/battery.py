"""Battery physical state machine & core math.

The Battery class manages immediate physical transformations for a single
1-second discrete step (dt = 1). It is intentionally free of time
orchestration or external-system overrides; that responsibility belongs to
the DispatchEngine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from .config_loader import Config


@dataclass
class BatteryState:
    """Snapshot of dynamic state variables at a single timestep."""

    soc: float                  # state of charge, fraction [0, 1]
    cell_temp_c: float          # cell temperature
    cumulative_throughput_mwh: float = 0.0
    equivalent_full_cycles: float = 0.0
    capacity_loss_fraction: float = 0.0


class Battery:
    """Physical state machine for a grid-scale battery."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.state = BatteryState(
            soc=config.initial_soc,
            cell_temp_c=config.thermal["initial_temp_c"],
        )

    def step(self, target_power_mw: float, dt: float = 1.0) -> Dict[str, float]:
        """Advance the battery one timestep under a target power setpoint.

        Positive power = discharge (export); negative = charge (import).
        Returns a telemetry dict of the resulting state and the actual power
        delivered after physical constraints.
        """
        raise NotImplementedError

    def _soc_resistance_factor(self) -> float:
        """Exponential internal-resistance penalty near the SoC extremes."""
        raise NotImplementedError

    def _apply_efficiency(self, power_mw: float) -> float:
        """Apply round-trip efficiency separately for charge/discharge."""
        raise NotImplementedError

    def _update_thermal(self, resistive_loss_mw: float, dt: float) -> None:
        """Update cell temperature from I^2R heating, ambient, and HVAC cooling."""
        raise NotImplementedError

    def _update_degradation(self, power_mw: float, dt: float) -> None:
        """Accrue cycle-based and calendar-based capacity loss."""
        raise NotImplementedError

    def auxiliary_load_mw(self) -> float:
        """Base load plus dynamic HVAC load scaled by temperature deviation."""
        raise NotImplementedError
