"""CLI entry point for the grid-scale BESS physical model simulation."""

from __future__ import annotations

import csv
import datetime as dt
import os
from typing import List, Optional, Tuple

import click

from src import optimiser as opt
from src.battery import Battery
from src.config_loader import load_config
from src.dispatch_engine import DispatchEngine
from src.optimiser import OptimiseOptions
from src.prices.generator import generate as generate_prices
from src.runtime import RunnerConfig, run as run_service
from src.telemetry import Telemetry

SCENARIOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scenarios")
DEFAULT_CONFIG = "config.yaml"
DEFAULT_DISPATCH = "dispatch.csv"


def _load_dispatch(path: str) -> List[float]:
    """Read a 1-second-resolution dispatch CSV into a list of MW setpoints."""
    dispatch: List[float] = []
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            dispatch.append(float(row["dispatch_mw"]))
    return dispatch


def _available_scenarios() -> List[str]:
    """Names of scenarios/<name>/ folders that hold a config + dispatch pair."""
    if not os.path.isdir(SCENARIOS_DIR):
        return []
    names = []
    for name in sorted(os.listdir(SCENARIOS_DIR)):
        folder = os.path.join(SCENARIOS_DIR, name)
        if (os.path.isfile(os.path.join(folder, "config.yaml"))
                and os.path.isfile(os.path.join(folder, "dispatch.csv"))):
            names.append(name)
    return names


def _resolve_inputs(scenario: Optional[str], config_path: Optional[str],
                    dispatch_path: Optional[str]) -> Tuple[str, str]:
    """Resolve the (config, dispatch) paths from the CLI options.

    With ``--scenario`` the paths are taken from ``scenarios/<name>/``; it is
    mutually exclusive with ``--config``/``--dispatch``. Without it, the
    explicit paths (or their defaults) are used.
    """
    if scenario is None:
        return config_path or DEFAULT_CONFIG, dispatch_path or DEFAULT_DISPATCH

    if config_path is not None or dispatch_path is not None:
        raise click.UsageError("--scenario cannot be combined with --config/--dispatch.")

    folder = os.path.join(SCENARIOS_DIR, scenario)
    cfg = os.path.join(folder, "config.yaml")
    disp = os.path.join(folder, "dispatch.csv")
    if not (os.path.isfile(cfg) and os.path.isfile(disp)):
        available = ", ".join(_available_scenarios()) or "(none found)"
        raise click.BadParameter(
            f"unknown scenario '{scenario}'. Available: {available}",
            param_hint="'--scenario'",
        )
    return cfg, disp


@click.group()
def cli() -> None:
    """Grid-scale BESS: simulate, optimise day-ahead dispatch, or run the service."""


@cli.command()
@click.option("--scenario", default=None,
              help="Run a named scenario from scenarios/<name>/ (its config.yaml "
                   "+ dispatch.csv). Mutually exclusive with --config/--dispatch.")
@click.option("--config", "config_path", default=None,
              help=f"Path to the physical parameters configuration file "
                   f"(default: {DEFAULT_CONFIG}).")
@click.option("--dispatch", "dispatch_path", default=None,
              help=f"Path to the time-series dispatch signal, 1s resolution "
                   f"(default: {DEFAULT_DISPATCH}).")
@click.option("--visualize", is_flag=True,
              help="Open a live matplotlib dashboard during the run.")
def simulate(scenario: Optional[str], config_path: Optional[str],
             dispatch_path: Optional[str], visualize: bool) -> None:
    """Run the high-fidelity simulation over a dispatch signal."""
    config_path, dispatch_path = _resolve_inputs(scenario, config_path, dispatch_path)

    config = load_config(config_path)
    dispatch = _load_dispatch(dispatch_path)

    battery = Battery(config)
    telemetry = Telemetry()
    engine = DispatchEngine(config, battery, telemetry)

    engine.run(dispatch)

    if visualize:
        telemetry.visualize()
    else:
        telemetry.emit_stdout()


@cli.command(name="generate-prices")
@click.option("--root", required=True, help="Data root (fsspec URL: ./data or s3://…).")
@click.option("--start", default=None,
              help="First day, YYYY-MM-DD (default: today).")
@click.option("--days", type=int, default=7, show_default=True,
              help="Number of daily forecasts to write.")
@click.option("--resolution-minutes", type=int, default=30, show_default=True,
              help="Market period length (must divide 1440).")
@click.option("--seed", type=int, default=0, show_default=True,
              help="Seed for the synthetic price model (reproducible per date).")
def generate_prices_cmd(root: str, start: Optional[str], days: int,
                        resolution_minutes: int, seed: int) -> None:
    """Generate N days of synthetic day-ahead price forecasts in advance."""
    start = start or dt.date.today().isoformat()
    paths = generate_prices(root, start, days, resolution_minutes=resolution_minutes,
                            seed=seed)
    click.echo(f"Wrote {len(paths)} forecast(s) from {start} under {root}/prices/")


@cli.command()
@click.option("--root", required=True, help="Data root (fsspec URL).")
@click.option("--config", "config_path", default=None,
              help=f"Physical parameters file (default: {DEFAULT_CONFIG}).")
@click.option("--date", default=None,
              help="First day to optimise, YYYY-MM-DD (default: tomorrow).")
@click.option("--days", type=int, default=1, show_default=True,
              help="Number of consecutive days to optimise.")
@click.option("--terminal-soc", type=float, default=None,
              help="End-of-day SoC target (default: initial_soc).")
@click.option("--degradation-cost", type=float, default=0.0, show_default=True,
              help="£/MWh throughput penalty discouraging over-cycling.")
def optimise(root: str, config_path: Optional[str], date: Optional[str], days: int,
             terminal_soc: Optional[float], degradation_cost: float) -> None:
    """Solve the day-ahead LP for one or more days and write dispatch schedules.

    With no --date, plans tomorrow onward (so a daily job stays a day ahead).
    """
    config = load_config(config_path or DEFAULT_CONFIG)
    first = dt.date.fromisoformat(date) if date else dt.date.today() + dt.timedelta(days=1)
    options = OptimiseOptions(terminal_soc=terminal_soc, degradation_cost=degradation_cost)
    for offset in range(days):
        day = (first + dt.timedelta(days=offset)).isoformat()
        prices, resolution = _read_prices(root, day)
        schedule = opt.optimise(config, prices, resolution, options, date=day)
        path = schedule.write(root)
        click.echo(f"Optimised {day}: objective={schedule.objective_value:.2f}  ->  {path}")


@cli.command()
@click.option("--root", required=True, help="Data root (fsspec URL).")
@click.option("--config", "config_path", default=None,
              help=f"Physical parameters file (default: {DEFAULT_CONFIG}).")
@click.option("--start", default=None,
              help="Start datetime/date (default: today). Ignored if a checkpoint exists.")
@click.option("--days", type=int, default=None,
              help="Number of sim-days to run (default: run indefinitely).")
@click.option("--time-scale", type=float, default=1.0, show_default=True,
              help="Sim-seconds per wall-second (1 = real time, large = demo).")
def run(root: str, config_path: Optional[str], start: Optional[str],
        days: Optional[int], time_scale: float) -> None:
    """Run the long-running simulator, following daily schedules."""
    config = load_config(config_path or DEFAULT_CONFIG)
    start = start or dt.date.today().isoformat()
    runner_config = RunnerConfig(root=root, time_scale=time_scale, days=days)
    summary = run_service(config, runner_config, start)
    click.echo(f"Ran {summary['days_run']} day(s), wrote "
               f"{summary['minutes_written']} minute record(s); "
               f"final SoC={summary['final_soc']:.3f}")


def _read_prices(root: str, date: str):
    """Read a day's price forecast (prices, resolution_minutes)."""
    from src.optimiser import prices as prices_module
    return prices_module.read(root, date)


if __name__ == "__main__":
    cli()
