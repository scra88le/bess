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


class ScenarioConfig(BaseModel):
    site: SiteSpec
    prices: PriceConfig
    timestep_minutes: int = Field(default=30, gt=0)
    output_dir: Path = Path("runs")
    seed: int = 0


def load_scenario(path: Path | str) -> ScenarioConfig:
    path = Path(path)
    with path.open() as f:
        raw = yaml.safe_load(f)
    return ScenarioConfig.model_validate(raw)
