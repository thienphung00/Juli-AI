"""R1 owner decision #102 (4c): a combo line posted by the Connector (promo_kind bundle, source
extension) has a deal_price that is already its share of the combo price; its bundle_discount is
information and is not taken off again. File-import lines keep subtracting. Synthetic data."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from juli_backend.services.ingest.canonical import OrderLine as CanonicalLine
from juli_backend.services.shopee_analytics.catalog import RawItem, build_catalog
from juli_backend.services.shopee_analytics.engine import to_shop_lines
from juli_backend.services.shopee_profit.order_profit import (
    OrderLine,
    OrderStatus,
    PromoKind,
    SkuCost,
    line_profit,
)
from tests.unit.test_shopee_analytics_pure import _raw

D = Decimal


def _line(*, in_price: bool) -> OrderLine:
    return OrderLine(
        order_id="o1",
        sku="S",
        product_id="P",
        order_date=date(2026, 11, 4),
        qty=1,
        original_price=D(100_000),
        deal_price=D(95_000),
        bundle_discount=D(5_000),
        promo_kind=PromoKind.NONE,
        status=OrderStatus.DELIVERED,
        combo_in_price=in_price,
    )


def test_a_connector_combo_line_is_not_discounted_twice():
    # a combo of 2 x 95.000 (page list 100.000, 5.000 off each): Shopee settled goods 190.000
    lines = [_line(in_price=True), _line(in_price=True)]
    assert sum((ln.buyer_paid for ln in lines), D(0)) == D(190_000)
    assert lines[0].item_after_seller_promo == D(95_000)
    pb = line_profit(lines[0], SkuCost("S", D(40_000), D(0)))
    assert pb.buyer_paid == D(95_000)
    assert pb.bundle == D(5_000) and pb.promo_discount == D(0)
    assert pb.offer_cost == D(5_000)  # the combo discount once, not as promo AND combo


def test_a_file_line_still_takes_its_combo_discount_off():
    ln = _line(in_price=False)
    assert ln.buyer_paid == D(90_000)
    pb = line_profit(ln, SkuCost("S", D(40_000), D(0)))
    assert pb.promo_discount == D(5_000) and pb.bundle == D(5_000)


def test_the_canonical_line_follows_its_source():
    def canon(source: str) -> CanonicalLine:
        return CanonicalLine(
            shop_id=__import__("uuid").uuid4(),
            platform="shopee",
            order_ref="o1",
            line_no=0,
            ordered_at=datetime(2026, 11, 4, 10),
            status="delivered",
            item_id="P",
            variation_id="",
            qty=1,
            original_price=D(100_000),
            deal_price=D(95_000),
            bundle_discount=D(5_000),
            promo_kind="bundle",
            source=source,
            source_version="t",
        )

    assert canon("extension").buyer_paid == D(95_000)
    assert canon("file").buyer_paid == D(90_000)


def test_the_engine_marks_only_connector_combo_lines():
    catalog = build_catalog([RawItem("11", "", "Găng", None, "G1", None)])
    kw = dict(promo_kind="bundle", bundle_discount=D(5_000), deal_price=D(95_000))
    lines = to_shop_lines(
        [
            _raw(1, source="extension", **kw),
            _raw(2, source="file", **kw),
            _raw(3, source="extension"),
        ],
        catalog,
    )
    assert [sl.line.combo_in_price for sl in lines] == [True, False, False]


def test_a_collapsed_combo_does_not_put_the_order_discount_on_every_line():
    import uuid

    from juli_backend.models.shopee_profit import ShopeeOrderLine
    from juli_backend.repositories.combo_lines import from_settlement

    def row(line_no: int, qty: int, deal: str, bundle: str) -> ShopeeOrderLine:
        return ShopeeOrderLine(
            shop_id=uuid.uuid4(),
            platform="shopee",
            order_ref="o1",
            line_no=line_no,
            qty=qty,
            item_id="P",
            original_price=D(100_000),
            deal_price=D(deal),
            seller_subsidy=D(0),
            bundle_discount=D(bundle),
            promo_kind="bundle",
            source="extension",
        )

    parent = row(0, 1, "190000", "0")  # the collapsed line: the whole combo price
    sibling = row(1, 1, "95000", "5000")
    got = from_settlement([parent, sibling], parent, D(190_000))
    assert got is not None and got.qty == 1 and got.deal_price == D(95_000)
    assert got.bundle_discount == D(5_000)  # its own 5.000, not the order's 10.000
