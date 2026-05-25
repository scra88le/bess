from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, Field


class SiteSpec(BaseModel):
    power_mw: float = Field(gt=0)
    energy_mwh: float = Field(gt=0)
    eta_charge: float = Field(gt=0, le=1)
    eta_discharge: float = Field(gt=0, le=1)
    soc_min_frac: float = Field(default=0.0, ge=0, le=1)
    soc_max_frac: float = Field(default=1.0, ge=0, le=1)
    soc_initial_frac: float = Field(default=0.5, ge=0, le=1)


class CsvPriceConfig(BaseModel):
    kind: Literal["csv"] = "csv"
    path: Path
    timestamp_column: str = "timestamp"
    price_column: str = "price"


class SyntheticPriceConfig(BaseModel):
    kind: Literal["synthetic"] = "synthetic"
    days: int = Field(gt=0)
    peak_price: float = 120.0
    trough_price: float = 20.0
    start: str = "2025-01-01"


PriceConfig = Annotated[
    CsvPriceConfig | SyntheticPriceConfig,
    Field(discriminator="kind"),
]


class DcLowServiceConfig(BaseModel):
    kind: Literal["dc_low"] = "dc_low"
    path: Path
    timestamp_column: str = "timestamp"
    price_column: str = "price"
    response_minutes: int = Field(default=15, gt=0)


class DcHighServiceConfig(BaseModel):
    kind: Literal["dc_high"] = "dc_high"
    path: Path
    timestamp_column: str = "timestamp"
    price_column: str = "price"
    response_minutes: int = Field(default=15, gt=0)


ServiceConfig = Annotated[
    DcLowServiceConfig | DcHighServiceConfig,
    Field(discriminator="kind"),
]


class EfaConfig(BaseModel):
    block_hours: int = Field(default=4, gt=0)
    block_start_hour: int = Field(default=23, ge=0, lt=24)


class ScenarioConfig(BaseModel):
    site: SiteSpec
    prices: PriceConfig
    timestep_minutes: int = Field(default=30, gt=0)
    output_dir: Path = Path("runs")
    seed: int = 0
    services: list[ServiceConfig] = Field(default_factory=list)
    efa: EfaConfig = Field(default_factory=EfaConfig)


def load_scenario(path: Path | str) -> ScenarioConfig:
    path = Path(path)
    with path.open() as f:
        raw = yaml.safe_load(f)
    return ScenarioConfig.model_validate(raw)
