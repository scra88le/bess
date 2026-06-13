"""Day-ahead dispatch optimisation as a linear program (PuLP / CBC).

This is the reduced-order *planning* model — a convex LP that captures the
first-order economics of arbitrage. It is intentionally simpler than the
physics model: constant per-direction efficiency, a linear SoC band, no
thermal/degradation feedback. The full simulator validates the plan afterwards.

Decision variables per period t: discharge dis[t] >= 0, charge chg[t] >= 0,
and state of charge soc[t] (fraction). Discharge draws dis/eta from the cells,
charge stores chg*eta — mirroring src/battery.py's per-direction efficiency.

It is a pure LP (no binaries): under an arbitrage objective simultaneous
charge+discharge is never optimal, so no anti-simultaneity constraint is needed.
MILP would only be required for min up/down times, block bids, or startup costs.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import List, Optional

import pulp

from ..config_loader import Config
from .schedule import Schedule


class OptimisationError(RuntimeError):
    """Raised when the LP does not solve to optimality."""


@dataclass
class OptimiseOptions:
    """Tunable optimisation parameters (kept out of the physics Config)."""

    terminal_soc: Optional[float] = None      # default = initial_soc
    degradation_cost: float = 0.0             # £/MWh penalty on throughput
    soc_terminal_tol: float = 1e-3            # band around terminal SoC
    capacity_loss_fraction: float = 0.0       # plan against today's degraded capacity


def optimise(config: Config, prices: List[float], resolution_minutes: int,
             options: Optional[OptimiseOptions] = None,
             date: Optional[str] = None) -> Schedule:
    """Solve the day-ahead arbitrage LP and return the optimal schedule."""
    opts = options or OptimiseOptions()
    n = len(prices)
    if n == 0:
        raise OptimisationError("price forecast is empty")

    h = resolution_minutes / 60.0                                   # period length, hours
    eta = config.efficiency
    capacity = config.nominal_capacity_mwh * (1.0 - opts.capacity_loss_fraction)
    soc0 = config.initial_soc
    s_lo = config.soc_non_linearity["lower_threshold"]
    s_hi = config.soc_non_linearity["upper_threshold"]
    max_dis = float(config.grid_constraints["max_export_mw"])
    max_chg = float(config.grid_constraints["max_import_mw"])
    terminal = opts.terminal_soc if opts.terminal_soc is not None else soc0

    # PuLP 3.x emits forward-looking (PuLP 4.0) deprecation warnings when
    # constructing LpVariable/PULP_CBC_CMD directly. Both are the only APIs
    # guaranteed to work here (the bundled CBC needs no external binary), so
    # silence those warnings across the whole build + solve.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)

        prob = pulp.LpProblem("da_arbitrage", pulp.LpMaximize)
        dis = [pulp.LpVariable(f"dis_{t}", lowBound=0, upBound=max_dis) for t in range(n)]
        chg = [pulp.LpVariable(f"chg_{t}", lowBound=0, upBound=max_chg) for t in range(n)]
        soc = [pulp.LpVariable(f"soc_{t}", lowBound=s_lo, upBound=s_hi) for t in range(n)]

        # SoC dynamics (mirrors the battery's per-direction efficiency).
        for t in range(n):
            prev = soc[t - 1] if t > 0 else soc0
            prob += soc[t] == prev - (dis[t] / eta) * h / capacity + (chg[t] * eta) * h / capacity

        # Terminal SoC as a tight band (equality can be infeasible on coarse grids).
        prob += soc[n - 1] >= terminal - opts.soc_terminal_tol
        prob += soc[n - 1] <= terminal + opts.soc_terminal_tol

        # Objective: arbitrage revenue minus a linear throughput (degradation) cost.
        revenue = pulp.lpSum(prices[t] * (dis[t] - chg[t]) * h for t in range(n))
        throughput = pulp.lpSum((dis[t] + chg[t]) * h for t in range(n))
        prob += revenue - opts.degradation_cost * throughput

        status = prob.solve(pulp.PULP_CBC_CMD(msg=False))

    if pulp.LpStatus[status] != "Optimal":
        raise OptimisationError(f"LP did not solve to optimality: {pulp.LpStatus[status]}")

    power_mw: List[float] = []
    for t in range(n):
        net = (dis[t].value() or 0.0) - (chg[t].value() or 0.0)
        if abs(net) < 1e-6:
            net = 0.0
        power_mw.append(round(net, 6))

    return Schedule(
        date=date,
        resolution_minutes=resolution_minutes,
        power_mw=power_mw,
        terminal_soc=terminal,
        objective_value=float(pulp.value(prob.objective)),
    )
