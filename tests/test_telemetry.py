"""Telemetry emission and dashboard-building tests."""

from __future__ import annotations

import matplotlib
import pytest

matplotlib.use("Agg")  # headless backend for figure-building tests

from src.telemetry import Telemetry  # noqa: E402


def _row(t: float, **kw) -> dict:
    base = {
        "timestamp_s": t,
        "injected_mw": 10.0,
        "target_mw": 8.0,
        "actual_mw": 7.5,
        "grid_limit_export_mw": 45.0,
        "grid_limit_import_mw": -45.0,
        "soc": 0.5,
        "cell_temp_c": 25.0,
        "ambient_temp_c": 20.0,
        "aux_load_mw": 0.05,
        "resistive_loss_mw": 0.6,
        "cumulative_throughput_mwh": 0.1,
        "equivalent_full_cycles": 0.001,
        "capacity_loss_fraction": 0.0001,
        "warranty_breached": 0.0,
        "limit_reason": "",
    }
    base.update(kw)
    return base


def test_emit_stdout_header_and_rows(capsys) -> None:
    tel = Telemetry()
    tel.record(_row(0.0))
    tel.record(_row(1.0, limit_reason="Ramp Limit Exceeded"))
    tel.emit_stdout()

    out = capsys.readouterr().out.strip().splitlines()
    assert out[0].startswith("timestamp_s,injected_mw,target_mw,actual_mw")
    assert len(out) == 3  # header + 2 rows
    assert out[2].endswith("Ramp Limit Exceeded")


def test_emit_stdout_empty_warns(capsys) -> None:
    Telemetry().emit_stdout()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no telemetry" in captured.err


def test_column_extracts_field() -> None:
    tel = Telemetry()
    tel.record(_row(0.0, soc=0.4))
    tel.record(_row(1.0, soc=0.6))
    assert tel.column("soc") == [0.4, 0.6]


def test_build_figure_has_four_subplots() -> None:
    tel = Telemetry()
    for i in range(5):
        tel.record(_row(float(i), soc=0.5 - i * 0.05))
    fig = tel.build_figure()
    # Four stacked telemetry axes (+ one twin axis on the degradation panel).
    assert len(fig.axes) == 5
    import matplotlib.pyplot as plt
    plt.close(fig)


def test_build_figure_empty_raises() -> None:
    with pytest.raises(ValueError, match="no telemetry"):
        Telemetry().build_figure()
