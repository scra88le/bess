"""Wall-clock pacing for the simulator.

``SimClock`` maps simulation time to wall time via ``time_scale`` (sim-seconds
per wall-second): 1.0 is real time, large values accelerate (a full day in
seconds) for dev/demo. The sleep is drift-corrected against a fixed anchor so
errors don't accumulate, and collapses to no sleep for large time_scale.
"""

from __future__ import annotations

import datetime as dt
import time


class SimClock:
    def __init__(
        self, start: dt.datetime, time_scale: float = 1.0, dt_seconds: float = 1.0
    ) -> None:
        self.sim_now = start
        self.time_scale = float(time_scale)
        self.dt = float(dt_seconds)
        self._sim_start = start
        self._wall_start = time.monotonic()

    @property
    def date(self) -> dt.date:
        return self.sim_now.date()

    @property
    def second_of_day(self) -> int:
        return self.sim_now.hour * 3600 + self.sim_now.minute * 60 + self.sim_now.second

    @property
    def minute_index(self) -> int:
        return self.second_of_day // 60

    def is_minute_end(self) -> bool:
        """True on the final second of a minute (flush boundary)."""
        return self.second_of_day % 60 == 59

    def minute_start(self) -> dt.datetime:
        """Timestamp of the start of the current minute."""
        return self.sim_now.replace(second=0, microsecond=0)

    def tick(self) -> None:
        """Advance one ``dt`` of sim time, sleeping to honour ``time_scale``."""
        self.sim_now += dt.timedelta(seconds=self.dt)
        if self.time_scale > 0:
            sim_elapsed = (self.sim_now - self._sim_start).total_seconds()
            delay = (
                self._wall_start + sim_elapsed / self.time_scale
            ) - time.monotonic()
            if delay > 0:
                time.sleep(delay)
