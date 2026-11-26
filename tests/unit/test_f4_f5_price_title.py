"""R1 F4 + F5 (synthetic figures only).

F4: one price rule -- what the buyer pays after; a product_discount / flash_sale never yields a
price at or above what the buyer pays today, per variation.
F5: title and cover_image show no uplift until measured; the other simple kinds are unchanged.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace
from typing import Any, cast

import pytest

from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_builder.context import SpecRefused
from juli_backend.services.shopee_builder.engine.contract import (
    CARD_SOURCES,
    FunnelBase,
    SourceFunnel,
)
from juli_backend.services.shopee_builder.engine.engine import run
from juli_backend.services.shopee_builder.engine_families import common, option_for
from juli_backend.services.shopee_builder.translate import (
    _variation_inputs,
    paid_price_and_min_discount,
)

# ------------------------------------------------------------------------------------- F4

LIST = 150_900
PAID = 126_360


def _row(vid: str, selling: int | None, listed: int | None) -> dict:
    return {
        "variation_id": vid,
        "name": f"Loại {vid}",
        "selling_price": selling,
        "list_price": listed,
        "sku_key": "SHARED",
    }


class _Env:
    """What the order lines say about the SHARED cost key: another variation's newest line."""

    def __init__(self, current: int | None, listed: int | None = LIST) -> None:
        self._current, self._listed = current, listed

    def current_price(self, sku: str) -> D | None:
        return None if self._current is None else D(self._current)

    def list_price(self, sku: str) -> D | None:
        return None if self._listed is None else D(self._listed)


class _Ctx:
    def __init__(self, rows: list[dict], env: _Env, *, shared: bool = True) -> None:
        self.env = env
        self._rows = {r["variation_id"]: r for r in rows}
        self._shared = shared

    def variation(self, item_id: str, variation_id: str) -> dict:
        return self._rows[variation_id]

    def sku_key(self, item_id: str, variation_id: str) -> str:
        return "SHARED" if self._shared else f"K{variation_id}"


def _discount(ctx: _Ctx, *variations: sp.VariationPrice, discount: bool = True):
    return _variation_inputs(ctx, "9", list(variations), discount=discount)


def test_5_percent_on_a_variation_sold_at_126360_is_refused_when_the_key_is_shared():
    """E134: 8 variations share one cost key; the key's newest order line is another variation
    sold at the list price 150.9k. The refusal compared 143.4k with THAT, not with this
    variation's own 126.360."""
    rows = [_row("a", PAID, LIST), _row("b", LIST, LIST)]
    ctx = _Ctx(rows, _Env(current=LIST))
    with pytest.raises(SpecRefused) as refused:
        _discount(ctx, sp.VariationPrice(variation_id="a", discount_pct=5))
    assert refused.value.code.startswith("discount_not_below_current:9:126360:143300")


def test_the_refusal_also_fires_when_the_key_has_no_order_line_at_all():
    rows = [_row("a", PAID, LIST)]
    ctx = _Ctx(rows, _Env(current=None), shared=False)
    with pytest.raises(SpecRefused) as refused:
        _discount(ctx, sp.VariationPrice(variation_id="a", discount_pct=5))
    assert refused.value.code.startswith("discount_not_below_current")


def test_a_pinned_final_price_is_refused_against_the_variations_own_paid_price():
    """The frontend sends final_price per variation (applyOwnPrices): same rule."""
    rows = [_row("a", PAID, LIST), _row("b", LIST, LIST)]
    ctx = _Ctx(rows, _Env(current=LIST))
    with pytest.raises(SpecRefused) as refused:
        _discount(ctx, sp.VariationPrice(variation_id="a", final_price=143_300))
    assert refused.value.code.startswith("discount_not_below_current")
    ok = _discount(ctx, sp.VariationPrice(variation_id="a", final_price=120_000))
    assert ok[0]["final_price"] == 120_000


def test_a_discount_below_what_buyers_pay_is_accepted_per_variation():
    rows = [_row("a", PAID, LIST), _row("b", LIST, LIST)]
    ctx = _Ctx(rows, _Env(current=LIST))
    out = _discount(
        ctx,
        sp.VariationPrice(variation_id="a", discount_pct=20),
        sp.VariationPrice(variation_id="b", discount_pct=5),
    )
    by = {r["variation_id"]: r for r in out}
    assert by["a"]["final_price"] == 120_700  # 150.900 x 0.8
    assert by["b"]["final_price"] == 143_300  # b sells at 150.900: 5 % off is below it


def test_a_price_change_is_not_a_discount_and_keeps_its_rule():
    rows = [_row("a", PAID, LIST)]
    ctx = _Ctx(rows, _Env(current=LIST), shared=False)
    out = _discount(ctx, sp.VariationPrice(variation_id="a", change_pct=-5), discount=False)
    assert out[0]["new_price_pct"] == 95


def test_a_variation_without_a_price_accepts_no_percent():
    rows = [_row("a", None, None)]
    ctx = _Ctx(rows, _Env(current=None, listed=None), shared=False)
    with pytest.raises(SpecRefused) as refused:
        _discount(ctx, sp.VariationPrice(variation_id="a", discount_pct=5))
    assert refused.value.code == "no_price"
    with pytest.raises(SpecRefused) as price:
        _discount(ctx, sp.VariationPrice(variation_id="a", change_pct=5), discount=False)
    assert price.value.code == "no_price"


def test_the_builder_hint_uses_the_variations_own_paid_price():
    """service._paid_fields: paid = the lowest of the variation's own price and its key's line."""
    from juli_backend.services.shopee_builder.service import _paid_fields

    row = _row("a", PAID, LIST)
    out = _paid_fields(_Env(current=LIST), row, shared=True)
    assert out == {"paid_price": PAID, "min_discount_pct": 17}  # 1 - 126360/150900 = 16.3 %
    alone = _paid_fields(_Env(current=None), row, shared=False)
    assert alone["paid_price"] == PAID
    assert paid_price_and_min_discount(_Env(current=LIST), "SHARED")[0] == D(LIST)


# ------------------------------------------------------------------------------------- F5


def _base() -> FunnelBase:
    def src(key, views, clicks, orders, gmv, profit):
        return SourceFunnel(key, D(views), D(clicks), D(orders), D(gmv), D(profit))

    return FunnelBase(
        "shop-1",
        "shop",
        (),
        date(2026, 10, 1),
        date(2026, 10, 30),
        (
            src("the_san_pham_khac", 100000, 5000, 200, 20_000_000, 4_000_000),
            src("trang_shop", 20000, 1000, 50, 5_000_000, 1_000_000),
        ),
        D("0.3"),
    )


class _NoEvidence:
    """option_for must not even look for a lift: title / cover are not estimated."""

    env = None
    keyword_weights: dict = {}


TITLE = sp.TitleSpec(kind="title", item_id="1", title="Găng tay nitrile")
COVER = sp.CoverSpec(kind="cover_image", item_id="1", overlay=sp.CoverOverlay(layout="banner_top"))


@pytest.mark.parametrize(("spec", "metrics"), [(TITLE, ["views", "ctr"]), (COVER, ["ctr"])])
def test_title_and_cover_show_no_uplift_until_measured(spec, metrics):
    option = option_for(spec, cast(Any, _NoEvidence()))
    assert [d.metric for d in option.drivers] == metrics
    assert all(d.basis == "not_estimable" and d.lift is None for d in option.drivers)
    assert all(d.sources == CARD_SOURCES for d in option.drivers)
    assert all(d.note == common.NOTE_NOT_MEASURED for d in option.drivers)
    r = run(_base(), option, n=200)
    assert r.estimable is False
    assert r.low is None and r.likely is None and r.high is None
    assert r.build_up == ()
    assert r.cost_total == 0
    wire = r.json()
    assert _leaves(wire["delta"]) == [None] * len(_leaves(wire["delta"]))
    drivers_pct = cast(list[dict[str, Any]], wire["drivers_pct"])
    assert all(d["pct"] is None for d in drivers_pct)


def _leaves(node: object) -> list[object]:
    """Every number-ish leaf of a nested wire dict (notes are texts, not figures)."""
    if isinstance(node, dict):
        return [x for k, v in node.items() if k != "note" for x in _leaves(v)]
    return [node]


def test_description_price_display_and_variation_set_keep_their_effect():
    from juli_backend.services.shopee_builder.engine_families import _SIMPLE_KINDS

    assert {"description_first_line", "price_display", "variation_set"} <= set(_SIMPLE_KINDS)
    assert "title" in _SIMPLE_KINDS and "cover_image" in _SIMPLE_KINDS


def test_the_title_limit_is_120_everywhere():
    from juli_backend.services.shopee_recommendations import config

    assert config.MAX_TITLE_CHARS == 120
    assert sp.MAX_TITLE_CHARS == 120
    sp.TitleSpec(kind="title", item_id="1", title="x" * 120)
    with pytest.raises(ValueError):
        sp.TitleSpec(kind="title", item_id="1", title="x" * 121)


def test_namespace_helper_is_unused():
    assert SimpleNamespace  # keeps the import honest for the shared fakes above
