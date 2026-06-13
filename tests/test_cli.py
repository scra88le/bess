"""CLI input-resolution tests."""

from __future__ import annotations

import os

import click
import pytest

import main


def test_defaults_when_no_options() -> None:
    cfg, disp = main._resolve_inputs(None, None, None)
    assert cfg == main.DEFAULT_CONFIG
    assert disp == main.DEFAULT_DISPATCH


def test_explicit_paths_passthrough() -> None:
    cfg, disp = main._resolve_inputs(None, "my.yaml", "my.csv")
    assert (cfg, disp) == ("my.yaml", "my.csv")


def test_scenario_resolves_to_folder() -> None:
    cfg, disp = main._resolve_inputs("08_thermal_trip", None, None)
    assert cfg == os.path.join(main.SCENARIOS_DIR, "08_thermal_trip", "config.yaml")
    assert disp == os.path.join(main.SCENARIOS_DIR, "08_thermal_trip", "dispatch.csv")
    assert os.path.isfile(cfg) and os.path.isfile(disp)


def test_unknown_scenario_raises_with_listing() -> None:
    with pytest.raises(click.BadParameter) as exc:
        main._resolve_inputs("does_not_exist", None, None)
    # The error should list real, available scenarios to guide the user.
    assert "08_thermal_trip" in str(exc.value)


def test_scenario_conflicts_with_explicit_paths() -> None:
    with pytest.raises(click.UsageError):
        main._resolve_inputs("08_thermal_trip", "config.yaml", None)
    with pytest.raises(click.UsageError):
        main._resolve_inputs("08_thermal_trip", None, "dispatch.csv")


def test_available_scenarios_includes_known() -> None:
    names = main._available_scenarios()
    assert "01_grid_clip" in names
    assert "09_compound_hot_gridclip" in names


# --- CLI group smoke tests -------------------------------------------- #
from click.testing import CliRunner  # noqa: E402


def test_cli_exposes_subcommands() -> None:
    result = CliRunner().invoke(main.cli, ["--help"])
    assert result.exit_code == 0
    for cmd in ("simulate", "optimise", "generate-prices", "run"):
        assert cmd in result.output


def test_generate_optimise_run_end_to_end(tmp_path) -> None:
    """The three new subcommands chain through the file contract."""
    runner = CliRunner()
    root = str(tmp_path)

    r = runner.invoke(main.cli, ["generate-prices", "--root", root,
                                 "--start", "2026-06-13", "--days", "1", "--seed", "7"])
    assert r.exit_code == 0, r.output

    r = runner.invoke(main.cli, ["optimise", "--root", root,
                                 "--config", "config.yaml", "--date", "2026-06-13"])
    assert r.exit_code == 0, r.output
    assert "objective" in r.output

    r = runner.invoke(main.cli, ["run", "--root", root, "--config", "config.yaml",
                                 "--start", "2026-06-13T23:58:00", "--days", "1",
                                 "--time-scale", "1000000"])
    assert r.exit_code == 0, r.output
    assert "minute record" in r.output


def test_run_missing_schedule_errors(tmp_path) -> None:
    """Running a day with no schedule exits non-zero (no silent fallback)."""
    result = CliRunner().invoke(main.cli, ["run", "--root", str(tmp_path),
                                           "--config", "config.yaml",
                                           "--start", "2026-06-13", "--days", "1",
                                           "--time-scale", "1000000"])
    assert result.exit_code != 0
