from __future__ import annotations

from pathlib import Path

import typer

from . import __version__
from .config import load_scenario
from .runtime import run as run_scenario

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Grid-scale BESS arbitrage simulation runtime.",
)


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


@app.command()
def run(
    scenario: Path = typer.Argument(..., exists=True, readable=True, help="Path to scenario YAML."),
    output_dir: Path | None = typer.Option(
        None, "--output-dir", help="Override scenario.output_dir."
    ),
) -> None:
    """Run a scenario end-to-end and print a KPI summary."""
    config = load_scenario(scenario)
    if output_dir is not None:
        config = config.model_copy(update={"output_dir": output_dir})
    result = run_scenario(config)

    typer.echo(f"\nRun written to: {result.run_dir}")
    typer.echo("\nKPIs")
    typer.echo("-" * 40)
    for key, value in result.summary.items():
        if isinstance(value, float):
            typer.echo(f"  {key:<28} {value:>12,.3f}")
        else:
            typer.echo(f"  {key:<28} {value!s:>12}")


if __name__ == "__main__":
    app()
