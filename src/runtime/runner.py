"""The long-running runner: follow the daily schedule, emit minute telemetry.

Each simulated second: read the scheduled setpoint, advance the engine, fold the
row into the current minute. On a minute boundary: write the minute record and
checkpoint. At a day boundary: load the next day's schedule (raising if it's
missing — no silent fallback) and continue.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, Union

from ..battery import Battery
from ..config_loader import Config
from ..dispatch_engine import DispatchEngine
from ..optimiser.schedule import Schedule
from . import state
from .aggregator import MinuteAggregator
from .clock import SimClock
from .config import RunnerConfig
from .sink import NullTelemetry, TelemetrySink

StartLike = Union[str, dt.date, dt.datetime]


def _as_datetime(start: StartLike) -> dt.datetime:
    if isinstance(start, dt.datetime):
        return start
    if isinstance(start, dt.date):
        return dt.datetime.combine(start, dt.time())
    return dt.datetime.fromisoformat(start)


def run(
    config: Config, runner_config: RunnerConfig, start: StartLike
) -> Dict[str, Any]:
    """Run the simulator, consuming daily schedules and emitting minute telemetry.

    Returns a summary dict. Raises ``MissingArtifactError`` if a required day's
    schedule is absent.
    """
    root = runner_config.root
    battery = Battery(config)
    engine = DispatchEngine(config, battery, NullTelemetry())
    sink = TelemetrySink(root)

    checkpoint = state.load(root)
    if checkpoint is not None:
        start_dt = state.apply(checkpoint, battery, engine)
    else:
        start_dt = _as_datetime(start)

    clock = SimClock(start_dt, runner_config.time_scale)
    aggregator = MinuteAggregator()
    days_run = 0
    minutes_written = 0

    while runner_config.days is None or days_run < runner_config.days:
        date = clock.date
        schedule = Schedule.read(root, date)  # raises MissingArtifactError if absent
        engine.begin_day()

        while clock.date == date:
            power = schedule.power_at_second(clock.second_of_day)
            aggregator.add(engine.step(power, dt=1.0))

            minute_end = clock.is_minute_end()
            minute_index = clock.minute_index
            minute_ts = clock.minute_start().isoformat()
            clock.tick()  # advance first so checkpoint points at next second

            if minute_end:
                record = aggregator.flush(date.isoformat(), minute_index, minute_ts)
                sink.write_minute(date, minute_index, record)
                minutes_written += 1
                if runner_config.checkpoint:
                    state.save(root, battery, engine, clock.sim_now, clock.time_scale)

        days_run += 1

    return {
        "days_run": days_run,
        "minutes_written": minutes_written,
        "end_sim_now": clock.sim_now.isoformat(),
        "final_soc": battery.state.soc,
    }
