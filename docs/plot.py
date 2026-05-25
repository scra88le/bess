import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
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

soc_planned_t = schedule.index + dt
soc_planned_y = schedule["soc_planned"].to_numpy()
soc_actual_t = telemetry["timestamp"] + dt
soc_actual_y = telemetry["soc_mwh"].to_numpy()

fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)

ax = axes[0]
ax.plot(schedule.index, schedule["price"], color="black", linewidth=1, drawstyle="steps-post")
ax.set_ylabel("Price (£/MWh)")
ax.set_title("Price")
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
ax.set_title("Schedule")
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
ax.set_xlabel("Time")
ax.legend(loc="upper right")
ax.grid(alpha=0.3)

fig.tight_layout()
out = out_dir / "plot.png"
fig.savefig(out, dpi=120)
print(f"saved {out}")
