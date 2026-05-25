from __future__ import annotations

from dataclasses import dataclass

import cvxpy as cp
import numpy as np
import pandas as pd

from .config import EfaConfig, SiteSpec


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


@dataclass
class ServicePriceSeries:
    prices: pd.Series
    response_hours: float


@dataclass
class SequentialResult:
    schedule: pd.DataFrame
    bid_curve: pd.DataFrame


_SERVICE_KINDS = ("dc_low", "dc_high")


def solve_sequential(
    prices: pd.Series,
    services: dict[str, ServicePriceSeries],
    site: SiteSpec,
    timestep_hours: float,
    efa: EfaConfig,
) -> SequentialResult:
    """Sequential wholesale-then-DC solve.

    Stage 1 solves wholesale-only via `solve_perfect_foresight`. Stage 2 derives, per
    EFA block, the deliverable DC-Low / DC-High commitments from the locked-in
    wholesale schedule and battery state, allocates them under the shared inverter
    rating priced by forecast clearing prices, and emits a per-block bid curve.

    DC commitments are assumed zero-delivery in expectation; the battery model and
    SoC trajectory are unaffected by them.
    """
    if any(k not in _SERVICE_KINDS for k in services):
        bad = sorted(set(services) - set(_SERVICE_KINDS))
        raise ValueError(f"Unknown service kinds: {bad}; supported: {_SERVICE_KINDS}")

    wholesale = solve_perfect_foresight(prices, site, timestep_hours)

    block_id = _assign_blocks(prices.index, efa.block_hours, efa.block_start_hour)

    soc_initial = site.soc_initial_frac * site.energy_mwh
    soc_min = site.soc_min_frac * site.energy_mwh
    soc_max = site.soc_max_frac * site.energy_mwh

    # SoC at every step boundary: trajectory[0] = initial, trajectory[i+1] = end of step i.
    soc_planned = wholesale["soc_planned"].to_numpy()
    trajectory = np.concatenate([[soc_initial], soc_planned])

    p_d = wholesale["p_discharge"].to_numpy()
    p_c = wholesale["p_charge"].to_numpy()

    low_series = services.get("dc_low")
    high_series = services.get("dc_high")
    response_hours_low = low_series.response_hours if low_series else 0.0
    response_hours_high = high_series.response_hours if high_series else 0.0
    low_prices = (
        low_series.prices.to_numpy() if low_series else np.zeros(len(prices), dtype=float)
    )
    high_prices = (
        high_series.prices.to_numpy() if high_series else np.zeros(len(prices), dtype=float)
    )

    c_low_per_step = np.zeros(len(prices), dtype=float)
    c_high_per_step = np.zeros(len(prices), dtype=float)

    bid_rows: list[dict] = []

    unique_blocks = np.unique(block_id)
    for bid in unique_blocks:
        mask = block_id == bid
        idxs = np.where(mask)[0]
        lo, hi = int(idxs[0]), int(idxs[-1])

        block_start = prices.index[lo]
        block_end = prices.index[hi]

        traj_slice = trajectory[lo : hi + 2]  # boundaries from start of step lo to end of step hi
        soc_min_in_block = float(traj_slice.min())
        soc_max_in_block = float(traj_slice.max())

        p_d_max = float(p_d[lo : hi + 1].max())
        p_c_max = float(p_c[lo : hi + 1].max())

        block_hours_actual = float(timestep_hours * len(idxs))

        # Forecast price for the block: mean over its timesteps.
        p_low_fc = float(low_prices[lo : hi + 1].mean()) if low_series else 0.0
        p_high_fc = float(high_prices[lo : hi + 1].mean()) if high_series else 0.0

        # Per-service headrooms.
        if low_series:
            power_low = max(0.0, site.power_mw - p_d_max)
            energy_low_raw = (soc_min_in_block - soc_min) * site.eta_discharge / response_hours_low
            energy_low = max(0.0, energy_low_raw)
            A_low = min(power_low, energy_low)
            binding_low = "power" if power_low <= energy_low else "energy"
        else:
            A_low = 0.0
            binding_low = "n/a"

        if high_series:
            power_high = max(0.0, site.power_mw - p_c_max)
            energy_high_raw = (soc_max - soc_max_in_block) / (response_hours_high * site.eta_charge)
            energy_high = max(0.0, energy_high_raw)
            A_high = min(power_high, energy_high)
            binding_high = "power" if power_high <= energy_high else "energy"
        else:
            A_high = 0.0
            binding_high = "n/a"

        # Allocation under shared inverter rating, ranked by forecast price.
        cap_low, cap_high = _allocate(A_low, A_high, site.power_mw, p_low_fc, p_high_fc)

        c_low_per_step[lo : hi + 1] = cap_low
        c_high_per_step[lo : hi + 1] = cap_high

        # Bid curves (1-2 cumulative tranches per service).
        if low_series:
            for price_threshold, mw in _bid_curve(A_low, A_high, site.power_mw, p_high_fc):
                bid_rows.append(
                    {
                        "service": "dc_low",
                        "block_start": block_start,
                        "block_end": block_end,
                        "block_hours": block_hours_actual,
                        "price_threshold_gbp_per_mw_h": price_threshold,
                        "mw_cumulative": mw,
                        "binding_constraint": binding_low,
                        "forecast_price_gbp_per_mw_h": p_low_fc,
                        "expected_revenue_gbp": cap_low * p_low_fc * block_hours_actual,
                    }
                )
        if high_series:
            for price_threshold, mw in _bid_curve(A_high, A_low, site.power_mw, p_low_fc):
                bid_rows.append(
                    {
                        "service": "dc_high",
                        "block_start": block_start,
                        "block_end": block_end,
                        "block_hours": block_hours_actual,
                        "price_threshold_gbp_per_mw_h": price_threshold,
                        "mw_cumulative": mw,
                        "binding_constraint": binding_high,
                        "forecast_price_gbp_per_mw_h": p_high_fc,
                        "expected_revenue_gbp": cap_high * p_high_fc * block_hours_actual,
                    }
                )

    schedule = wholesale.copy()
    schedule["c_dc_low"] = c_low_per_step
    schedule["c_dc_high"] = c_high_per_step
    schedule["dc_low_price"] = low_prices
    schedule["dc_high_price"] = high_prices

    bid_curve = pd.DataFrame(
        bid_rows,
        columns=[
            "service",
            "block_start",
            "block_end",
            "block_hours",
            "price_threshold_gbp_per_mw_h",
            "mw_cumulative",
            "binding_constraint",
            "forecast_price_gbp_per_mw_h",
            "expected_revenue_gbp",
        ],
    )
    return SequentialResult(schedule=schedule, bid_curve=bid_curve)


def _assign_blocks(
    index: pd.DatetimeIndex, block_hours: int, block_start_hour: int
) -> np.ndarray:
    """Tag each timestamp with an EFA block id (monotonic, starts at 0).

    Anchor at the most recent `block_start_hour` clock time at or before the first
    timestamp; partial blocks at the start or end of the horizon get their own id.
    """
    first = index[0]
    anchor_today = first.normalize() + pd.Timedelta(hours=block_start_hour)
    anchor = anchor_today if anchor_today <= first else anchor_today - pd.Timedelta(days=1)
    hours_from_anchor = (index - anchor) / pd.Timedelta(hours=1)
    raw = np.floor(np.asarray(hours_from_anchor, dtype=float) / float(block_hours)).astype(int)
    # Normalise so the first block is id 0.
    return raw - raw.min()


def _allocate(
    A_low: float, A_high: float, p_max: float, p_low_fc: float, p_high_fc: float
) -> tuple[float, float]:
    if A_low + A_high <= p_max:
        return A_low, A_high
    if p_low_fc >= p_high_fc:
        cap_low = min(A_low, p_max)
        cap_high = min(A_high, max(0.0, p_max - cap_low))
    else:
        cap_high = min(A_high, p_max)
        cap_low = min(A_low, max(0.0, p_max - cap_high))
    return cap_low, cap_high


def _bid_curve(
    A_self: float, A_other: float, p_max: float, p_other_fc: float
) -> list[tuple[float, float]]:
    """Cumulative-tranche bid curve for one service, given the other service's forecast.

    Returns 1-2 tranches as (price_threshold, mw_cumulative). At any clearing price
    `p`, the operator's offered MW is the largest `mw_cumulative` whose
    `price_threshold <= p`.
    """
    if A_self + A_other <= p_max:
        return [(0.0, A_self)]
    cap_at_low_price = min(A_self, max(0.0, p_max - A_other))
    cap_at_high_price = min(A_self, p_max)
    if cap_at_high_price > cap_at_low_price + 1e-9:
        return [(0.0, cap_at_low_price), (p_other_fc, cap_at_high_price)]
    return [(0.0, cap_at_high_price)]
