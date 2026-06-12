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


def load_config(path: str) -> Config:
    """Load and validate a YAML configuration file.

    Raises:
        ConfigError: if the file cannot be read, required keys are missing,
            or any value is physically impossible.
    """
    raise NotImplementedError


def _validate(raw: Dict[str, Any]) -> None:
    """Validate raw config values, raising ConfigError on any impossibility."""
    raise NotImplementedError
