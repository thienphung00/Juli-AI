"""P92 B-8 / B-9: the answers of the seller's four Ops pages, from the real serializers.

The Demo web parses these answers (Từ khóa, Đơn hàng, Sản phẩm + luồng, Quảng cáo + khuyến mãi).
Hand-written stubs hid mismatches before, so the web tests read
``apps/demo/src/components/ops/__tests__/fixtures/p92-real-responses.json``. THIS test regenerates
the same bodies through the real routes on real Postgres (the dashboards use ``date_trunc`` /
``jsonb_typeof``) from the synthetic seller shop and fails if the committed file differs. After a
deliberate change of an answer: ``JULI_WRITE_FIXTURES=1 pytest <this file>`` and commit the file.

Also here, because it needs the same substrate: a seller reads only their own shop (a second
shop's rows never enter any of the answers) and no buyer data is in any answer.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.core.config.runtime import async_database_url
from juli_backend.models.market import MarketKeywordMetric
from juli_backend.models.shop_keywords import ShopKeywordSeed
from tests.support.api import authenticate, build_app, client_for
from tests.support.postgres import requires_postgres
from tests.support.shopee_analytics import CUR_END, NOW, seed_shopee_shop

pytestmark = [requires_postgres]

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "apps/demo/src/components/ops/__tests__/fixtures/p92-real-responses.json"
DEMO = "/v1/demo/shopee"
D1, D2 = date(2026, 10, 27), date(2026, 11, 3)
PROMO_FROM = (CUR_END - timedelta(days=29)).isoformat()


@asynccontextmanager
async def pg_session():
    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    conn = await engine.connect()
    outer = await conn.begin()
    session = AsyncSession(
        bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    try:
        yield session
    finally:
        await session.close()
        await outer.rollback()
        await conn.close()
        await engine.dispose()


def _seed_keywords(shop_id: uuid.UUID) -> list[object]:
    def seed(keyword: str, items: list[str], pattern: str = "type_function") -> ShopKeywordSeed:
        return ShopKeywordSeed(
            id=uuid.uuid5(uuid.NAMESPACE_URL, f"seed/{keyword}"),
            shop_id=shop_id,
            platform="shopee",
            keyword=keyword,
            pattern=pattern,
            item_ids=items,
            enabled=True,
            created_at=NOW,
            updated_at=NOW,
        )

    def metric(
        keyword: str, seed_kw: str, day: date, status: str = "ok", volume: int | None = None
    ) -> MarketKeywordMetric:
        return MarketKeywordMetric(
            id=uuid.uuid5(uuid.NAMESPACE_URL, f"metric/{keyword}/{seed_kw}/{day}"),
            platform="shopee",
            source="shopeeanalytics",
            keyword=keyword,
            seed=seed_kw,
            collected_on=day,
            status=status,
            volume=volume,
            cpc_min=400 if status == "ok" else None,
            cpc_max=2200 if status == "ok" else None,
            difficulty=56 if status == "ok" else None,
            extra={},
        )

    return [
        seed("găng tay tự hủy", ["1001"]),
        seed("nước rửa chén", ["1002"]),
        seed("túi rác sinh học", ["1003"], "brand_type"),
        metric("găng tay tự hủy", "găng tay tự hủy", D1, volume=250),
        metric("găng tay tự hủy", "găng tay tự hủy", D2, volume=300),
        metric("găng tay dùng một lần", "găng tay tự hủy", D2, volume=90),
        metric("nước rửa chén", "nước rửa chén", D2, status="no_match"),
        metric("túi rác sinh học", "túi rác sinh học", D2, status="blocked"),
    ]


async def _answers(session: AsyncSession, seeded) -> dict[str, object]:
    app = build_app(session)
    authenticate(app, user=seeded.user, shop=seeded.shop)
    window = {"period": "7d", "as_of": CUR_END.isoformat()}
    out: dict[str, object] = {}
    try:
        async with client_for(app) as client:
            for name, path, params in (
                ("keywords", "/keywords", {}),
                ("orders", "/orders", window),
                ("products", "/dashboard/products", {}),
                ("flows", "/dashboard/flows", {}),
                ("ads", "/dashboard/ads", {}),
                # Pinned: with no promotion_daily rows the default window ends today, and the
                # seeded programme (ending CUR_END) fell out of it once the calendar moved on.
                (
                    "promotions",
                    "/dashboard/promotions",
                    {"from": PROMO_FROM, "to": CUR_END.isoformat()},
                ),
            ):
                response = await client.get(f"{DEMO}{path}", params=params)
                assert response.status_code == 200, (name, response.text)
                out[name] = response.json()
    finally:
        app.dependency_overrides.clear()
    return out


async def test_the_four_pages_answer_with_the_committed_real_shapes():
    async with pg_session() as session:
        seeded = await seed_shopee_shop(session, rules=True)
        session.add_all(_seed_keywords(seeded.shop_id))
        # Another shop with its own keyword and orders: nothing of it may enter the answers.
        other = await seed_shopee_shop(session, rules=True)
        session.add(
            ShopKeywordSeed(
                id=uuid.uuid4(),
                shop_id=other.shop_id,
                platform="shopee",
                keyword="khoá của shop khác",
                pattern="type_function",
                item_ids=["1001"],
                enabled=True,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.flush()
        got = await _answers(session, seeded)
        text = json.dumps(got, ensure_ascii=False)
    assert "khoá của shop khác" not in text
    for ref in seeded.order_refs | other.order_refs:
        assert ref not in text
    for banned in (
        '"order_ref"',
        '"buyer_id',
        '"buyer_name',
        '"buyer_user',
        "recipient",
        '"address',
        '"phone',
    ):
        assert banned not in text

    products = got["products"]
    assert isinstance(products, dict) and products["products"]
    for row in products["products"]:
        assert {"price_min", "price_max", "list_price", "margin_pct", "margin_basis"} <= row.keys()
        assert row["margin_basis"] in {"theo đơn thực tế", "ước tính", "chưa tính"}
    assert any(r["price_min"] is not None for r in products["products"])

    rendered = json.dumps(got, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if os.environ.get("JULI_WRITE_FIXTURES") == "1":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(rendered, encoding="utf-8")
    assert FIXTURE.read_text(encoding="utf-8") == rendered, (
        "the real answers differ from the committed fixture: "
        "rerun with JULI_WRITE_FIXTURES=1 and commit it"
    )


@pytest.mark.parametrize(
    "path", ["/keywords", "/orders", "/dashboard/products", "/dashboard/flows"]
)
async def test_a_second_seller_reads_only_their_own_shop(path):
    async with pg_session() as session:
        mine = await seed_shopee_shop(session, rules=True)
        other = await seed_shopee_shop(session, rules=True)
        session.add(
            ShopKeywordSeed(
                id=uuid.uuid4(),
                shop_id=other.shop_id,
                platform="shopee",
                keyword="khoá của shop khác",
                pattern="type_function",
                item_ids=["1001"],
                enabled=True,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.flush()
        app = build_app(session)
        authenticate(app, user=mine.user, shop=mine.shop)
        try:
            async with client_for(app) as client:
                response = await client.get(
                    f"{DEMO}{path}", params={"period": "7d", "as_of": CUR_END.isoformat()}
                )
        finally:
            app.dependency_overrides.clear()
    assert response.status_code == 200
    assert "khoá của shop khác" not in response.text


async def test_the_public_market_lane_is_read_as_the_runtime_role_only_through_the_ops_block():
    """P92 B-10: ``market_*`` tables are Ops-only for ``juli_app`` (migration 108).

    The seller routes read them through the short ``ops_role`` block (as Từ khóa already does);
    without it the runtime role is refused, with it the read works and the role is restored."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from juli_backend.repositories import MarketListingsReadRepo
    from juli_backend.services.ops.access import ops_role
    from juli_backend.services.shopee_analytics import loaders
    from tests.integration.two_tenant import RUNTIME_ROLE

    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
            session = AsyncSession(bind=conn, expire_on_commit=False)
            try:
                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        await MarketListingsReadRepo(session).latest_page1(["x"])
                async with session.begin_nested(), ops_role(session):
                    assert await MarketListingsReadRepo(session).latest_page1(["x"]) == {}
                assert await loaders.load_keyword_market(session, ["x"]) == {}
                assert (await session.execute(text("SELECT current_user"))).scalar() == RUNTIME_ROLE
            finally:
                await session.close()
    finally:
        await engine.dispose()
