"""Forecast orders are whole numbers on every Shopee screen (vn and wire formatters)."""

from __future__ import annotations

from juli_backend.services.shopee_builder.engine.vn import count, signed_orders, vnd
from juli_backend.services.shopee_builder.engine.wire import round_count


def test_count_is_whole_orders() -> None:
    assert count(12.0) == "12"
    assert count(1.4) == "1"
    assert count(1.5) == "2"
    assert count(9.6) == "10"
    assert count(1234) == "1.234"
    assert count(-3.2) == "3"


def test_count_under_one_order() -> None:
    assert count(0.4) == "< 1"
    assert count(-0.9) == "< 1"
    assert count(0) == "0"


def test_signed_orders_forms() -> None:
    assert signed_orders(3.2) == "+3 đơn"
    assert signed_orders(-3.2) == "−3 đơn"
    assert signed_orders(0.4) == "< 1 đơn"
    assert signed_orders(-0.4) == "< 1 đơn"
    assert signed_orders(0) == "0 đơn"


def test_build_up_text_shape() -> None:
    assert f"{signed_orders(0.4)} × {vnd(65000)}" == "< 1 đơn × 65.000đ"
    assert f"{signed_orders(1.4)} × {vnd(65000)}" == "+1 đơn × 65.000đ"


def test_round_count_whole_from_one_keeps_sub_one() -> None:
    assert round_count(None) is None
    assert round_count(7.6638) == 8.0
    assert round_count(-7.6638) == -8.0
    assert round_count(1.4) == 1.0
    assert round_count(0.4321) == 0.43
