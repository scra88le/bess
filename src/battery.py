"""Battery physical state machine & core math.

The Battery class manages immediate physical transformations for a single
discrete step (default dt = 1 s). It is intentionally free of time
orchestration or external-system overrides (planned outages, grid clips,
ramping); that responsibility belongs to the DispatchEngine.

Sign convention for power (MW), grid-side:
    positive = discharge / export to grid
    negative = charge / import from grid

Round-trip efficiency is applied separately per direction, per the spec:
    discharging: the cells must supply P / eta to deliver P to the grid
    charging:    P * eta of grid energy actually reaches the cells
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict

from .config_loader import Config

SECONDS_PER_HOUR: float = 3600.0
SECONDS_PER_YEAR: float = 365.25 * 24 * 3600.0
WATTS_PER_MW: float = 1_000_000.0
KW_PER_MW: float = 1000.0


@dataclass
class BatteryState:
    """Snapshot of dynamic state variables at a single timestep."""

    soc: float  # state of charge, fraction [0, 1]
    cell_temp_c: float  # cell temperature
    cumulative_throughput_mwh: float = 0.0
    equivalent_full_cycles: float = 0.0
    capacity_loss_fraction: float = 0.0
    warranty_breached: bool = False


class Battery:
    """Physical state machine for a grid-scale battery."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.state = BatteryState(
            soc=config.initial_soc,
            cell_temp_c=config.thermal["initial_temp_c"],
        )

    # ------------------------------------------------------------------ #
    # Main step
    # ------------------------------------------------------------------ #
    def step(self, target_power_mw: float, dt: float = 1.0) -> Dict[str, Any]:
        """Advance the battery one timestep under a target power setpoint.

        Returns a telemetry dict describing the resulting state and the actual
        grid-side power delivered after physical constraints. ``limit_reason``
        is a non-empty string whenever the actual power diverged from the
        target because of the battery's own physics (not engine-level limits).
        """
        cfg = self.config
        st = self.state
        dt_h = dt / SECONDS_PER_HOUR

        # Effective capacity shrinks as the cells degrade.
        capacity_mwh = cfg.nominal_capacity_mwh * (1.0 - st.capacity_loss_fraction)
        ambient = cfg.thermal["ambient_temp_c"]
        optimal = float(cfg.thermal.get("optimal_temp_c", ambient))
        max_temp = cfg.thermal.get("max_cell_temp_c")

        target = float(target_power_mw)
        reason = ""

        # Auxiliary load is parasitic and evaluated against the temperature at
        # the start of the step (the Temp -> Aux feedback the spec calls for).
        aux_mw = self.auxiliary_load_mw()

        # --- Intra-step check: thermal cutoff -------------------------- #
        if max_temp is not None and st.cell_temp_c >= float(max_temp):
            desired = 0.0
            reason = "Thermal Trip"
        else:
            desired = target

        # --- Intra-step check: SoC non-linear boundary ----------------- #
        if desired != 0.0:
            charging = desired < 0.0
            factor = self._soc_capability_factor(charging)
            if factor < 1.0 and not reason:
                reason = "SoC Non-Linear Limit"
            desired *= factor

        # --- Energy bookkeeping at the cells --------------------------- #
        cell_power = self._cell_power(desired)  # +ve = leaving cells
        batt_cell_energy = cell_power * dt_h
        aux_energy = aux_mw * dt_h
        soc_raw = st.soc - (batt_cell_energy + aux_energy) / capacity_mwh

        # --- Clamp SoC to [0, 1] and back-solve actual battery action -- #
        if soc_raw < 0.0:
            soc_new = 0.0
            reason = reason or "SoC Floor"
        elif soc_raw > 1.0:
            soc_new = 1.0
            reason = reason or "SoC Ceiling"
        else:
            soc_new = soc_raw

        # Aux load has priority (it always runs); the battery absorbs the clamp.
        actual_batt_cell_energy = (st.soc - soc_new) * capacity_mwh - aux_energy
        if desired > 0.0:  # discharge: cells can only give energy
            actual_batt_cell_energy = max(0.0, actual_batt_cell_energy)
        elif desired < 0.0:  # charge: cells can only take energy (negative)
            actual_batt_cell_energy = min(0.0, actual_batt_cell_energy)
        else:
            actual_batt_cell_energy = 0.0

        # Recompute SoC consistently with the clamped battery action + aux.
        soc_new = st.soc - (actual_batt_cell_energy + aux_energy) / capacity_mwh
        soc_new = min(1.0, max(0.0, soc_new))

        actual_cell_power = actual_batt_cell_energy / dt_h if dt_h else 0.0
        actual_grid = self._grid_power(actual_cell_power)

        if not reason and abs(actual_grid - target) > 1e-9:
            reason = "SoC Limit"

        # --- Thermal: I^2R heating from actual throughput, then cooling - #
        resistive_loss_mw = abs(abs(actual_cell_power) - abs(actual_grid))
        self._update_thermal(resistive_loss_mw, dt, optimal)

        # --- Commit SoC and accrue degradation ------------------------- #
        st.soc = soc_new
        self._update_degradation(abs(actual_batt_cell_energy), dt)

        return {
            "target_mw": target,
            "actual_mw": actual_grid,
            "soc": st.soc,
            "cell_temp_c": st.cell_temp_c,
            "ambient_temp_c": ambient,
            "aux_load_mw": aux_mw,
            "resistive_loss_mw": resistive_loss_mw,
            "cumulative_throughput_mwh": st.cumulative_throughput_mwh,
            "equivalent_full_cycles": st.equivalent_full_cycles,
            "capacity_loss_fraction": st.capacity_loss_fraction,
            "warranty_breached": float(st.warranty_breached),
            "limit_reason": reason,
        }

    # ------------------------------------------------------------------ #
    # Physics helpers
    # ------------------------------------------------------------------ #
    def _soc_capability_factor(self, charging: bool) -> float:
        """Capability derate from rising internal resistance near the extremes.

        Resistance grows exponentially once SoC passes the configured
        thresholds, so usable power capability is ``exp(-k * depth)`` where
        ``depth`` runs 0 -> 1 from the threshold to the relevant rail. Returns
        1.0 inside the linear range. Charging is limited near the top rail,
        discharging near the bottom rail.
        """
        soc = self.state.soc
        nl = self.config.soc_non_linearity
        lower = nl["lower_threshold"]
        upper = nl["upper_threshold"]
        k = nl["exponential_factor"]

        if charging:
            if soc <= upper:
                return 1.0
            depth = (soc - upper) / max(1e-9, 1.0 - upper)
        else:
            if soc >= lower:
                return 1.0
            depth = (lower - soc) / max(1e-9, lower)

        depth = min(1.0, max(0.0, depth))
        return math.exp(-k * depth)

    def _cell_power(self, grid_power_mw: float) -> float:
        """Cell-side power for a grid-side setpoint (+ve = leaving the cells)."""
        eta = self.config.efficiency
        if grid_power_mw > 0.0:  # discharge: cells must supply more
            return grid_power_mw / eta
        if grid_power_mw < 0.0:  # charge: less reaches the cells
            return grid_power_mw * eta
        return 0.0

    def _grid_power(self, cell_power_mw: float) -> float:
        """Grid-side power for a cell-side flow (inverse of ``_cell_power``)."""
        eta = self.config.efficiency
        if cell_power_mw > 0.0:  # discharge
            return cell_power_mw * eta
        if cell_power_mw < 0.0:  # charge
            return cell_power_mw / eta
        return 0.0

    def _update_thermal(
        self, resistive_loss_mw: float, dt: float, optimal_temp_c: float
    ) -> None:
        """Update cell temperature from I^2R heating then HVAC cooling.

        All resistive (efficiency) loss becomes heat: ``dT = Q / thermal_mass``.
        HVAC then removes heat toward the optimal temperature at up to the
        configured rate, never overshooting below optimal.
        """
        thermal = self.config.thermal
        heat_j = resistive_loss_mw * WATTS_PER_MW * dt
        self.state.cell_temp_c += heat_j / thermal["thermal_mass"]

        if self.state.cell_temp_c > optimal_temp_c:
            cooling = min(
                thermal["hvac_cooling_rate_c_per_sec"] * dt,
                self.state.cell_temp_c - optimal_temp_c,
            )
            self.state.cell_temp_c -= cooling

    def _update_degradation(self, throughput_mwh: float, dt: float) -> None:
        """Accrue cycle-based and calendar-based capacity loss, flag warranty."""
        cfg = self.config
        st = self.state
        nominal = cfg.nominal_capacity_mwh
        max_efc = cfg.warranty["max_equivalent_full_cycles"]

        # One equivalent full cycle = 2 x capacity of throughput (charge+discharge).
        efc_delta = throughput_mwh / (2.0 * nominal)
        st.cumulative_throughput_mwh += throughput_mwh
        st.equivalent_full_cycles += efc_delta

        deg = cfg.degradation
        cycle_loss_per_efc = float(deg.get("cycle_loss_per_efc", 0.20 / max_efc))
        calendar_per_sec = (
            float(deg.get("calendar_loss_per_year", 0.0)) / SECONDS_PER_YEAR
        )

        st.capacity_loss_fraction = min(
            0.9999,
            st.capacity_loss_fraction
            + cycle_loss_per_efc * efc_delta
            + calendar_per_sec * dt,
        )
        st.warranty_breached = st.equivalent_full_cycles > max_efc

    def auxiliary_load_mw(self) -> float:
        """Base load plus dynamic HVAC load scaled by temperature deviation."""
        aux = self.config.auxiliary_load_kw
        optimal = float(
            self.config.thermal.get(
                "optimal_temp_c", self.config.thermal["ambient_temp_c"]
            )
        )
        deviation = max(0.0, self.state.cell_temp_c - optimal)
        kw = aux["base"] + aux["hvac_per_degree"] * deviation
        return kw / KW_PER_MW
