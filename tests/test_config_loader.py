"""Validation and loading tests for config_loader."""

from __future__ import annotations

import pytest
import yaml

from src.config_loader import Config, ConfigError, load_config

VALID = {
    "nominal_capacity_mwh": 50.0,
    "initial_soc": 0.5,
    "efficiency": 0.92,
    "ramping_limit_mw_per_sec": 2.0,
    "thermal": {
        "initial_temp_c": 25.0,
        "ambient_temp_c": 20.0,
        "thermal_mass": 15000,
        "hvac_cooling_rate_c_per_sec": 0.05,
        "optimal_temp_c": 20.0,
        "max_cell_temp_c": 60.0,
    },
    "soc_non_linearity": {
        "lower_threshold": 0.10,
        "upper_threshold": 0.90,
        "exponential_factor": 2.5,
    },
    "auxiliary_load_kw": {"base": 50.0, "hvac_per_degree": 10.0},
    "grid_constraints": {"max_export_mw": 45.0, "max_import_mw": 45.0},
    "warranty": {"max_equivalent_full_cycles": 3000},
    "degradation": {"cycle_loss_per_efc": 0.0000667, "calendar_loss_per_year": 0.02},
    "planned_outages": [[0, 10], [3600, 3700]],
}


def write(tmp_path, data) -> str:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    return str(path)


def test_loads_valid_config(tmp_path) -> None:
    cfg = load_config(write(tmp_path, VALID))
    assert isinstance(cfg, Config)
    assert cfg.nominal_capacity_mwh == 50.0
    assert cfg.efficiency == 0.92
    assert cfg.planned_outages == [(0, 10), (3600, 3700)]
    assert cfg.degradation["calendar_loss_per_year"] == 0.02


def test_repo_config_yaml_loads() -> None:
    """The shipped config.yaml must load cleanly."""
    cfg = load_config("config.yaml")
    assert cfg.nominal_capacity_mwh > 0


def test_missing_file_raises() -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config("/no/such/config.yaml")


def test_malformed_yaml_raises(tmp_path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("nominal_capacity_mwh: 50.0\n  bad: : indent")
    with pytest.raises(ConfigError, match="Invalid YAML"):
        load_config(str(path))


def test_missing_required_key_raises(tmp_path) -> None:
    data = {k: v for k, v in VALID.items() if k != "efficiency"}
    with pytest.raises(ConfigError, match="efficiency"):
        load_config(write(tmp_path, data))


def test_missing_nested_key_raises(tmp_path) -> None:
    data = {
        **VALID,
        "thermal": {k: v for k, v in VALID["thermal"].items() if k != "thermal_mass"},
    }
    with pytest.raises(ConfigError, match="thermal.thermal_mass"):
        load_config(write(tmp_path, data))


@pytest.mark.parametrize(
    "overrides, match",
    [
        ({"efficiency": 0.0}, "efficiency"),
        ({"efficiency": 1.5}, "efficiency"),
        ({"nominal_capacity_mwh": 0.0}, "nominal_capacity_mwh"),
        ({"initial_soc": 1.2}, "initial_soc"),
        ({"initial_soc": -0.1}, "initial_soc"),
        ({"ramping_limit_mw_per_sec": -1.0}, "ramping_limit"),
    ],
)
def test_out_of_range_scalars_raise(tmp_path, overrides, match) -> None:
    data = {**VALID, **overrides}
    with pytest.raises(ConfigError, match=match):
        load_config(write(tmp_path, data))


def test_threshold_ordering_enforced(tmp_path) -> None:
    data = {
        **VALID,
        "soc_non_linearity": {
            "lower_threshold": 0.9,
            "upper_threshold": 0.1,
            "exponential_factor": 2.5,
        },
    }
    with pytest.raises(ConfigError, match="lower_threshold must be < upper_threshold"):
        load_config(write(tmp_path, data))


def test_non_numeric_value_raises(tmp_path) -> None:
    data = {**VALID, "efficiency": "high"}
    with pytest.raises(ConfigError, match="must be a number"):
        load_config(write(tmp_path, data))


@pytest.mark.parametrize(
    "outages",
    [
        [[10, 5]],  # start > end
        [[-1, 5]],  # negative offset
        [[1, 2, 3]],  # wrong arity
        [[1.5, 2.0]],  # non-integer seconds
        "not-a-list",
    ],
)
def test_invalid_outages_raise(tmp_path, outages) -> None:
    data = {**VALID, "planned_outages": outages}
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, data))


def test_empty_file_raises(tmp_path) -> None:
    path = tmp_path / "empty.yaml"
    path.write_text("")
    with pytest.raises(ConfigError, match="must be a mapping"):
        load_config(str(path))
