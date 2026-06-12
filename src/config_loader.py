"""Loading and validation of physical parameters.

Uncaught boundary parameters or physical impossibilities (e.g. negative
efficiency) must raise an explicit runtime configuration exception at startup.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

import yaml


class ConfigError(RuntimeError):
    """Raised when the configuration is missing, malformed, or physically impossible."""


@dataclass
class Config:
    """Validated physical configuration for the BESS simulation."""

    nominal_capacity_mwh: float
    initial_soc: float
    efficiency: float
    ramping_limit_mw_per_sec: float
    thermal: Dict[str, float]
    soc_non_linearity: Dict[str, float]
    auxiliary_load_kw: Dict[str, float]
    grid_constraints: Dict[str, float]
    warranty: Dict[str, float]
    planned_outages: List[Tuple[int, int]] = field(default_factory=list)
    degradation: Dict[str, float] = field(default_factory=dict)


# Required nested keys per section. Optional keys (thermal.optimal_temp_c,
# thermal.max_cell_temp_c, degradation.*) are validated only when present.
_REQUIRED_SECTIONS: Dict[str, Tuple[str, ...]] = {
    "thermal": ("initial_temp_c", "ambient_temp_c", "thermal_mass",
                "hvac_cooling_rate_c_per_sec"),
    "soc_non_linearity": ("lower_threshold", "upper_threshold", "exponential_factor"),
    "auxiliary_load_kw": ("base", "hvac_per_degree"),
    "grid_constraints": ("max_export_mw", "max_import_mw"),
    "warranty": ("max_equivalent_full_cycles",),
}
_REQUIRED_SCALARS: Tuple[str, ...] = (
    "nominal_capacity_mwh", "initial_soc", "efficiency", "ramping_limit_mw_per_sec",
)


def load_config(path: str) -> Config:
    """Load and validate a YAML configuration file.

    Raises:
        ConfigError: if the file cannot be read, parsed, is missing required
            keys, or holds any physically impossible value.
    """
    try:
        with open(path, "r") as fh:
            raw = yaml.safe_load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration file not found: {path}") from exc
    except OSError as exc:
        raise ConfigError(f"Could not read configuration file {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"Configuration in {path} must be a mapping, got {type(raw).__name__}")

    _validate(raw)

    return Config(
        nominal_capacity_mwh=float(raw["nominal_capacity_mwh"]),
        initial_soc=float(raw["initial_soc"]),
        efficiency=float(raw["efficiency"]),
        ramping_limit_mw_per_sec=float(raw["ramping_limit_mw_per_sec"]),
        thermal=dict(raw["thermal"]),
        soc_non_linearity=dict(raw["soc_non_linearity"]),
        auxiliary_load_kw=dict(raw["auxiliary_load_kw"]),
        grid_constraints=dict(raw["grid_constraints"]),
        warranty=dict(raw["warranty"]),
        planned_outages=_parse_outages(raw.get("planned_outages", [])),
        degradation=dict(raw.get("degradation", {}) or {}),
    )


def _validate(raw: Dict[str, Any]) -> None:
    """Validate raw config values, raising ConfigError on any impossibility."""
    # Presence: required scalars and sections.
    for key in _REQUIRED_SCALARS:
        if key not in raw:
            raise ConfigError(f"Missing required key: {key}")
    for section, keys in _REQUIRED_SECTIONS.items():
        block = raw.get(section)
        if not isinstance(block, dict):
            raise ConfigError(f"Missing or invalid section: {section}")
        for key in keys:
            if key not in block:
                raise ConfigError(f"Missing required key: {section}.{key}")

    # Physical bounds.
    _positive(raw, "nominal_capacity_mwh")
    _in_range(raw, "initial_soc", 0.0, 1.0)
    _in_range(raw, "efficiency", 0.0, 1.0, lo_inclusive=False)
    _positive(raw, "ramping_limit_mw_per_sec")

    thermal = raw["thermal"]
    _positive(thermal, "thermal_mass", "thermal")
    _non_negative(thermal, "hvac_cooling_rate_c_per_sec", "thermal")
    _is_number(thermal, "initial_temp_c", "thermal")
    _is_number(thermal, "ambient_temp_c", "thermal")
    if "optimal_temp_c" in thermal:
        _is_number(thermal, "optimal_temp_c", "thermal")
    if "max_cell_temp_c" in thermal:
        _is_number(thermal, "max_cell_temp_c", "thermal")

    nl = raw["soc_non_linearity"]
    _in_range(nl, "lower_threshold", 0.0, 1.0, "soc_non_linearity")
    _in_range(nl, "upper_threshold", 0.0, 1.0, "soc_non_linearity")
    _non_negative(nl, "exponential_factor", "soc_non_linearity")
    if nl["lower_threshold"] >= nl["upper_threshold"]:
        raise ConfigError(
            "soc_non_linearity.lower_threshold must be < upper_threshold "
            f"(got {nl['lower_threshold']} >= {nl['upper_threshold']})"
        )

    aux = raw["auxiliary_load_kw"]
    _non_negative(aux, "base", "auxiliary_load_kw")
    _non_negative(aux, "hvac_per_degree", "auxiliary_load_kw")

    grid = raw["grid_constraints"]
    _non_negative(grid, "max_export_mw", "grid_constraints")
    _non_negative(grid, "max_import_mw", "grid_constraints")

    _positive(raw["warranty"], "max_equivalent_full_cycles", "warranty")

    deg = raw.get("degradation")
    if deg is not None:
        if not isinstance(deg, dict):
            raise ConfigError("degradation must be a mapping")
        for key in ("cycle_loss_per_efc", "calendar_loss_per_year"):
            if key in deg:
                _non_negative(deg, key, "degradation")


# --------------------------------------------------------------------- #
# Validation primitives
# --------------------------------------------------------------------- #
def _qualify(key: str, section: str = "") -> str:
    return f"{section}.{key}" if section else key


def _number(block: Dict[str, Any], key: str, section: str) -> float:
    value = block[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{_qualify(key, section)} must be a number, got {value!r}")
    return float(value)


def _is_number(block: Dict[str, Any], key: str, section: str = "") -> float:
    return _number(block, key, section)


def _positive(block: Dict[str, Any], key: str, section: str = "") -> None:
    if _number(block, key, section) <= 0.0:
        raise ConfigError(f"{_qualify(key, section)} must be > 0, got {block[key]}")


def _non_negative(block: Dict[str, Any], key: str, section: str = "") -> None:
    if _number(block, key, section) < 0.0:
        raise ConfigError(f"{_qualify(key, section)} must be >= 0, got {block[key]}")


def _in_range(block: Dict[str, Any], key: str, lo: float, hi: float,
             section: str = "", lo_inclusive: bool = True) -> None:
    value = _number(block, key, section)
    low_ok = value >= lo if lo_inclusive else value > lo
    if not (low_ok and value <= hi):
        bound = "[" if lo_inclusive else "("
        raise ConfigError(
            f"{_qualify(key, section)} must be in {bound}{lo}, {hi}], got {block[key]}"
        )


def _parse_outages(raw_outages: Any) -> List[Tuple[int, int]]:
    """Validate and normalise planned-outage windows into (start, end) tuples."""
    if raw_outages is None:
        return []
    if not isinstance(raw_outages, list):
        raise ConfigError("planned_outages must be a list of [start, end] windows")

    windows: List[Tuple[int, int]] = []
    for i, window in enumerate(raw_outages):
        if not isinstance(window, (list, tuple)) or len(window) != 2:
            raise ConfigError(
                f"planned_outages[{i}] must be a [start, end] pair, got {window!r}"
            )
        start, end = window
        for label, val in (("start", start), ("end", end)):
            if isinstance(val, bool) or not isinstance(val, int):
                raise ConfigError(
                    f"planned_outages[{i}] {label} must be an integer second, got {val!r}"
                )
        if start < 0 or end < 0:
            raise ConfigError(f"planned_outages[{i}] offsets must be >= 0, got {window!r}")
        if start > end:
            raise ConfigError(f"planned_outages[{i}] start must be <= end, got {window!r}")
        windows.append((int(start), int(end)))
    return windows
