"""Real-time state recording and terminal/chart visualization."""

from __future__ import annotations

from typing import Dict, List


class Telemetry:
    """Records time-series state rows and renders them to stdout or charts."""

    def __init__(self) -> None:
        self.rows: List[Dict[str, float]] = []

    def record(self, row: Dict[str, float]) -> None:
        """Append a single timestep's state to the in-memory buffer."""
        self.rows.append(row)

    def emit_stdout(self) -> None:
        """Stream recorded rows as time-series text to stdout."""
        raise NotImplementedError

    def visualize(self) -> None:
        """Open a matplotlib.animation dashboard with the four required subplots:

        1. Power (Target vs. Actual vs. Grid Limits)
        2. SoC % over time
        3. Cell Temperature vs. Ambient Temperature
        4. Cumulative Capacity Loss / Degradation Counter
        """
        raise NotImplementedError
