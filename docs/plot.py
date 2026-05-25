import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

if len(sys.argv) < 2:
    sys.exit("usage: plot.py <run_dir>")
run_dir = Path(sys.argv[1])
out_dir = Path(__file__).parent
telemetry = pd.read_parquet(run_dir / "telemetry.parquet")
schedule = pd.read_parquet(run_dir / "schedule.parquet")

manifest = json.loads((run_dir / "manifest.json").read_text())
site = manifest["scenario"]["site"]
soc_initial_mwh = site["soc_initial_frac"] * site["energy_mwh"]
dt = pd.Timedelta(minutes=manifest["scenario"]["timestep_minutes"])

has_dc = (run_dir / "bid_curve.parquet").exists()

soc_planned_t = schedule.index + dt
soc_planned_y = schedule["soc_planned"].to_numpy()
soc_actual_t = telemetry["timestamp"] + dt
soc_actual_y = telemetry["soc_mwh"].to_numpy()

n_panels = 4 if has_dc else 3
fig, axes = plt.subplots(n_panels, 1, figsize=(12, 2.6 * n_panels), sharex=True)

ax = axes[0]
ax.plot(schedule.index, schedule["price"], color="black", linewidth=1, drawstyle="steps-post")
ax.set_ylabel("Price (£/MWh)")
ax.set_title("Wholesale price")
ax.grid(alpha=0.3)

ax = axes[1]
ax.plot(
    schedule.index,
    schedule["p_net"],
    color="tab:blue",
    linewidth=1,
    label="planned",
    drawstyle="steps-post",
)
ax.plot(
    telemetry["timestamp"],
    telemetry["p_actual_mw"],
    color="tab:orange",
    linewidth=1,
    linestyle="--",
    label="actual",
    drawstyle="steps-post",
)
ax.axhline(0, color="grey", linewidth=0.5)
ax.set_ylabel("Power (MW)\n+discharge / -charge")
ax.set_title("Wholesale schedule")
ax.legend(loc="upper right")
ax.grid(alpha=0.3)

ax = axes[2]
ax.plot(
    [schedule.index[0], *soc_planned_t],
    [soc_initial_mwh, *soc_planned_y],
    color="tab:blue",
    linewidth=1,
    label="planned",
)
ax.plot(
    [telemetry["timestamp"].iloc[0], *soc_actual_t],
    [soc_initial_mwh, *soc_actual_y],
    color="tab:orange",
    linewidth=1,
    linestyle="--",
    label="actual",
)
ax.set_ylabel("SoC (MWh)")
ax.set_title("State of charge")
ax.legend(loc="upper right")
ax.grid(alpha=0.3)

if has_dc:
    ax = axes[3]
    ax.plot(
        schedule.index,
        schedule["c_dc_low"],
        color="tab:green",
        linewidth=1.2,
        label="DC-Low committed",
        drawstyle="steps-post",
    )
    ax.plot(
        schedule.index,
        schedule["c_dc_high"],
        color="tab:purple",
        linewidth=1.2,
        label="DC-High committed",
        drawstyle="steps-post",
    )
    ax.set_ylabel("Committed MW")
    ax.set_title("DC commitment (per EFA block)")
    ax.legend(loc="upper right")
    ax.grid(alpha=0.3)

axes[-1].set_xlabel("Time")
fig.tight_layout()
out = out_dir / "plot.png"
fig.savefig(out, dpi=120)
print(f"saved {out}")

if has_dc:
    bid_curve = pd.read_parquet(run_dir / "bid_curve.parquet")
    fig2, axes2 = plt.subplots(1, 2, figsize=(12, 5))
    services = ["dc_low", "dc_high"]
    titles = {"dc_low": "DC-Low bid curves", "dc_high": "DC-High bid curves"}

    for ax, service in zip(axes2, services):
        sub = bid_curve[bid_curve["service"] == service]
        if sub.empty:
            ax.set_visible(False)
            continue

        cmap = plt.get_cmap("viridis")
        block_starts = sorted(sub["block_start"].unique())
        x_max = max(
            float(sub["price_threshold_gbp_per_mw_h"].max()),
            float(sub["forecast_price_gbp_per_mw_h"].max()),
        ) * 1.4 or 1.0

        for i, block_start in enumerate(block_starts):
            colour = cmap(i / max(1, len(block_starts) - 1))
            block_df = sub[sub["block_start"] == block_start].sort_values(
                "price_threshold_gbp_per_mw_h"
            )
            prices_arr = block_df["price_threshold_gbp_per_mw_h"].to_numpy()
            mws = block_df["mw_cumulative"].to_numpy()
            xs = np.concatenate([prices_arr, [x_max]])
            ys = np.concatenate([mws, [mws[-1]]])
            label = pd.to_datetime(block_start).strftime("%m-%d %H:%M")
            ax.step(xs, ys, where="post", color=colour, linewidth=1.4, label=label)
            forecast = float(block_df["forecast_price_gbp_per_mw_h"].iloc[0])
            ax.axvline(forecast, color=colour, linewidth=0.7, linestyle=":", alpha=0.7)

        ax.set_xlabel("Bid price (£/MW/h)")
        ax.set_ylabel("MW offered (cumulative)")
        ax.set_title(f"{titles[service]} — dotted = forecast clearing price")
        ax.legend(title="EFA block start", fontsize="x-small", loc="lower right")
        ax.set_xlim(left=0, right=x_max)
        ax.set_ylim(bottom=0)
        ax.grid(alpha=0.3)

    fig2.tight_layout()
    out_bids = out_dir / "plot_bids.png"
    fig2.savefig(out_bids, dpi=120)
    print(f"saved {out_bids}")
