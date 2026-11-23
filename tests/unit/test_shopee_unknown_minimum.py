"""Chưa đủ dữ liệu: a voucher whose minimum spend was never read is neither a "không đơn tối
thiểu" voucher nor guessed as 0 (measure.py, generators.py). Synthetic."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from juli_backend.services.shopee_recommendations import generators as gen
from juli_backend.services.shopee_recommendations import measure

CRIT: dict[str, Any] = {"kpi": "bien"}


@pytest.mark.parametrize("raw", [None, "", "abc", True, [], {}])
def test_an_unread_minimum_is_not_a_voucher_type(raw):
    assert measure.voucher_kind_of(raw) is None


def test_a_read_minimum_picks_the_type():
    assert measure.voucher_kind_of(149_000) == ("min_spend_voucher", "aov")
    assert measure.voucher_kind_of("99000") == ("min_spend_voucher", "aov")
    assert measure.voucher_kind_of(Decimal("1")) == ("min_spend_voucher", "aov")
    assert measure.voucher_kind_of(0) == ("review_voucher", "ctor")  # an explicit 0 is read


def _voucher(min_spend):
    return SimpleNamespace(
        value=Decimal(10_000), min_spend=min_spend, max_value=None, usage_limit=50, voucher_id="v1"
    )


def test_a_voucher_cap_card_is_not_made_for_a_voucher_with_an_unread_minimum():
    env: Any = SimpleNamespace(vouchers=[_voucher(None)])
    assert gen.gen_voucher_cap(env, CRIT, "p1") == []
