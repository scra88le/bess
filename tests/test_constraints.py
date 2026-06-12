"""Ramping, thermal, and degradation edge-case tests."""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="scaffold: implement once DispatchEngine.run is complete")
def test_ramp_limit_enforced() -> None:
    """Step changes in power must not exceed ramping_limit_mw_per_sec."""
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: implement once DispatchEngine.run is complete")
def test_grid_export_import_clipped() -> None:
    """Actual power is hard-clipped to grid max export/import."""
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: implement once DispatchEngine.run is complete")
def test_planned_outage_masks_dispatch() -> None:
    """Dispatch is forced to 0 MW during a maintenance window."""
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: implement once config validation is complete")
def test_negative_efficiency_raises() -> None:
    """A physically impossible parameter raises ConfigError at startup."""
    raise NotImplementedError
