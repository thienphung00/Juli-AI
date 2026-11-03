"""P90 Step 6 on real Postgres, as ``juli_app`` under RLS: file vs Connector precedence (D-5),
the ad spend and voucher resolvers on stored rows (G-07, G-14), read-back verification events
(migration 114) and the migration's up / down. Synthetic tenants and numbers only."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services import ingest as svc
from juli_backend.services.card_events.verification import VERIFY_WINDOW, verify_shop
from juli_backend.services.ingest.readers import load_ad_spend, load_voucher_join
from tests.integration.test_ingest_two_tenant import juli_app_session
from tests.integration.test_shopee_orders_db import shopee_tenants  # noqa: F401 (fixture)
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]

NOW = datetime(2026, 11, 4, 3, 0)  # naive UTC
CARD = "psd_label_product_card"


def _body(rows, *, source, day="2026-10-01", end=None, granularity="day", **over):
    body = {
        "source": source,
        "source_version": f"{source}-1",
        "captured_at": "2026-11-03T09:30:00+07:00",
        "period": {"start": day, "end": end or day, "granularity": granularity},
        "rows": rows,
        **over,
    }
    return body


async def _post(shop_id, dataset, body):
    async with juli_app_session() as session:
        async with with_shop_scope(session, shop_id):
            await svc.ingest(
                session,
                shop_id=shop_id,
                platform="shopee",
                dataset=dataset,
                body=svc.IngestBody.model_validate(body),
                token_id=None,
                now=NOW,
            )
        await session.commit()


async def _query(shop_id, sql, **params):
    async with juli_app_session() as session:
        async with with_shop_scope(session, shop_id):
            return (await session.execute(text(sql), params)).all()


def _traffic(sales):
    return [{"date": "2026-10-01", "source": CARD, "sales": sales, "orders": 1}]


GMV = (
    "SELECT gmv::int, source FROM public.platform_daily_metrics "
    "WHERE dataset = 'traffic_overview' AND day = '2026-10-01' AND segment = 'all'"
)


async def test_a_file_post_replaces_a_connector_row_and_a_connector_post_never_replaces_a_file(
    shopee_tenants,  # noqa: F811
):
    a, b = shopee_tenants
    kw = {"order_type": "confirmed"}
    # connector first, then the file: the file wins
    await _post(a.shop_id, "traffic_overview", _body(_traffic(900), source="extension", **kw))
    assert await _query(a.shop_id, GMV) == [(900, "extension")]
    await _post(a.shop_id, "traffic_overview", _body(_traffic(1000), source="file", **kw))
    assert await _query(a.shop_id, GMV) == [(1000, "file")]
    # the file first, then the connector: the file stays
    await _post(b.shop_id, "traffic_overview", _body(_traffic(1000), source="file", **kw))
    later = _body(_traffic(900), source="extension", **kw)
    later["captured_at"] = "2026-11-04T09:30:00+07:00"
    await _post(b.shop_id, "traffic_overview", later)
    assert await _query(b.shop_id, GMV) == [(1000, "file")]
    # and the first shop never saw the second's rows
    assert await _query(a.shop_id, GMV) == [(1000, "file")]


async def test_a_row_stored_at_the_old_equal_rank_is_still_outranked_by_a_file(shopee_tenants):  # noqa: F811
    _, b = shopee_tenants
    kw = {"order_type": "confirmed"}
    day = "2026-10-02"
    rows = [{"date": day, "source": CARD, "sales": 500, "orders": 1}]
    await _post(b.shop_id, "traffic_overview", _body(rows, source="file", day=day, **kw))
    async with juli_app_session() as session:  # make it look like a row written before D-5
        async with with_shop_scope(session, b.shop_id):
            await session.execute(
                text("UPDATE public.platform_daily_metrics SET source_rank = 2 WHERE day = :d"),
                {"d": date(2026, 10, 2)},
            )
        await session.commit()
    rows = [{"date": day, "source": CARD, "sales": 400, "orders": 1}]
    later = _body(rows, source="extension", day=day, **kw)
    later["captured_at"] = "2026-11-04T09:30:00+07:00"
    await _post(b.shop_id, "traffic_overview", later)
    got = await _query(
        b.shop_id,
        "SELECT gmv::int, source FROM public.platform_daily_metrics "
        "WHERE dataset = 'traffic_overview' AND day = '2026-10-02'",
    )
    assert got == [(500, "file")]


async def test_item_traffic_sources_lands_through_the_runtime_role(shopee_tenants):  # noqa: F811
    a, b = shopee_tenants
    rows = [
        {"date": "2026-10-03", "item_id": "1001", "l1": "product_card", "l2": "total", "sales": 10},
        {"date": "2026-10-03", "item_id": "1001", "l1": "product_card", "l2": "shop", "sales": 4},
    ]
    await _post(
        a.shop_id,
        "item_traffic_sources",
        _body(rows, source="extension", day="2026-10-03", order_type="confirmed"),
    )
    got = await _query(
        a.shop_id,
        "SELECT stream, segment, order_type FROM public.platform_daily_metrics "
        "WHERE dataset = 'item_traffic_sources' ORDER BY segment",
    )
    assert got == [("product_card", "all", "confirmed"), ("product_card", "shop_page", "confirmed")]
    assert not await _query(
        b.shop_id,
        "SELECT 1 FROM public.platform_daily_metrics WHERE dataset = 'item_traffic_sources'",
    )


def _ad_day(campaign_id, name, day, cost):
    return {"date": day, "campaign_id": campaign_id, "campaign_name": name, "cost": cost}


async def test_ad_spend_takes_the_connector_days_and_csv_for_the_rest(shopee_tenants):  # noqa: F811
    a, _ = shopee_tenants
    # CSV window Oct 10-12, one group campaign with two product rows
    window = {"start": "2026-10-10", "end": "2026-10-12", "granularity": "period"}
    csv_rows = [
        {"campaign_name": "Nhóm A", "item_id": "1001", "ads_expense": 600, "sales": 1},
        {"campaign_name": "Nhóm A", "item_id": "1002", "ads_expense": 300, "sales": 1},
    ]
    csv = _body(csv_rows, source="file", day="2026-10-10", end="2026-10-12", granularity="period")
    csv["period"] = window
    csv["order_type"] = "placed"
    await _post(a.shop_id, "ads_campaign_period", csv)
    # the Connector read Oct 12 only: that day replaces the CSV's third of the window
    day = _body(
        [_ad_day("7001", "Nhóm A", "2026-10-12", 90)],
        source="extension",
        day="2026-10-12",
        order_type="placed",
    )
    await _post(a.shop_id, "ads_campaign_daily", day)
    async with juli_app_session() as session:
        async with with_shop_scope(session, a.shop_id):
            result = await load_ad_spend(session, a.shop_id, date(2026, 10, 10), date(2026, 10, 12))
    assert result.connector_total == 90
    assert result.csv_total == 600  # (600 + 300) x 2/3 days
    assert result.total == 690 and result.order_basis == "placed" and result.prorated
    assert result.products == {"1001": 400, "1002": 200}


async def test_the_voucher_export_joins_the_connector_settings_by_name_and_date(
    shopee_tenants,  # noqa: F811
):
    a, _ = shopee_tenants
    export = {
        "program_name": "Voucher Tri ân",
        "promo_type": "Voucher",
        "starts_at": "2026-10-01T00:00:00",
        "ordinal": 0,
        "orders": 3,
        "extra": {"voucher_cost": 30000},
    }
    await _post(
        a.shop_id,
        "promotions",
        _body(
            [export],
            source="file",
            day="2026-10-01",
            end="2026-10-28",
            granularity="period",
            order_type="confirmed",
        ),
    )
    setting = {
        "voucher_id": "9001",
        "program_name": "voucher  tri ân",
        "starts_at": "2026-10-01T08:30:00",
        "discount_amount": 10000,
    }
    twin = {**setting, "voucher_id": "9002", "program_name": "Voucher Khác"}
    await _post(
        a.shop_id,
        "voucher_settings",
        _body([setting, twin], source="extension", day="2026-11-03", granularity="period"),
    )
    async with juli_app_session() as session:
        async with with_shop_scope(session, a.shop_id):
            join = await load_voucher_join(session, a.shop_id)
    assert len(join.matched) == 1 and join.ambiguous == 0
    assert len(join.unmatched_settings) == 1 and join.unmatched_exports == ()


# -- read-back verification as the runtime role ---------------------------------------------


async def test_a_saved_price_is_verified_and_an_unseen_budget_is_flagged(shopee_tenants):  # noqa: F811
    _, b = shopee_tenants
    shop_id = b.shop_id
    executed_at = datetime(2026, 11, 1, 2, 0, tzinfo=UTC)
    cards = [uuid.uuid4(), uuid.uuid4()]
    async with juli_app_session() as session:
        async with with_shop_scope(session, shop_id):
            for cid, kind, target, expected in zip(
                cards,
                ("price", "daily_budget"),
                ({"item_id": "2001"}, {"campaign_id": "8001"}),
                ({"current_price": 89000}, {"daily_budget": 300000}),
                strict=True,
            ):
                await session.execute(
                    text(
                        "INSERT INTO public.action_cards (id, shop_id, workflow_key, subject_type, "
                        "subject_id, revision, priority, severity, title, description, "
                        "recommendation_payload, status, metadata_json, computed_at) VALUES "
                        "(:id, :shop, :wk, 'item', :sid, 1, 1, 'high', 't', 'd', '{}', 'active', "
                        "'{}', :now)"
                    ),
                    {"id": cid, "shop": shop_id, "wk": f"wk_{cid.hex[:8]}", "sid": "x", "now": NOW},
                )
                await session.execute(
                    text(
                        "INSERT INTO public.card_events (id, card_id, shop_id, workflow_key, "
                        "subject_type, subject_id, event_type, actor, occurred_at, source, "
                        "payload, "
                        "schema_version, dedup_key) VALUES (:id, :card, :shop, :wk, 'item', 'x', "
                        "'executed', 'seller', :at, 'live', CAST(:payload AS jsonb), 1, :dk)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "card": cid,
                        "shop": shop_id,
                        "wk": f"wk_{cid.hex[:8]}",
                        "at": executed_at,
                        "payload": json.dumps(
                            {
                                "change": {
                                    "change_kind": kind,
                                    "target": target,
                                    "expected": expected,
                                }
                            }
                        ),
                        "dk": f"assisted:{cid}",
                    },
                )
        await session.commit()
    # the Connector's product read, two days after the save, shows the new price
    snap = {
        "item_id": "2001",
        "price_min": 89000,
        "price_max": 89000,
        "selling_price_min": 89000,
        "total_available_stock": 5,
    }
    await _post(
        shop_id,
        "item_snapshot",
        _body([snap], source="extension", day="2026-11-03", granularity="period"),
    )
    now = executed_at + VERIFY_WINDOW + timedelta(hours=1)
    async with juli_app_session() as session:
        async with with_shop_scope(session, shop_id):
            counts = await verify_shop(session, shop_id, now)
        await session.commit()
    assert (counts.checked, counts.verified, counts.not_seen) == (2, 1, 1)
    got = await _query(
        shop_id,
        "SELECT e.event_type, v.payload->>'change_kind' FROM public.card_events e "
        "JOIN public.card_events v ON v.id = e.id "
        "WHERE e.event_type IN ('verified', 'mismatch', 'not_seen') ORDER BY 1",
    )
    assert got == [("not_seen", "daily_budget"), ("verified", "price")]
    # a second run is a no-op
    async with juli_app_session() as session:
        async with with_shop_scope(session, shop_id):
            again = await verify_shop(session, shop_id, now)
    assert again.checked == 0


# -- migration 114 -----------------------------------------------------------------------


def test_zz_migration_114_up_and_down(owner_engine, shopee_tenants):  # noqa: F811
    """Last in the module: the CHECK takes the new names at head, refuses them after a downgrade
    to 113 and takes them again after ``upgrade head``."""
    import os
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    from juli_backend.core.config.runtime import sync_database_url

    a, _ = shopee_tenants
    repo = Path(__file__).resolve().parents[2]
    cfg = Config(str(repo / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(repo / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(os.environ["DATABASE_URL"]))

    with owner_engine.begin() as conn:
        card = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO public.action_cards (id, shop_id, workflow_key, subject_type, "
                "subject_id, revision, priority, severity, title, description, "
                "recommendation_payload, status, metadata_json, computed_at) VALUES "
                "(:id, :shop, 'wk114', 'item', 'x', 1, 1, 'high', 't', 'd', '{}', 'active', "
                "'{}', now())"
            ),
            {"id": card, "shop": a.shop_id},
        )

    def insert(event_type: str) -> None:
        with owner_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO public.card_events (id, card_id, shop_id, workflow_key, "
                    "subject_type, subject_id, event_type, actor, occurred_at, source, "
                    "payload, "
                    "schema_version, dedup_key) VALUES (:id, :card, :shop, 'wk114', 'item', 'x', "
                    ":t, 'system', now(), 'live', '{}'::jsonb, 1, :dk)"
                ),
                {
                    "id": uuid.uuid4(),
                    "card": card,
                    "shop": a.shop_id,
                    "t": event_type,
                    "dk": uuid.uuid4().hex,
                },
            )

    def check_def() -> str:
        with owner_engine.connect() as conn:
            return conn.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'ck_card_events_event_type'"
                )
            ).scalar_one()

    for name in ("verified", "mismatch", "not_seen"):
        insert(name)  # the new names are accepted at head
    insert("executed")
    command.downgrade(cfg, "113_shopee_orders_and_logs")
    try:
        text_down = check_def()
        assert "verified" not in text_down and "whatif_adjusted" in text_down
        insert("executed")  # the old names still are
        with pytest.raises(DBAPIError):
            insert("verified")
    finally:
        command.upgrade(cfg, "head")
    insert("not_seen")
