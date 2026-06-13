"""Telemetry sink and a no-op telemetry for the engine.

``NullTelemetry`` is handed to the engine so its in-memory ``rows`` buffer never
grows during a multi-day run — the runner consumes each returned row directly
and writes aggregated minute records through ``TelemetrySink``.
"""

from __future__ import annotations

from typing import Any, Dict

from .. import io_layout
from ..io_layout import DateLike


class NullTelemetry:
    """Telemetry interface that discards rows (the engine only calls record)."""

    def record(self, row: Dict[str, Any]) -> None:  # noqa: D401 - no-op
        pass


class TelemetrySink:
    """Writes one minute record per file into the date-partitioned layout."""

    def __init__(self, root: str) -> None:
        self.root = root

    def write_minute(self, date: DateLike, minute_index: int,
                     record: Dict[str, Any]) -> str:
        path = io_layout.telemetry_path(self.root, date, minute_index)
        io_layout.write_table(path, [record])
        return path
