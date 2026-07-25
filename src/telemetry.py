"""Real-time state recording and terminal/chart visualization."""

from __future__ import annotations

import sys
from typing import Any, Dict, List

# Column order for stdout/CSV emission. Keys absent from a row are left blank.
_COLUMNS: List[str] = [
    "timestamp_s",
    "injected_mw",
    "target_mw",
    "actual_mw",
    "grid_limit_export_mw",
    "grid_limit_import_mw",
    "soc",
    "cell_temp_c",
    "ambient_temp_c",
    "aux_load_mw",
    "resistive_loss_mw",
    "cumulative_throughput_mwh",
    "equivalent_full_cycles",
    "capacity_loss_fraction",
    "warranty_breached",
    "limit_reason",
]


class Telemetry:
    """Records time-series state rows and renders them to stdout or charts."""

    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []

    def record(self, row: Dict[str, Any]) -> None:
        """Append a single timestep's state to the in-memory buffer."""
        self.rows.append(row)

    def column(self, key: str) -> List[Any]:
        """Extract one field across all recorded rows."""
        return [row.get(key) for row in self.rows]

    def emit_stdout(self) -> None:
        """Stream recorded rows as comma-separated time-series text to stdout."""
        if not self.rows:
            print("# no telemetry recorded", file=sys.stderr)
            return

        print(",".join(_COLUMNS))
        for row in self.rows:
            print(",".join(_format(row.get(col)) for col in _COLUMNS))

    def visualize(self) -> None:
        """Open a matplotlib dashboard of the recorded run with four subplots:

        1. Power (Target vs. Actual vs. Grid Limits)
        2. SoC % over time
        3. Cell Temperature vs. Ambient Temperature
        4. Cumulative Capacity Loss / Degradation Counter
        """
        fig = self.build_figure()
        try:
            import matplotlib.pyplot as plt
        except ImportError as exc:  # pragma: no cover - exercised via build_figure
            raise RuntimeError("matplotlib is required for --visualize") from exc
        plt.show()
        return fig

    def build_figure(self):
        """Build (but do not show) the dashboard figure. Separated for testing."""
        try:
            import matplotlib.pyplot as plt
        except ImportError as exc:
            raise RuntimeError(
                "matplotlib is required for visualization; install it via "
                "`pip install matplotlib`"
            ) from exc

        if not self.rows:
            raise ValueError("no telemetry recorded to visualize")

        t = self.column("timestamp_s")
        fig, (ax_power, ax_soc, ax_temp, ax_deg) = plt.subplots(
            4, 1, figsize=(11, 9), sharex=True
        )

        # 1. Power: target vs actual, bounded by grid limits.
        ax_power.plot(
            t,
            self.column("injected_mw"),
            label="Target (injected)",
            color="tab:blue",
            alpha=0.7,
        )
        ax_power.plot(t, self.column("actual_mw"), label="Actual", color="tab:orange")
        export = self.column("grid_limit_export_mw")
        imp = self.column("grid_limit_import_mw")
        if any(v is not None for v in export):
            ax_power.plot(
                t, export, "--", color="grey", linewidth=0.8, label="Grid limits"
            )
            ax_power.plot(t, imp, "--", color="grey", linewidth=0.8)
        ax_power.axhline(0.0, color="black", linewidth=0.5)
        ax_power.set_ylabel("Power (MW)")
        ax_power.legend(loc="upper right", fontsize="small")
        ax_power.set_title("BESS dispatch telemetry")

        # 2. SoC %.
        soc_pct = [v * 100.0 if v is not None else None for v in self.column("soc")]
        ax_soc.plot(t, soc_pct, color="tab:green")
        ax_soc.set_ylabel("SoC (%)")
        ax_soc.set_ylim(0, 100)

        # 3. Cell vs ambient temperature.
        ax_temp.plot(t, self.column("cell_temp_c"), label="Cell", color="tab:red")
        ax_temp.plot(
            t,
            self.column("ambient_temp_c"),
            label="Ambient",
            color="tab:cyan",
            linestyle="--",
        )
        ax_temp.set_ylabel("Temp (°C)")
        ax_temp.legend(loc="upper right", fontsize="small")

        # 4. Degradation: capacity loss with EFC on a twin axis.
        loss_pct = [
            v * 100.0 if v is not None else None
            for v in self.column("capacity_loss_fraction")
        ]
        ax_deg.plot(t, loss_pct, color="tab:purple", label="Capacity loss")
        ax_deg.set_ylabel("Capacity loss (%)")
        ax_deg.set_xlabel("Time (s)")
        ax_efc = ax_deg.twinx()
        ax_efc.plot(
            t,
            self.column("equivalent_full_cycles"),
            color="tab:brown",
            linestyle=":",
            label="EFC",
        )
        ax_efc.set_ylabel("Equivalent full cycles")

        fig.tight_layout()
        return fig


def _format(value: Any) -> str:
    """Render one cell for CSV output."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)
