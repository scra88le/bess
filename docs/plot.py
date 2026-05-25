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

fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)

ax = axes[0]
ax.plot(schedule.index, schedule["price"], color="black", linewidth=1)
ax.set_ylabel("Price (£/MWh)")
ax.set_title("Price")
ax.grid(alpha=0.3)

ax = axes[1]
ax.plot(schedule.index, schedule["p_net"], color="tab:blue", linewidth=1, label="planned")
ax.plot(
    telemetry["timestamp"],
    telemetry["p_actual_mw"],
    color="tab:orange",
    linewidth=1,
    linestyle="--",
    label="actual",
)
ax.axhline(0, color="grey", linewidth=0.5)
ax.set_ylabel("Power (MW)\n+discharge / -charge")
ax.set_title("Schedule")
ax.legend(loc="upper right")
ax.grid(alpha=0.3)

ax = axes[2]
ax.plot(schedule.index, schedule["soc_planned"], color="tab:blue", linewidth=1, label="planned")
ax.plot(
    telemetry["timestamp"],
    telemetry["soc_mwh"],
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
