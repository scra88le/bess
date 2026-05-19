from __future__ import annotations

import cvxpy as cp
import numpy as np
import pandas as pd

from .config import SiteSpec


def solve_perfect_foresight(
    prices: pd.Series,
    site: SiteSpec,
    timestep_hours: float,
) -> pd.DataFrame:
    """Maximise arbitrage revenue over the full price series with perfect foresight.

    Sign convention in the returned schedule: positive = discharge to grid,
    negative = charge from grid (matches `EnergyBucketBattery.step`).

    Returns a DataFrame indexed by the price timestamps with columns:
        price, p_charge, p_discharge, p_net, soc_planned
    """
    T = len(prices)
    if T == 0:
        raise ValueError("prices is empty")

    dt = timestep_hours
    eta_c = site.eta_charge
    eta_d = site.eta_discharge
    p_max = site.power_mw
    soc_min = site.soc_min_frac * site.energy_mwh
    soc_max = site.soc_max_frac * site.energy_mwh
    soc_initial = site.soc_initial_frac * site.energy_mwh
    price_arr = prices.to_numpy()

    p_c = cp.Variable(T, nonneg=True)
    p_d = cp.Variable(T, nonneg=True)
    soc = cp.Variable(T)  # SoC at end of each step

    delta = eta_c * dt * p_c - dt / eta_d * p_d

    constraints = [
        p_c <= p_max,
        p_d <= p_max,
        soc >= soc_min,
        soc <= soc_max,
        soc[0] == soc_initial + delta[0],
        soc[1:] == soc[:-1] + delta[1:],
        soc[-1] == soc_initial,
    ]

    revenue = price_arr @ (p_d - p_c) * dt
    problem = cp.Problem(cp.Maximize(revenue), constraints)
    problem.solve(solver=cp.HIGHS)

    if problem.status not in {"optimal", "optimal_inaccurate"}:
        raise RuntimeError(f"Optimiser failed: status={problem.status}")

    p_charge = np.asarray(p_c.value).ravel()
    p_discharge = np.asarray(p_d.value).ravel()
    soc_planned = np.asarray(soc.value).ravel()

    return pd.DataFrame(
        {
            "price": price_arr,
            "p_charge": p_charge,
            "p_discharge": p_discharge,
            "p_net": p_discharge - p_charge,
            "soc_planned": soc_planned,
        },
        index=prices.index,
    )
