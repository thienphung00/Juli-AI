"""Fast track P23 (D30.1 / D30.4): product history, promotions, external changes, baselines.

SQLite; TikTok is a fake read-resources object (no network). The Postgres RLS
proof for the five tables is the generic two-tenant isolation test, which reads
``tenant_scoped_tables`` (they are classified tenant_direct here).
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.integrations.tiktok.merchant import TikTokCapability
from juli_backend.models.history import (
    KIND_CONTENT,
    KIND_CREATION,
    KIND_PRICE,
    KIND_PROMOTION,
    PHASE_APPROVAL,
    PHASE_EXECUTION,
    SOURCE_RECONCILE,
    SOURCE_WEBHOOK_15,
    SOURCE_WEBHOOK_63,
    ExternalChange,
    ProductSnapshot,
    PromotionActivity,
    PromotionActivityProduct,
    RunBaseline,
)
from juli_backend.models.lever_flows import RunLeverFlow
from juli_backend.models.models import AnalyticsPerformanceInterval, Shop, User, WebhookRawEvent
from juli_backend.models.run_changes import RunWriteValue
from juli_backend.repositories import TikTokCredentialRepo, WorkflowWebhookSignalsRepo
from juli_backend.services.product_history import job as history_job
from juli_backend.services.product_history import promotions as promo
from juli_backend.services.product_history import webhooks as history_webhooks
from juli_backend.services.product_history.baselines import capture_run_baseline, pre_series
from juli_backend.services.product_history.normalize import normalize_detail
from juli_backend.services.product_history.overlap import (
    external_changes_overlapping,
    measurement_window,
)
from juli_backend.services.product_history.replay import replay_raw_events
from juli_backend.services.product_history.store import latest_snapshots, record_read
from juli_backend.services.tiktok.dispatcher import TikTokWebhookDispatcher
from juli_backend.services.tiktok.schemas import TikTokWebhookPayload
from juli_backend.services.tiktok.webhook import resolve_ingest_channel, should_handoff_to_etl
from juli_backend.services.tiktok.webhook_catalog import resolve_catalog_entry
from juli_backend.services.tiktok.webhook_handlers import DatabaseWebhookSideEffects
from tests.support.builders import make_product, make_tenant, make_workflow_run

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS = REPO_ROOT / "backend/src/juli_backend/database/migrations/versions"
MIGRATION = VERSIONS / "087_history_and_baselines.py"
DEFERRED = VERSIONS.parent / "deferred" / "074_users_placeholder_phone_cleanup.py"

NOW = datetime(2026, 10, 12, 3, 0)  # naive UTC = 10:00 UTC+7
T0 = 1_791_000_000  # an epoch before NOW


def _epoch(moment: datetime) -> int:
    return int(moment.replace(tzinfo=UTC).timestamp())


def _detail(pid: str, **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": pid,
        "title": "Chai Xịt Thơm Miệng 14mL",
        "description": "<p>Mô tả</p>",
        "main_images": [{"uri": "tos/img-1"}, {"uri": "tos/img-2"}],
        "product_attributes": [{"id": "100149", "values": [{"id": "1000854"}]}],
        "category_chains": [{"id": "601693", "is_leaf": True}],
        "skus": [
            {
                "id": "sku-1",
                "seller_sku": "XTM-C",
                "price": {"currency": "VND", "tax_exclusive_price": "72000", "sale_price": "72000"},
            }
        ],
        "status": "ACTIVATE",
        "update_time": T0,
        "create_time": T0 - 86400 * 100,
    }
    body.update(over)
    return body


def _list_row(detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": detail["id"],
        "title": detail["title"],
        "status": detail["status"],
        "update_time": detail["update_time"],
        "create_time": detail["create_time"],
        "skus": [
            {"id": s["id"], "price": {"tax_exclusive_price": s["price"]["tax_exclusive_price"]}}
            for s in detail["skus"]
        ],
    }


class FakeResources:
    """Read-only TikTok fake: products and promotions, counting every call."""

    def __init__(self) -> None:
        self.details: dict[str, dict[str, Any]] = {}
        self.activities: dict[str, dict[str, Any]] = {}
        self.activity_details: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, str]] = []
        self.products = SimpleNamespace(search_all=self._search, get_details=self._get)
        self.promotion = SimpleNamespace(
            search_activities_all=self._search_activities, get_activity=self._get_activity
        )

    def _search(self, **_kw: Any) -> list[dict[str, Any]]:
        self.calls.append(("search_products", ""))
        return [_list_row(d) for d in self.details.values()]

    def _get(self, pid: str) -> dict[str, Any]:
        self.calls.append(("get_product", pid))
        return dict(self.details[pid])

    def _search_activities(self, *, status: str, **_kw: Any) -> list[dict[str, Any]]:
        self.calls.append(("search_activities", status))
        return [a for a in self.activities.values() if a["status"] == status]

    def _get_activity(self, activity_id: str) -> dict[str, Any]:
        self.calls.append(("get_activity", activity_id))
        return dict(self.activity_details.get(activity_id, {"products": []}))

    def count(self, name: str) -> int:
        return sum(1 for call, _ in self.calls if call == name)


@pytest.fixture
def factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def seeded(factory):
    """A shop with a seller-connect read credential; returns its id and tiktok id."""
    async with factory() as session:
        user = User(id=uuid.uuid4(), phone=f"+8491{uuid.uuid4().int % 10_000_000:07d}")
        shop = Shop(
            id=uuid.uuid4(),
            user_id=user.id,
            shop_name="Fujiwa",
            tiktok_shop_id=f"tt-{uuid.uuid4().hex[:8]}",
            is_active=True,
        )
        session.add_all([user, shop])
        await session.flush()
        await TikTokCredentialRepo(session).create(
            shop_id=shop.id,
            access_token="access",
            refresh_token="refresh",
            token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
            merchant_authorization_id="merchant-fujiwa",
            capability=TikTokCapability.SELLER_CONNECT.value,
            shop_cipher="cipher",
        )
        await session.commit()
        return SimpleNamespace(id=shop.id, tiktok_id=shop.tiktok_shop_id)


async def _resources(factory, shop_id, fake):
    plan = await history_job.plan_reads(factory, shop_id, app_key="k", app_secret="s")
    assert plan.config.access_token == "access"
    return history_job.build_resources(plan, app_key="k", create_resources=lambda _c: fake)


async def _changes(factory, shop_id) -> list[ExternalChange]:
    async with factory() as session:
        rows = await session.execute(
            select(ExternalChange)
            .where(ExternalChange.shop_id == shop_id)
            .order_by(ExternalChange.occurred_at, ExternalChange.kind)
        )
        return list(rows.scalars())


# -- migration -----------------------------------------------------------------------------


def test_migration_087_chain_shape_and_pins():
    text = MIGRATION.read_text(encoding="utf-8")
    later = (VERSIONS / "096_change_attribution.py").read_text(encoding="utf-8")
    assert 'revision: str = "087_history_and_baselines"' in text
    assert len("087_history_and_baselines") <= 32
    assert 'down_revision: str | None = "086_ops_cost_and_terms"' in text
    assert 'down_revision: str | None = "100_sandbox_collision_xshop"' in DEFERRED.read_text(
        "utf-8"
    )
    children = [
        p.name
        for p in VERSIONS.glob("*.py")
        if 'down_revision: str | None = "086_ops_cost_and_terms"' in p.read_text("utf-8")
    ]
    assert children == ["087_history_and_baselines.py"]
    for model in (
        ProductSnapshot,
        PromotionActivity,
        PromotionActivityProduct,
        ExternalChange,
        RunBaseline,
    ):
        assert f'"{model.__tablename__}"' in text
        for column in model.__table__.columns.keys():
            # P60-1b: 096 adds `external_changes.attribution` / `field_attribution`.
            assert f'"{column}"' in text + later, (model.__tablename__, column)
    assert "ENABLE ROW LEVEL SECURITY" in text and "app_current_shop_id()" in text
    assert 'APPEND_ONLY_VERBS = "SELECT, INSERT"' in text
    assert "SNAPSHOTS_TABLE: APPEND_ONLY_VERBS" in text
    assert "CHANGES_TABLE: APPEND_ONLY_VERBS" in text
    assert "DELETE" not in text.split("GRANTS")[1].split("def ")[0]
    assert "uq_product_snapshots_day_state" in text and "uq_external_changes_dedup" in text


def test_new_tables_are_tenant_direct_and_the_gate_accepts_087():
    from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP

    for table in (
        "product_snapshots",
        "promotion_activities",
        "promotion_activity_products",
        "external_changes",
        "run_baselines",
    ):
        assert TABLE_CLASSIFICATION_MAP[("public", table)] == "tenant_direct"
    sys.path.insert(0, str(REPO_ROOT / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([MIGRATION])
    assert result.accepted, result.report()


# -- snapshot diff ---------------------------------------------------------------------------


async def _record(session, shop_id, detail, previous=None, **kw):
    return await record_read(
        session,
        shop_id=shop_id,
        new=normalize_detail(detail),
        previous=previous,
        source=kw.pop("source", SOURCE_RECONCILE),
        now=kw.pop("now", NOW),
        **kw,
    )


@pytest.mark.asyncio
async def test_no_change_writes_no_snapshot_and_no_change(session):
    _, shop = await make_tenant(session)
    first = await _record(session, shop.id, _detail("p1"), baseline=True)
    assert first.snapshot is not None and first.changes == []
    again = await _record(session, shop.id, _detail("p1"), previous=first.snapshot)
    assert again.snapshot is None and again.changes == []
    # Same state replayed later the same day without a previous: still stored once.
    replay = await _record(session, shop.id, _detail("p1"), baseline=True)
    assert replay.snapshot is None
    count = await session.execute(select(ProductSnapshot).where(ProductSnapshot.shop_id == shop.id))
    assert len(list(count.scalars())) == 1


@pytest.mark.asyncio
async def test_title_change_is_a_content_change(session):
    _, shop = await make_tenant(session)
    base = await _record(session, shop.id, _detail("p1"), baseline=True)
    out = await _record(
        session,
        shop.id,
        _detail("p1", title="Tiêu đề mới", update_time=T0 + 600),
        previous=base.snapshot,
    )
    assert [c.kind for c in out.changes] == [KIND_CONTENT]
    change = out.changes[0]
    assert change.fields == ["title"]
    assert change.juli_write is False
    assert change.details["title"] == {"before": "Chai Xịt Thơm Miệng 14mL", "after": "Tiêu đề mới"}
    assert change.occurred_at == datetime.fromtimestamp(T0 + 600, UTC).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_price_change_is_a_price_change(session):
    _, shop = await make_tenant(session)
    base = await _record(session, shop.id, _detail("p1"), baseline=True)
    cheaper = _detail("p1")
    cheaper["skus"][0]["price"] = {"currency": "VND", "tax_exclusive_price": "65000"}
    out = await _record(session, shop.id, cheaper, previous=base.snapshot)
    assert [c.kind for c in out.changes] == [KIND_PRICE]
    assert out.changes[0].fields[0] == "price"
    assert out.changes[0].details["skus"]["sku-1"]["list_price"] == {
        "before": "72000",
        "after": "65000",
    }


@pytest.mark.asyncio
async def test_juli_own_write_is_marked_juli_write(session):
    _, shop = await make_tenant(session)
    product = await make_product(session, shop, tiktok_product_id="p1")
    run = await make_workflow_run(session, shop, product=product)
    base = await _record(session, shop.id, _detail("p1"), baseline=True)
    written_at = datetime(2026, 10, 3, 4, 40)
    session.add(
        RunWriteValue(
            shop_id=shop.id,
            workflow_run_id=run.id,
            tool_call_id="call-1",
            tool_name="update_product_listing",
            tiktok_product_id="p1",
            field="title",
            before_value="Chai Xịt Thơm Miệng 14mL",
            after_value="Tiêu đề Juli",
            after_source="read_back",
            recorded_at=written_at,
        )
    )
    await session.flush()
    out = await _record(
        session,
        shop.id,
        _detail("p1", title="Tiêu đề Juli", update_time=_epoch(written_at) + 300),
        previous=base.snapshot,
    )
    assert [(c.kind, c.juli_write) for c in out.changes] == [(KIND_CONTENT, True)]

    # The seller then edits the title again by hand: external, even though Juli wrote
    # the title an hour earlier (the value no longer matches Juli's).
    out2 = await _record(
        session,
        shop.id,
        _detail("p1", title="Seller tự sửa", update_time=_epoch(written_at) + 3600),
        previous=out.snapshot,
        now=NOW + timedelta(minutes=1),
    )
    assert [(c.kind, c.juli_write) for c in out2.changes] == [(KIND_CONTENT, False)]


# -- daily reconciliation --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_reconcile_baseline_then_only_changed_products(factory, seeded):
    fake = FakeResources()
    fake.details = {pid: _detail(pid) for pid in ("p1", "p2", "p3")}
    resources = await _resources(factory, seeded.id, fake)

    first = await history_job.reconcile_products(factory, seeded.id, resources, now=NOW)
    assert first.baseline and first.snapshots == 3 and first.changes == 0
    assert fake.count("get_product") == 3
    assert await _changes(factory, seeded.id) == []

    # Next day: p1's title moved update_time; p2's list price moved without it; p3 same.
    fake.calls.clear()
    fake.details["p1"] = _detail("p1", title="Mới", update_time=T0 + 7200)
    fake.details["p2"]["skus"][0]["price"] = {"currency": "VND", "tax_exclusive_price": "69000"}
    fake.details["p4"] = _detail("p4", create_time=_epoch(NOW) + 3600, update_time=T0)
    second = await history_job.reconcile_products(
        factory, seeded.id, resources, now=NOW + timedelta(days=1)
    )
    assert not second.baseline
    assert sorted(pid for call, pid in fake.calls if call == "get_product") == ["p1", "p2", "p4"]
    kinds = {(c.tiktok_product_id, c.kind, c.source) for c in await _changes(factory, seeded.id)}
    assert kinds == {
        ("p1", KIND_CONTENT, SOURCE_RECONCILE),
        ("p2", KIND_PRICE, SOURCE_RECONCILE),
        ("p4", KIND_CREATION, SOURCE_RECONCILE),
    }

    # Third run, nothing moved: one search, no product read, no new row.
    fake.calls.clear()
    third = await history_job.reconcile_products(
        factory, seeded.id, resources, now=NOW + timedelta(days=2)
    )
    assert fake.count("get_product") == 0 and third.snapshots == 0
    assert len(await _changes(factory, seeded.id)) == 3


@pytest.mark.asyncio
async def test_webhook_refresh_product_uses_the_snapshot_diff(factory, seeded):
    fake = FakeResources()
    fake.details = {"p1": _detail("p1")}
    resources = await _resources(factory, seeded.id, fake)
    await history_job.reconcile_products(factory, seeded.id, resources, now=NOW)
    fake.details["p1"] = _detail("p1", description="<p>Mô tả mới</p>", update_time=T0 + 60)
    count = await history_job.refresh_product(
        factory,
        seeded.id,
        resources,
        product_id="p1",
        source=SOURCE_WEBHOOK_15,
        hint_kind=KIND_CONTENT,
        hint_fields=["description"],
        now=NOW + timedelta(hours=1),
    )
    assert count == 1
    (change,) = await _changes(factory, seeded.id)
    assert (change.kind, change.fields, change.source) == (
        KIND_CONTENT,
        ["description"],
        SOURCE_WEBHOOK_15,
    )
    # Replayed: same state, no new change.
    again = await history_job.refresh_product(
        factory,
        seeded.id,
        resources,
        product_id="p1",
        source=SOURCE_WEBHOOK_15,
        hint_kind=KIND_CONTENT,
        now=NOW + timedelta(hours=2),
    )
    assert again == 0


# -- promotions ------------------------------------------------------------------------------


def _activity(aid: str, status: str, **over: Any) -> dict[str, Any]:
    row = {
        "id": aid,
        "title": f"Flash {aid}",
        "activity_type": "FLASHSALE",
        "status": status,
        "product_level": "VARIATION",
        "begin_time": _epoch(NOW) - 86400,
        "end_time": _epoch(NOW) + 86400,
        "create_time": _epoch(NOW) - 2 * 86400,
        "update_time": _epoch(NOW) - 2 * 86400,
    }
    row.update(over)
    return row


def _activity_detail(pid: str, price: str = "59000") -> dict[str, Any]:
    return {
        "products": [
            {
                "id": pid,
                "skus": [{"id": "sku-1", "activity_price": {"amount": price, "currency": "VND"}}],
            }
        ]
    }


@pytest.mark.asyncio
async def test_promotion_backfill_then_daily_sweep_records_new_and_deactivated(factory, seeded):
    fake = FakeResources()
    fake.activities = {
        "a1": _activity("a1", "ONGOING"),
        "a2": _activity("a2", "EXPIRED", end_time=_epoch(NOW) - 3600),
        "a3": _activity("a3", "DEACTIVATED"),
    }
    fake.activity_details = {"a1": _activity_detail("p1"), "a2": _activity_detail("p2", "50000")}
    resources = await _resources(factory, seeded.id, fake)

    first = await history_job.sweep_promotions(factory, seeded.id, resources, now=NOW)
    assert first.backfill and first.activities == 3 and first.details_read == 3
    assert first.changes == 0
    assert fake.count("search_activities") == len(promo.ACTIVITY_STATUSES)
    async with factory() as session:
        stored = {
            row.activity_id: row
            for row in (
                await session.execute(
                    select(PromotionActivity).where(PromotionActivity.shop_id == seeded.id)
                )
            ).scalars()
        }
        assert set(stored) == {"a1", "a2", "a3"}
        assert stored["a3"].deactivated_at is not None
        prices = (
            await session.execute(
                select(PromotionActivityProduct).where(
                    PromotionActivityProduct.shop_id == seeded.id,
                    PromotionActivityProduct.activity_id == "a1",
                )
            )
        ).scalars()
        assert [(r.tiktok_product_id, r.tiktok_sku_id, r.activity_price) for r in prices] == [
            ("p1", "sku-1", Decimal("59000.00"))
        ]

    # Next day: a4 appears, a1 is deactivated; only those two details are read.
    fake.calls.clear()
    fake.activities["a4"] = _activity("a4", "NOT_START", activity_type="FIXED_PRICE")
    fake.activity_details["a4"] = _activity_detail("p3")
    fake.activities["a1"] = _activity("a1", "DEACTIVATED", update_time=_epoch(NOW) + 60)
    second = await history_job.sweep_promotions(
        factory, seeded.id, resources, now=NOW + timedelta(days=1)
    )
    assert not second.backfill
    assert sorted(aid for call, aid in fake.calls if call == "get_activity") == ["a1", "a4"]
    rows = {(c.tiktok_product_id, tuple(c.fields)) for c in await _changes(factory, seeded.id)}
    assert rows == {("p3", ("fixed_price", "start")), ("p1", ("flash_sale", "deactivate"))}


#: Webhook 63 ``Activity change`` as in the Partner Center doc example (shape).
WEBHOOK_63 = {
    "type": 63,
    "tts_notification_id": "7450000000000000063",
    "shop_id": "SHOP",
    "timestamp": 1791000600,
    "data": {
        "activity_id": "7450000000000000001",
        "change_type": "UPDATE",
        "update_time": 1791000500,
        "product_update_list": [
            {"product_id": "1734952395144267383", "sku_ids": ["1734952449674217079"]}
        ],
        "product_remove_list": [{"product_id": "1734952395144267999"}],
    },
}


def test_webhook_63_and_39_parsing():
    change = promo.parse_activity_change(WEBHOOK_63["data"], catalog_id=63)
    assert change.activity_id == "7450000000000000001"
    assert change.change_type == "UPDATE"
    assert change.updated_products == ["1734952395144267383"]
    assert change.removed_products == ["1734952395144267999"]
    assert change.skus == {"1734952395144267383": ["1734952449674217079"]}
    assert change.occurred_at == datetime.fromtimestamp(1791000500, UTC).replace(tzinfo=None)
    assert promo.ActivityChange.from_json(change.to_json()) == change

    status = promo.parse_activity_change(
        {"activity_id": "a9", "status": "DEACTIVATED", "update_time": 1791000000}, catalog_id=39
    )
    assert status.change_type == "DEACTIVATE" and status.updated_products == []
    with pytest.raises(ValueError):
        promo.parse_activity_change({"change_type": "CREATE"}, catalog_id=63)
    assert promo.change_fields("FLASHSALE", "CREATE") == ["flash_sale", "start"]
    assert promo.change_fields(None, "UPDATE", "EXPIRED") == ["expire"]


@pytest.mark.asyncio
async def test_refresh_activity_webhook_63_marks_removed_and_records_per_product(factory, seeded):
    data = WEBHOOK_63["data"]
    kept, gone = "1734952395144267383", "1734952395144267999"
    fake = FakeResources()
    fake.activity_details[data["activity_id"]] = {
        "activity_type": "FIXED_PRICE",
        "status": "ONGOING",
        "title": "Giảm giá",
        "begin_time": _epoch(NOW) - 3600,
        "products": [{"id": kept, "skus": [{"id": "s1", "activity_price": "45000"}]}],
    }
    async with factory() as session:
        session.add(
            PromotionActivityProduct(
                shop_id=seeded.id,
                activity_id=data["activity_id"],
                tiktok_product_id=gone,
                tiktok_sku_id="",
                added_at=NOW - timedelta(days=3),
                updated_at=NOW - timedelta(days=3),
            )
        )
        await session.commit()
    resources = await _resources(factory, seeded.id, fake)
    change = promo.parse_activity_change(data, catalog_id=63)
    count = await history_job.refresh_activity(
        factory, seeded.id, resources, change=change, source=SOURCE_WEBHOOK_63, now=NOW
    )
    assert count == 2
    changes = await _changes(factory, seeded.id)
    assert {(c.tiktok_product_id, c.kind, tuple(c.fields), c.juli_write) for c in changes} == {
        (kept, KIND_PROMOTION, ("fixed_price", "update"), False),
        (gone, KIND_PROMOTION, ("fixed_price", "update"), False),
    }
    async with factory() as session:
        removed = (
            await session.execute(
                select(PromotionActivityProduct.removed_at).where(
                    PromotionActivityProduct.tiktok_product_id == gone
                )
            )
        ).scalar_one()
        assert removed == NOW
    # Redelivered: deduplicated.
    again = await history_job.refresh_activity(
        factory, seeded.id, resources, change=change, source=SOURCE_WEBHOOK_63, now=NOW
    )
    assert again == 0


@pytest.mark.asyncio
async def test_activity_found_by_a_juli_promotion_card_is_juli_write(session):
    _, shop = await make_tenant(session)
    run = await make_workflow_run(session, shop)
    session.add(
        RunLeverFlow(
            shop_id=shop.id,
            workflow_run_id=run.id,
            kind="promotion",
            lever="flash_sale",
            found={"ref": promo.promotion_ref("a-juli"), "type_label": "Flash sale"},
            verify_attempts=0,
        )
    )
    await session.flush()
    assert await promo.is_juli_activity(session, shop.id, "a-juli") is True
    assert await promo.is_juli_activity(session, shop.id, "a-other") is False


# -- webhooks 15 / 16 / 18 / 63 ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("catalog_id", "event_type", "handler", "channel"),
    [
        (
            15,
            "PRODUCT_INFORMATION_CHANGE",
            "product_information_change",
            "tiktok.product_information_change",
        ),
        (16, "PRODUCT_CREATION", "product_creation", "tiktok.product_creation"),
        (
            18,
            "PRODUCT_CATEGORY_CHANGE",
            "product_category_change",
            "tiktok.product_category_change",
        ),
        (63, "ACTIVITY_CHANGE", "activity_change", "tiktok.activity_change"),
    ],
)
def test_history_catalog_entries(catalog_id, event_type, handler, channel):
    for key in (event_type, str(catalog_id)):
        entry = resolve_catalog_entry(key)
        assert entry is not None and entry.catalog_id == catalog_id
        assert entry.handler_name == handler and entry.etl_channel == channel
    assert resolve_ingest_channel(str(catalog_id)) == channel
    # Their bodies carry only ids: never handed to the ETL product transform.
    assert should_handoff_to_etl(event_type, channel) is False
    assert TikTokWebhookPayload.from_dict({"type": catalog_id, "shop_id": "s"}).type == event_type


def test_history_work_for_each_type():
    w15 = history_webhooks.history_work_for(
        15, "S", {"product_id": "p1", "changed_fields": ["TITLE", "main_images"], "update_time": 1}
    )
    assert w15 is not None
    assert (w15.subject, w15.subject_id, w15.source, w15.hint_kind, w15.hint_fields) == (
        "product",
        "p1",
        "webhook_15",
        "content",
        ["main_images", "title"],
    )
    w16 = history_webhooks.history_work_for(16, "S", {"product_id": "p2"})
    assert w16 is not None and w16.hint_kind == "creation"
    w18 = history_webhooks.history_work_for(18, "S", {"product_id": "p3"})
    assert w18 is not None and (w18.hint_kind, w18.hint_fields) == ("category", ["category_id"])
    w63 = history_webhooks.history_work_for(63, "S", WEBHOOK_63["data"])
    assert w63 is not None and w63.subject == "activity" and w63.change is not None
    assert history_webhooks.history_work_for(15, "S", {}) is None
    assert history_webhooks.history_work_for(1, "S", {"order_id": "o"}) is None


@pytest.fixture
def captured_work():
    seen: list[tuple[str, Any]] = []

    def enqueue(shop_id, work):
        seen.append((shop_id, work))
        return f"task-{len(seen)}"

    history_webhooks.set_history_enqueuer(enqueue)
    history_webhooks.set_coalesce_gate(history_webhooks.InMemoryCoalesceGate())
    yield seen
    history_webhooks.set_history_enqueuer(None)
    history_webhooks.set_coalesce_gate(None)


@pytest.mark.asyncio
async def test_webhook_handler_is_idempotent_by_notification_id(session, captured_work):
    _, shop = await make_tenant(session)
    dispatcher = TikTokWebhookDispatcher(side_effects=DatabaseWebhookSideEffects(session))

    def event(notification: str, product: str, ts: int):
        return TikTokWebhookPayload.from_dict(
            {
                "type": 15,
                "tts_notification_id": notification,
                "shop_id": shop.tiktok_shop_id,
                "timestamp": ts,
                "data": {"product_id": product, "changed_fields": ["title"], "update_time": ts},
            }
        )

    assert await dispatcher.dispatch(event("n-1", "p1", 100)) == "product_information_change"
    await dispatcher.dispatch(event("n-1", "p1", 100))  # redelivery
    await dispatcher.dispatch(event("n-2", "p1", 101))  # same product inside the coalesce window
    await dispatcher.dispatch(event("n-3", "p2", 102))
    await session.flush()
    assert [(sid, w.subject_id) for sid, w in captured_work] == [
        (str(shop.id), "p1"),
        (str(shop.id), "p2"),
    ]
    signals = await WorkflowWebhookSignalsRepo(session).list_for_shop(shop.id)
    assert sorted(s.event_id for s in signals) == ["ttsn:n-1", "ttsn:n-2", "ttsn:n-3"]

    activity = TikTokWebhookPayload.from_dict({**WEBHOOK_63, "shop_id": shop.tiktok_shop_id})
    assert await dispatcher.dispatch(activity) == "activity_change"
    await dispatcher.dispatch(activity)
    assert [w.subject for _, w in captured_work].count("activity") == 1


@pytest.mark.asyncio
async def test_replay_stored_raw_events_enqueues_once(session, captured_work):
    _, shop = await make_tenant(session)
    bodies = [
        {
            "type": 15,
            "tts_notification_id": "r-1",
            "shop_id": shop.tiktok_shop_id,
            "timestamp": 1,
            "data": {"product_id": "p1", "changed_fields": ["title"]},
        },
        {
            "type": 16,
            "tts_notification_id": "r-2",
            "shop_id": shop.tiktok_shop_id,
            "timestamp": 2,
            "data": {"product_id": "p9"},
        },
        {**WEBHOOK_63, "shop_id": shop.tiktok_shop_id},
        {"type": 1, "shop_id": shop.tiktok_shop_id, "data": {"order_id": "o"}},
    ]
    for i, body in enumerate(bodies):
        session.add(
            WebhookRawEvent(
                received_at=NOW + timedelta(seconds=i),
                tiktok_shop_id=shop.tiktok_shop_id,
                event_type=str(body["type"]),
                raw_body=json.dumps(body),
                http_status=200,
                processing_status="unknown_event",
            )
        )
    session.add(
        WebhookRawEvent(
            tiktok_shop_id="nobody",
            event_type="15",
            raw_body=json.dumps({**bodies[0], "shop_id": "nobody"}),
            http_status=200,
            processing_status="unknown_event",
        )
    )
    await session.flush()

    first = await replay_raw_events(session)
    assert (first.scanned, first.replayed, first.unknown_shop) == (4, 3, 1)
    assert [(w.subject, w.subject_id, w.source) for _, w in captured_work] == [
        ("product", "p1", "webhook_15"),
        ("product", "p9", "webhook_16"),
        ("activity", "7450000000000000001", "webhook_63"),
    ]
    await replay_raw_events(session)
    assert len(captured_work) == 3


# -- baselines -------------------------------------------------------------------------------


async def _seed_metrics(session, shop, pid):
    for offset in range(1, 16):
        day = date(2026, 10, 12) - timedelta(days=offset)
        session.add(
            AnalyticsPerformanceInterval(
                shop_id=shop.id,
                snapshot_key=f"k-{pid}-{offset}",
                grain="product",
                start_date=day,
                end_date=day + timedelta(days=1),
                tiktok_product_id=pid,
                gmv=Decimal(100 * offset),
                impressions=None,
                clicks=10 * offset,
                sku_orders=offset,
                traffic_breakdown={"A34_TOTAL": {"impressions": 1000, "add_cart_count": 3}},
                update_time=NOW,
            )
        )
    await session.flush()


@pytest.mark.asyncio
async def test_baseline_capture_at_approval_and_execution(session):
    _, shop = await make_tenant(session)
    product = await make_product(session, shop, tiktok_product_id="p1")
    run = await make_workflow_run(session, shop, product=product)
    await _seed_metrics(session, shop, "p1")
    await _record(session, shop.id, _detail("p1"), baseline=True, now=NOW - timedelta(days=1))
    session.add(
        PromotionActivity(
            shop_id=shop.id,
            activity_id="a1",
            activity_type="FLASHSALE",
            status="ONGOING",
            begin_time=NOW - timedelta(days=1),
            end_time=NOW + timedelta(days=1),
            first_seen_at=NOW,
            refreshed_at=NOW,
        )
    )
    session.add(
        PromotionActivityProduct(
            shop_id=shop.id,
            activity_id="a1",
            tiktok_product_id="p1",
            tiktok_sku_id="sku-1",
            activity_price=Decimal("59000"),
            added_at=NOW,
            updated_at=NOW,
        )
    )
    await session.flush()

    row = await capture_run_baseline(
        session,
        shop_id=shop.id,
        workflow_run_id=run.id,
        product_id=product.id,
        phase=PHASE_APPROVAL,
        now=NOW,
    )
    assert row is not None and row.phase == PHASE_APPROVAL
    series = row.metrics_pre["series"]
    assert (
        row.metrics_pre["days"][0] == "2026-09-28" and row.metrics_pre["days"][-1] == "2026-10-11"
    )
    assert len(series["gmv"]) == 14 and series["gmv"][-1] == 100.0
    assert series["impressions"][-1] == 1000.0  # from A34_TOTAL
    assert series["add_cart_count"][0] == 3.0
    assert row.price["min_list_price"] == "72000" and row.price["source"] == "snapshot"
    assert [p["activity_id"] for p in row.active_promotions] == ["a1"]
    assert row.content_hash and row.quality_score is None
    # Idempotent per (run, phase); the execution phase is its own row.
    assert (
        await capture_run_baseline(
            session,
            shop_id=shop.id,
            workflow_run_id=run.id,
            product_id=product.id,
            phase=PHASE_APPROVAL,
            now=NOW,
        )
        is None
    )
    execution = await capture_run_baseline(
        session,
        shop_id=shop.id,
        workflow_run_id=run.id,
        product_id=product.id,
        phase=PHASE_EXECUTION,
        now=NOW + timedelta(minutes=2),
    )
    assert execution is not None and execution.phase == PHASE_EXECUTION


def test_pre_series_skips_window_rows():
    day = date(2026, 10, 11)
    window_row = SimpleNamespace(
        start_date=day - timedelta(days=6),
        end_date=day + timedelta(days=1),
        impressions=1,
        clicks=1,
        traffic_breakdown=None,
        conversion_rate=None,
        click_to_order_rate=None,
        gmv=Decimal(9),
    )
    out = pre_series([window_row], [day - timedelta(days=6)])
    assert out["series"]["gmv"] == [None]


@pytest.mark.asyncio
async def test_approve_route_enqueues_the_approval_baseline(monkeypatch):
    from juli_backend.api.routes import demo_execution
    from juli_backend.workers.tasks import product_history as tasks

    seen: list[tuple] = []
    monkeypatch.setattr(tasks, "enqueue_run_baseline", lambda *args: seen.append(args) or "t")
    shop_id, run_id = uuid.uuid4(), uuid.uuid4()
    assert demo_execution._enqueue_approval_baseline(shop_id, run_id) == "t"
    assert seen[0][:3] == (shop_id, run_id, PHASE_APPROVAL)
    source = Path(demo_execution.__file__).read_text(encoding="utf-8")
    body = source.split("async def approve_demo_decision")[1]
    # After the commit and the run enqueue, never inside the approval transaction.
    assert body.index("await session.commit()") < body.index("_enqueue_approval_baseline(")


@pytest.mark.asyncio
async def test_baseline_task_body_and_execution_hook(factory, seeded, monkeypatch):
    from juli_backend.workers.tasks import agent_workflow
    from juli_backend.workers.tasks.product_history import run_capture_baseline

    async with factory() as session:
        shop = await session.get(Shop, seeded.id)
        product = await make_product(session, shop, tiktok_product_id="p1")
        run = await make_workflow_run(session, shop, product=product)
        await session.commit()
    assert await run_capture_baseline(
        str(seeded.id), str(run.id), PHASE_APPROVAL, NOW.isoformat(), session_factory=factory
    )
    monkeypatch.setattr(agent_workflow, "_shop_scoped_session_factory", lambda _shop: factory)
    await agent_workflow._capture_execution_baseline(run)
    async with factory() as session:
        phases = (
            await session.execute(
                select(RunBaseline.phase, RunBaseline.captured_at).where(
                    RunBaseline.workflow_run_id == run.id
                )
            )
        ).all()
    assert sorted(p for p, _ in phases) == [PHASE_APPROVAL, PHASE_EXECUTION]
    assert dict(phases)[PHASE_APPROVAL] == NOW


# -- overlap annotation ----------------------------------------------------------------------


async def _change(session, shop_id, pid, kind, at, *, juli=False, key=None, fields=("title",)):
    session.add(
        ExternalChange(
            shop_id=shop_id,
            tiktok_product_id=pid,
            kind=kind,
            fields=list(fields),
            occurred_at=at,
            detected_at=at,
            source="webhook_15",
            juli_write=juli,
            dedup_key=key or uuid.uuid4().hex,
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_overlap_service_excludes_juli_writes_and_other_products(session):
    _, shop = await make_tenant(session)
    start, end = NOW - timedelta(days=14), NOW
    await _change(session, shop.id, "p1", KIND_CONTENT, NOW - timedelta(days=2))
    await _change(session, shop.id, "p1", KIND_CONTENT, NOW - timedelta(days=1), juli=True)
    await _change(
        session, shop.id, None, KIND_PROMOTION, NOW - timedelta(days=3), fields=("start",)
    )
    await _change(session, shop.id, "p2", KIND_PRICE, NOW - timedelta(days=2))
    await _change(session, shop.id, "p1", KIND_PRICE, NOW - timedelta(days=30))
    out = await external_changes_overlapping(session, shop.id, "p1", start, end)
    assert [(c.kind, c.tiktok_product_id) for c in out] == [
        (KIND_PROMOTION, None),
        (KIND_CONTENT, "p1"),
    ]
    assert out[1].to_json() == {
        "kind": "content",
        "fields": ["title"],
        "occurred_at": (NOW - timedelta(days=2)).isoformat(),
        "source": "webhook_15",
    }


def test_measurement_window_from_body():
    body = {"stage": "day7", "dates": {"day7": "2026-10-10", "day14": "2026-10-17"}}
    start, end = measurement_window(body)
    # day0 = 10-03; pre starts 09-19 00:00 UTC+7; day7 ends 10-11 00:00 UTC+7.
    assert start == datetime(2026, 9, 18, 17, 0) and end == datetime(2026, 10, 10, 17, 0)
    final = measurement_window({**body, "stage": "final"})
    assert final[1] == datetime(2026, 10, 17, 17, 0)
    assert measurement_window({"stage": "waiting"}) is None


@pytest.mark.asyncio
async def test_measurement_api_adds_external_changes_without_touching_the_verdict(
    session, monkeypatch
):
    from juli_backend.api.routes import demo_run_flows
    from juli_backend.services import lever_flows

    _, shop = await make_tenant(session)
    product = await make_product(session, shop, tiktok_product_id="p1")
    run = await make_workflow_run(session, shop, product=product)
    verdict = {
        "stage": "final",
        "dates": {"day7": "2026-10-10", "day14": "2026-10-17"},
        "final": {"label": "dat"},
    }

    async def fake_measure(_session, _shop_id, _run):
        return dict(verdict)

    monkeypatch.setattr(lever_flows, "measure_run", fake_measure)
    await _change(session, shop.id, "p1", KIND_CONTENT, datetime(2026, 10, 5, 2, 0))
    await _change(session, shop.id, "p1", KIND_CONTENT, datetime(2026, 10, 6, 2, 0), juli=True)
    body = await demo_run_flows.get_run_measurement(run_id=run.id, shop=shop, session=session)
    assert body["final"] == {"label": "dat"} and body["stage"] == "final"
    assert body["external_changes"] == [
        {
            "kind": "content",
            "fields": ["title"],
            "occurred_at": "2026-10-05T02:00:00",
            "source": "webhook_15",
        }
    ]


def test_beat_schedules_the_daily_fanout():
    from celery.schedules import crontab

    from juli_backend.workers.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["product-history-fanout"]
    assert entry["task"] == "juli_backend.product_history_fanout"
    assert entry["schedule"] == crontab(hour=20, minute=53)


@pytest.mark.asyncio
async def test_fanout_enqueues_shops_past_their_fast_phase():
    from juli_backend.workers.tasks.product_history import run_fanout

    shops = [
        SimpleNamespace(shop_id=uuid.uuid4(), fast_done=True),
        SimpleNamespace(shop_id=uuid.uuid4(), fast_done=False),
    ]
    seen: list[str] = []

    async def enumerate_fn(_session):
        return shops

    assert await run_fanout(None, enqueue=seen.append, enumerate_fn=enumerate_fn) == 1
    assert seen == [str(shops[0].shop_id)]


@pytest.mark.asyncio
async def test_latest_snapshots_picks_the_newest_per_product(session):
    _, shop = await make_tenant(session)
    await _record(session, shop.id, _detail("p1"), baseline=True, now=NOW - timedelta(days=2))
    first = (await latest_snapshots(session, shop.id))["p1"]
    await _record(session, shop.id, _detail("p1", title="B"), previous=first, now=NOW)
    assert (await latest_snapshots(session, shop.id))["p1"].title == "B"
    assert (await latest_snapshots(session, shop.id, ["p2"])) == {}


# -- P58-A (D67): promotion epochs from the 2026-10-19 production sweep ------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1_791_000_000, datetime(2026, 10, 3, 4, 0)),
        ("1791000000", datetime(2026, 10, 3, 4, 0)),
        (" 1791000000 ", datetime(2026, 10, 3, 4, 0)),
        (1_791_000_000.0, datetime(2026, 10, 3, 4, 0)),
        ("1791000000.5", datetime(2026, 10, 3, 4, 0)),
        # Milliseconds, as Search Activities' create/update times arrive in production.
        (1_791_000_000_123, datetime(2026, 10, 3, 4, 0)),
        ("1791000000123", datetime(2026, 10, 3, 4, 0)),
        (1_791_000_000_123_456, datetime(2026, 10, 3, 4, 0)),  # µs
        (1_791_000_000_123_456_789, datetime(2026, 10, 3, 4, 0)),  # ns
        # Open-ended / missing / junk: None, never an exception.
        (0, None),
        ("0", None),
        (-1, None),
        (None, None),
        ("", None),
        ("  ", None),
        (True, None),
        (False, None),
        ("abc", None),
        ("NaN", None),
        ("Infinity", None),
        ({"seconds": 1791000000}, None),
        ([1791000000], None),
        (10**40, None),
        ("1e400", None),
    ],
)
def test_epoch_to_naive_utc_accepts_tiktok_shapes_and_never_raises(value, expected):
    from juli_backend.services.product_history.normalize import epoch_to_naive_utc

    assert epoch_to_naive_utc(value) == expected


def _ms(moment: datetime) -> int:
    return _epoch(moment) * 1000


@pytest.mark.asyncio
async def test_promotion_sweep_survives_millisecond_and_open_ended_times(factory, seeded):
    """The 2026-10-19 crash: a ms ``update_time`` aborted the shop's first sweep."""
    fake = FakeResources()
    fake.activities = {
        # Search Activities row as seen in production: ms create / update times.
        "7436000000000000001": _activity(
            "7436000000000000001",
            "ONGOING",
            create_time=_ms(NOW) - 2 * 86_400_000,
            update_time=_ms(NOW) - 86_400_000,
        ),
        # String seconds; an open-ended end_time sent as 0.
        "7436000000000000002": _activity(
            "7436000000000000002",
            "ONGOING",
            begin_time=str(_epoch(NOW) - 3600),
            end_time=0,
            create_time="",
            update_time=None,
        ),
    }
    resources = await _resources(factory, seeded.id, fake)

    result = await history_job.sweep_promotions(factory, seeded.id, resources, now=NOW)
    assert result.backfill and result.activities == 2 and result.skipped == []
    async with factory() as session:
        stored = {
            row.activity_id: row
            for row in (
                await session.execute(
                    select(PromotionActivity).where(PromotionActivity.shop_id == seeded.id)
                )
            ).scalars()
        }
    ms_row = stored["7436000000000000001"]
    assert ms_row.tiktok_update_time == NOW - timedelta(days=1)
    assert ms_row.tiktok_create_time == NOW - timedelta(days=2)
    open_row = stored["7436000000000000002"]
    assert open_row.begin_time == NOW - timedelta(hours=1)
    assert open_row.end_time is None and open_row.tiktok_create_time is None


@pytest.mark.asyncio
async def test_one_bad_promotion_is_logged_and_skipped_not_the_sweep(
    factory, seeded, monkeypatch, caplog
):
    fake = FakeResources()
    fake.activities = {
        "good": _activity("good", "ONGOING"),
        "bad": _activity("bad", "ONGOING"),
    }
    fake.activity_details = {"good": _activity_detail("p1"), "bad": _activity_detail("p2")}
    real = promo.upsert_activity

    async def flaky(session, shop_id, raw, *, now):
        if promo.activity_id_of(raw) == "bad":
            await real(session, shop_id, raw, now=now)  # dirty the savepoint first
            raise ValueError("unexpected activity payload")
        return await real(session, shop_id, raw, now=now)

    monkeypatch.setattr(promo, "upsert_activity", flaky)
    resources = await _resources(factory, seeded.id, fake)

    with caplog.at_level("WARNING", logger=history_job.logger.name):
        result = await history_job.sweep_promotions(factory, seeded.id, resources, now=NOW)

    assert result.skipped == ["bad"]
    skipped = [r for r in caplog.records if r.getMessage() == "product_history_promotion_skipped"]
    assert [(r.activity_id, r.stage, r.error_type) for r in skipped] == [
        ("bad", "listed", "ValueError")
    ]
    assert fake.count("get_activity") == 1  # only the stored one is read
    async with factory() as session:
        ids = set(
            (
                await session.execute(
                    select(PromotionActivity.activity_id).where(
                        PromotionActivity.shop_id == seeded.id
                    )
                )
            ).scalars()
        )
        products = list(
            (
                await session.execute(
                    select(PromotionActivityProduct.tiktok_product_id).where(
                        PromotionActivityProduct.shop_id == seeded.id
                    )
                )
            ).scalars()
        )
    assert ids == {"good"} and products == ["p1"]
