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
