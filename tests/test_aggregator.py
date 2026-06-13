"""Tests for the 1-minute telemetry aggregator."""

from __future__ import annotations

from src.runtime.aggregator import MinuteAggregator


def _row(actual_mw, *, soc=0.5, temp=25.0, target=None, reason="",
         efc=0.0, loss=0.0, throughput=0.0, warranty=0.0, aux=0.05, rloss=0.0):
    return {
        "actual_mw": actual_mw,
        "target_mw": actual_mw if target is None else target,
        "soc": soc,
        "cell_temp_c": temp,
        "aux_load_mw": aux,
        "resistive_loss_mw": rloss,
        "equivalent_full_cycles": efc,
        "capacity_loss_fraction": loss,
        "cumulative_throughput_mwh": throughput,
        "warranty_breached": warranty,
        "limit_reason": reason,
    }


def test_energy_sums_and_end_of_minute_values() -> None:
    agg = MinuteAggregator()
    # 30 s discharging at 36 MW, 30 s charging at 36 MW.
    for _ in range(30):
        agg.add(_row(36.0, soc=0.6, temp=30.0))
    for _ in range(30):
        agg.add(_row(-36.0, soc=0.55, temp=29.0))
    rec = agg.flush("2026-06-13", 5, "2026-06-13T00:05:00")

    assert rec["date"] == "2026-06-13"
    assert rec["minute_index"] == 5
    assert rec["mwh_discharged"] == 36.0 * 30 / 3600.0   # 0.30
    assert rec["mwh_charged"] == 36.0 * 30 / 3600.0
    assert rec["mean_power_mw"] == 0.0
    assert rec["peak_discharge_mw"] == 36.0
    assert rec["peak_charge_mw"] == 36.0
    assert rec["soc_end"] == 0.55                        # last row
    assert rec["cell_temp_c_end"] == 29.0
    assert agg.is_empty()                                # reset after flush


def test_violation_counts_by_reason() -> None:
    agg = MinuteAggregator()
    agg.add(_row(10.0, reason="Ramp Limit Exceeded"))
    agg.add(_row(10.0, reason="Ramp Limit Exceeded"))
    agg.add(_row(0.0, reason="Thermal Trip"))
    agg.add(_row(5.0, reason="Mystery Reason"))
    agg.add(_row(5.0, reason=""))
    rec = agg.flush("2026-06-13", 0, "2026-06-13T00:00:00")
    assert rec["violations_ramp_limit"] == 2
    assert rec["violations_thermal_trip"] == 1
    assert rec["violations_other"] == 1
    assert rec["violations_grid_constrained"] == 0


def test_warranty_sticky() -> None:
    agg = MinuteAggregator()
    agg.add(_row(1.0, warranty=0.0))
    agg.add(_row(1.0, warranty=1.0))
    agg.add(_row(1.0, warranty=0.0))
    rec = agg.flush("2026-06-13", 0, "2026-06-13T00:00:00")
    assert rec["warranty_breached"] == 1.0


def test_monotonic_counters_take_end_value() -> None:
    agg = MinuteAggregator()
    agg.add(_row(1.0, efc=0.1, loss=0.001, throughput=5.0))
    agg.add(_row(1.0, efc=0.2, loss=0.002, throughput=10.0))
    rec = agg.flush("2026-06-13", 0, "2026-06-13T00:00:00")
    assert rec["equivalent_full_cycles_end"] == 0.2
    assert rec["capacity_loss_fraction_end"] == 0.002
    assert rec["cumulative_throughput_mwh_end"] == 10.0
