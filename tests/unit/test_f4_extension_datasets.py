"""F4.7 / F4.8 / F4.9 (C5): the Connector posts product_overview, promotion_daily, promotions and
order_income with the file import's field names; an extension row wins over a file row of the
same key and a file post never replaces it (it only fills NULLs). order_income's own rank test is
``test_shopee_income_ingest``. Synthetic values only."""

from __future__ import annotations

from decimal import Decimal

import pytest

from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.models.platform_data import PlatformPromotion
from juli_backend.services.ingest.rate_limit import InMemoryRateGate, set_ingest_rate_gate
from tests.unit.test_shopee_file_datasets import (
    DAY,
    OCTOBER,
    _body,
    _ingest,
    _program,
    _rows,
    _shop,
)


@pytest.fixture(autouse=True)
def generous_gate():
    set_ingest_rate_gate(InMemoryRateGate())
    yield
    set_ingest_rate_gate(None)


def _as_extension(body, captured="2026-10-29T10:30:00+07:00"):
    return {**body, "source": "extension", "source_version": "0.3.29", "captured_at": captured}


async def test_product_overview_from_the_connector_replaces_the_file_row_and_keeps_it(session):
    shop = await _shop(session)
    day = DAY.isoformat()
    row = {"date": day, "product_visitors": 19, "product_page_views": 57, "atc_visitors": 7}
    await _ingest(session, shop, "product_overview", _body([row]))
    live = {**row, "product_visitors": 25}
    await _ingest(session, shop, "product_overview", _as_extension(_body([live])))
    (stored,) = await _rows(session, PlatformDailyMetric, shop)
    assert (stored.source, stored.visitors) == ("extension", Decimal("25"))
    older_file = {**row, "product_visitors": 11}
    await _ingest(
        session,
        shop,
        "product_overview",
        _body([older_file], captured_at="2026-10-29T11:30:00+07:00"),
    )
    (stored,) = await _rows(session, PlatformDailyMetric, shop)
    assert (stored.source, stored.visitors) == ("extension", Decimal("25"))


async def test_promotion_daily_from_the_connector_wins_over_the_file(session):
    shop = await _shop(session)
    row = {"date": DAY.isoformat(), "promo_type": "Tất cả", "sales": 800000, "orders": 6}
    await _ingest(session, shop, "promotion_daily", _body([row]))
    await _ingest(
        session, shop, "promotion_daily", _as_extension(_body([{**row, "sales": 900000}]))
    )
    await _ingest(
        session,
        shop,
        "promotion_daily",
        _body([{**row, "sales": 1}], captured_at="2026-10-29T11:30:00+07:00"),
    )
    (stored,) = await _rows(session, PlatformDailyMetric, shop)
    assert (stored.source, stored.gmv) == ("extension", Decimal("900000"))


async def test_promotions_from_the_connector_win_over_the_file(session):
    shop = await _shop(session)
    await _ingest(session, shop, "promotions", _body([_program()], period=OCTOBER))
    await _ingest(
        session,
        shop,
        "promotions",
        _as_extension(_body([_program(sales=950000, orders=7)], period=OCTOBER)),
    )
    await _ingest(
        session,
        shop,
        "promotions",
        _body([_program(sales=5)], period=OCTOBER, captured_at="2026-10-29T11:30:00+07:00"),
    )
    (stored,) = await _rows(session, PlatformPromotion, shop)
    assert (stored.source, stored.gmv, stored.orders) == (
        "extension",
        Decimal("950000"),
        Decimal("7"),
    )
