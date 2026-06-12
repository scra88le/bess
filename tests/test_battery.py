"""Physics & state boundary tests for the Battery model."""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="scaffold: implement once Battery.step is complete")
def test_soc_stays_within_bounds() -> None:
    """SoC must never exceed [0, 1] regardless of dispatch."""
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: implement once Battery.step is complete")
def test_efficiency_applied_per_direction() -> None:
    """Charge multiplies by efficiency; discharge divides by it."""
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: implement once Battery.step is complete")
def test_nonlinear_resistance_near_extremes() -> None:
    """Charge acceptance / discharge capability falls near 0% and 100% SoC."""
    raise NotImplementedError
