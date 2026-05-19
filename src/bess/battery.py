from __future__ import annotations

from dataclasses import dataclass

from .config import SiteSpec

# Energy tolerance below which a clip is considered numerical noise rather than
# a real binding constraint. 1e-9 MWh = 3.6 J, well below any meaningful action.
_CLIP_TOL_MWH = 1e-9


@dataclass
class StepResult:
    power_setpoint_mw: float
    power_actual_mw: float
    soc_mwh: float
    soc_frac: float
    clipped: bool


class EnergyBucketBattery:
    """Energy-bucket battery model.

    Sign convention: positive power = discharge to grid, negative = charge from grid.
    Efficiency is applied at the AC↔DC boundary: charging an MWh of grid energy
    deposits eta_charge MWh in the bucket; discharging an MWh from the bucket
    delivers eta_discharge MWh to the grid.
    """

    def __init__(self, site: SiteSpec, timestep_hours: float):
        self.site = site
        self.dt = timestep_hours
        self.p_max = site.power_mw
        self.soc_min = site.soc_min_frac * site.energy_mwh
        self.soc_max = site.soc_max_frac * site.energy_mwh
        self.soc_mwh = site.soc_initial_frac * site.energy_mwh

    def step(self, power_mw: float) -> StepResult:
        setpoint = power_mw
        p = max(-self.p_max, min(self.p_max, setpoint))
        clipped = abs(p - setpoint) > _CLIP_TOL_MWH / max(self.dt, 1e-12)

        if p >= 0:
            energy_from_bucket = p * self.dt / self.site.eta_discharge
            available = self.soc_mwh - self.soc_min
            if energy_from_bucket > available + _CLIP_TOL_MWH:
                energy_from_bucket = max(0.0, available)
                p = energy_from_bucket * self.site.eta_discharge / self.dt
                clipped = True
            else:
                energy_from_bucket = min(energy_from_bucket, max(0.0, available))
            self.soc_mwh -= energy_from_bucket
        else:
            energy_to_bucket = -p * self.dt * self.site.eta_charge
            headroom = self.soc_max - self.soc_mwh
            if energy_to_bucket > headroom + _CLIP_TOL_MWH:
                energy_to_bucket = max(0.0, headroom)
                p = -energy_to_bucket / (self.dt * self.site.eta_charge)
                clipped = True
            else:
                energy_to_bucket = min(energy_to_bucket, max(0.0, headroom))
            self.soc_mwh += energy_to_bucket

        return StepResult(
            power_setpoint_mw=setpoint,
            power_actual_mw=p,
            soc_mwh=self.soc_mwh,
            soc_frac=self.soc_mwh / self.site.energy_mwh,
            clipped=clipped,
        )
