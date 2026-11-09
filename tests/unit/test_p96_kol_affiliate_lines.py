"""P96 (migration 122): Phân tích › KOL fills from the Connector's affiliate lines alone.

On the unit substrate (SQLite): every report line is stored on its own; the KOL table builds rows
from them when the order export does not hold the order, uses the export's line when it does (one
source per order, no double count), marks an export line the report reached first, and leaves out
lines the fraud check did not pass. The Postgres proof (RLS, grants, up / down, the same flows under
``juli_app``) is ``tests/integration/test_shopee_affiliate_lines_db.py``.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from juli_backend.database.tenant_scoped_tables import (
    TABLE_CLASSIFICATION_MAP,
    get_tenant_scoped_tables,
)
from juli_backend.models.shopee_profit import ShopeeAffiliateLine
from juli_backend.services.ingest.kol_key import kol_key
from juli_backend.services.ingest.schemas import ShopeeAffiliateOrderLineRow
from juli_backend.services.ingest.writers import write_affiliate_lines
from juli_backend.services.shopee_analytics import kol_affiliate, queries
from tests.support.shopee_analytics import CUR_START, _line, _ref
from tests.support.shopee_reco import AS_OF, seed_reco_shop

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "backend/src/juli_backend/database/migrations"
MIGRATION = MIGRATIONS / "versions/122_shopee_affiliate_lines.py"
BACKFILL = MIGRATIONS / "deferred/101_write_mode_backfill.py"
HANDLE = "kol_moi"
WHEN = datetime.combine(CUR_START, datetime.min.time()) + timedelta(hours=10)


def _module():
    spec = importlib.util.spec_from_file_location("mig122", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _report(n: int, item: str = "1001", **over) -> ShopeeAffiliateOrderLineRow:
    values = {
        "order_ref": _ref(n),
        "item_id": item,
        "price": Decimal(90_000),
        "qty": 1,
        "order_value": Decimal(90_000),
        "ordered_at": WHEN,
        "completed_at": WHEN + timedelta(days=3),
        "order_status": "Đã hoàn thành",
        "affiliate_account": HANDLE,
        "channel": "Shopee Video",
        "campaign_type": "Chiến dịch mở rộng",
        "cost": Decimal(4_500),
        "valid": True,
        **over,
    }
    return ShopeeAffiliateOrderLineRow.model_validate(values)


def _provenance(shop_id) -> dict:
    return {
        "shop_id": shop_id,
        "platform": "shopee",
        "source": "extension",
        "source_version": "0.3.6",
        "raw_payload_id": None,
        "updated_at": datetime(2026, 11, 6, 9, 0),
    }


@pytest.fixture
async def reco_shop(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    return seeded


async def _write(session, shop_id, rows) -> None:
    await write_affiliate_lines(session, rows, None, _provenance(shop_id))
    await session.commit()


def _kol_rows(body: dict, handle: str = HANDLE) -> list[dict]:
    return [r for r in body["rows"] if r["handle"] == handle]


# ------------------------------------------------------------------------- the migration


def test_migration_122_fits_alembic_and_123_follows_it():
    mig = _module()
    assert mig.revision == "122_shopee_affiliate_lines" and len(mig.revision) <= 32
    assert mig.down_revision == "121_shop_members"
    # P97 T2's 123_shopee_metrics_tables sits on 122 and took the deferred tail.
    nxt = (MIGRATION.parent / "123_shopee_metrics_tables.py").read_text("utf-8")
    assert 'down_revision: str | None = "122_shopee_affiliate_lines"' in nxt
    assert 'down_revision: str | None = "125_reco_plan_groups"' in BACKFILL.read_text("utf-8")


def test_the_additive_gate_accepts_migration_122():
    sys.path.insert(0, str(REPO / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([MIGRATION])
    assert [finding.render() for finding in result.findings] == []
    assert result.accepted is True


def test_the_table_is_tenant_direct_with_upsert_grants_and_every_model_column():
    mig = _module()
    assert TABLE_CLASSIFICATION_MAP[("public", "shopee_affiliate_lines")] == "tenant_direct"
    assert ("public", "shopee_affiliate_lines") in set(get_tenant_scoped_tables())
    assert mig.TENANT_VERBS == {"shopee_affiliate_lines": "SELECT, INSERT, UPDATE"}
    source = MIGRATION.read_text("utf-8")
    up = source.split("def upgrade")[1].split("def downgrade")[0]
    for verb in ("op.drop_", "op.alter_column", "UPDATE public", "DELETE FROM"):
        assert verb not in up, verb
    created = set(__import__("re").findall(r'sa\.Column\(\s*"(\w+)"', source))
    assert set(ShopeeAffiliateLine.__table__.columns.keys()) == created


def test_no_column_can_hold_a_buyer():
    forbidden = ("phone", "address", "email", "recipient", "customer", "buyer", "username")
    bad = [
        c for c in ShopeeAffiliateLine.__table__.columns.keys() if any(w in c for w in forbidden)
    ]
    assert bad == []


# ------------------------------------------------------------------------------ the writer


async def test_every_report_line_is_stored_even_without_the_export_and_a_reread_updates_it(
    session, reco_shop
):
    sid = reco_shop.shop_id
    await _write(session, sid, [_report(901), _report(902, valid=False)])
    stored = (await session.execute(select(ShopeeAffiliateLine))).scalars().all()
    assert sorted(s.order_ref for s in stored) == sorted([_ref(901), _ref(902)])
    assert {s.order_ref: s.valid for s in stored}[_ref(902)] is False
    assert all(s.kol_key == kol_key(HANDLE) and s.kol_handle == HANDLE for s in stored)
    # the next day's report moves the refund: same key, one row, updated
    await _write(session, sid, [_report(901, refund_amount=Decimal(90_000))])
    rows = (
        (
            await session.execute(
                select(ShopeeAffiliateLine)
                .where(ShopeeAffiliateLine.order_ref == _ref(901))
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1 and rows[0].refund_amount == Decimal(90_000)


# ----------------------------------------------------------------------------- the KOL table


async def test_kol_rows_come_from_the_report_when_the_export_does_not_hold_the_orders(
    session, reco_shop
):
    sid = reco_shop.shop_id
    await _write(session, sid, [_report(901), _report(902), _report(903)])
    body = await queries.kol_table(session, sid, as_of=AS_OF)
    (row,) = _kol_rows(body)
    assert (row["orders"], row["units"], row["gmv"], row["commission"]) == (3, 3, 270_000, 13_500)
    assert row["channel"] == "Shopee Video" and row["item_id"] == "1001"


async def test_an_order_in_the_export_is_counted_once_from_the_export_line(session, reco_shop):
    sid = reco_shop.shop_id
    export = _line(sid, 950, CUR_START, "G1", deal=80_000, affiliate=True, commission=4_000)
    export.kol_key, export.kol_handle = kol_key(HANDLE), HANDLE
    export.affiliate_channel = "Shopee Video"
    session.add(export)
    await session.commit()
    await _write(session, sid, [_report(950)])  # the same order, in the report too
    body = await queries.kol_table(session, sid, as_of=AS_OF)
    (row,) = _kol_rows(body)
    assert row["orders"] == 1 and row["gmv"] == 80_000  # the export's line, not 2 orders


async def test_an_export_line_the_report_reached_first_is_marked_from_the_report(
    session, reco_shop
):
    sid = reco_shop.shop_id
    session.add(_line(sid, 960, CUR_START, "G1", deal=80_000))  # export written after: no mark
    await session.commit()
    await _write(session, sid, [_report(960)])
    body = await queries.kol_table(session, sid, as_of=AS_OF)
    (row,) = _kol_rows(body)
    assert row["orders"] == 1 and row["gmv"] == 80_000


async def test_a_line_the_fraud_check_rejected_never_counts(session, reco_shop):
    sid = reco_shop.shop_id
    await _write(session, sid, [_report(970, valid=False)])
    body = await queries.kol_table(session, sid, as_of=AS_OF)
    assert _kol_rows(body) == []


def test_report_statuses_map_to_the_profit_engine():
    def line(**over):
        base = {
            "order_ref": "r",
            "line_no": 0,
            "item_id": "1001",
            "model_id": "",
            "price": Decimal(1),
            "qty": 1,
            "order_value": Decimal(1),
            "refund_amount": None,
            "commission": None,
            "valid": True,
            "order_status": "Đang xử lý",
            "ordered_at": WHEN,
            "completed_at": None,
            "kol_key": None,
            "kol_handle": None,
            "channel": None,
            "campaign_type": None,
            "mcn": None,
        }
        return kol_affiliate.AffiliateLine(**{**base, **over})

    status = kol_affiliate.status_of
    assert status(line()).value == "in_transit"
    assert status(line(order_status="Đã hủy")).value == "cancelled"
    assert status(line(completed_at=WHEN)).value == "delivered"
    assert status(line(refund_amount=Decimal(1))).value == "refunded_accepted"
