"""E7 (formats + direction) and the pure math / window pieces of E3."""

from __future__ import annotations

from datetime import date

import pytest

from juli_backend.services.analytics_agent import fmt, mathx, windows


def test_vietnamese_number_formats() -> None:
    assert fmt.value("gmv", 8728160) == "8.728.160đ"
    assert fmt.value("margin", 0.428) == "42,8%"
    assert fmt.value("ctr", 0.0307) == "3,07%"
    assert fmt.value("roas", 3.414) == "3,41"
    assert fmt.value("orders", 1285) == "1.285"
    assert fmt.value("gmv", None) == "chưa có dữ liệu"


def test_delta_direction_up_down_flat() -> None:
    assert fmt.delta("gmv", 120, 100)["dir"] == "up"
    assert fmt.delta("gmv", 80, 100)["dir"] == "down"
    assert fmt.delta("gmv", 100, 100)["dir"] == "flat"
    assert fmt.delta("gmv", 100, 0)["dir"] == "flat"
    assert fmt.delta("gmv", 120, 100)["text_vi"] == "▲ 20,0%"
    assert fmt.delta("gmv", 80, 100)["text_vi"] == "▼ 20,0%"


def test_window_last_7d() -> None:
    w = windows.build_windows("last_7d_vs_prev_7d", date(2026, 11, 18))
    assert w.cur == (date(2026, 11, 12), date(2026, 11, 18))
    assert w.prev == (date(2026, 11, 5), date(2026, 11, 11))
    assert w.label() == "12/11–18/11 so với 05/11–11/11"


def test_window_mtd_clamps_and_flags_double_day() -> None:
    w = windows.build_windows("mtd_vs_same_days_last_month", date(2026, 3, 31))
    assert w.prev == (date(2026, 2, 1), date(2026, 2, 28))
    assert w.context == (date(2026, 2, 1), date(2026, 2, 28))
    w2 = windows.build_windows("last_7d_vs_prev_7d", date(2026, 11, 12))
    assert any(f.startswith("contains_campaign_day") and "11/11" in f for f in w2.flags)


def test_window_yesterday_same_weekday_and_unknown_default() -> None:
    w = windows.build_windows("yesterday_vs_same_weekday", date(2026, 11, 18))
    assert w.same_weekday[0] == date(2026, 11, 11) and len(w.same_weekday) == 4
    d = windows.build_windows("nonsense", date(2026, 11, 18))
    assert d.preset == "last_30d_vs_prev_30d" and "window_defaulted" in d.flags


def test_lmdi_adds_up_exactly() -> None:
    eff = mathx.lmdi(100.0, 150.0, {"a": (10, 12), "b": (10, 12.5)})
    assert sum(eff.values()) == pytest.approx(50.0)
    assert mathx.lmdi(0, 10, {"a": (1, 2)}) == {}


def test_rate_mix_adds_up_to_rate_change() -> None:
    s0 = {"x": (10.0, 100.0), "y": (30.0, 100.0)}
    s1 = {"x": (6.0, 100.0), "y": (40.0, 200.0)}
    rm = mathx.rate_mix(s0, s1)
    r0 = 40 / 200
    r1 = 46 / 300
    assert sum(v["rate"] + v["mix"] for v in rm.values()) == pytest.approx(r1 - r0)


def test_change_point_finds_the_step() -> None:
    series = [(date(2026, 11, d), 10.0 if d < 8 else 2.0) for d in range(1, 15)]
    assert mathx.change_point(series) == date(2026, 11, 8)


def test_robust_z_and_poisson() -> None:
    hist = [10.0, 11.0, 9.0, 10.0, 10.5, 9.5]
    z = mathx.robust_z(30.0, hist)
    assert z is not None and z >= 3
    assert mathx.poisson_significant(now=50, expected=100) is True
    assert mathx.poisson_significant(now=98, expected=100) is False
