"""CLI entry point for the grid-scale BESS physical model simulation."""

from __future__ import annotations

import csv
import os
from typing import List, Optional, Tuple

import click

from src.battery import Battery
from src.config_loader import load_config
from src.dispatch_engine import DispatchEngine
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


@click.command()
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
def main(scenario: Optional[str], config_path: Optional[str],
         dispatch_path: Optional[str], visualize: bool) -> None:
    """Run the BESS simulation over a dispatch signal."""
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


if __name__ == "__main__":
    main()
