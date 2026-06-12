"""CLI entry point for the grid-scale BESS physical model simulation."""

from __future__ import annotations

import csv
from typing import List

import click

from src.battery import Battery
from src.config_loader import load_config
from src.dispatch_engine import DispatchEngine
from src.telemetry import Telemetry


def _load_dispatch(path: str) -> List[float]:
    """Read a 1-second-resolution dispatch CSV into a list of MW setpoints."""
    dispatch: List[float] = []
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            dispatch.append(float(row["dispatch_mw"]))
    return dispatch


@click.command()
@click.option("--config", "config_path", default="config.yaml",
              help="Path to the physical parameters configuration file.")
@click.option("--dispatch", "dispatch_path", default="dispatch.csv",
              help="Path to the time-series dispatch signal (1s resolution).")
@click.option("--visualize", is_flag=True,
              help="Open a live matplotlib dashboard during the run.")
def main(config_path: str, dispatch_path: str, visualize: bool) -> None:
    """Run the BESS simulation over a dispatch signal."""
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
