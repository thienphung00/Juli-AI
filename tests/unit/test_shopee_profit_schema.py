"""ADR-120, migration 112: Shopee profit and history tables.

On the unit substrate (source text + SQLite):

- the chain: revision id fits ``alembic_version`` (32), sits on 111, the deferred tail
  moved onto it, the additive gate accepts it;
- vocabularies match the models and every model column is created by the migration;
- classification: five tenant-direct tables, the fee formulas ``non_tenant``;
- grants: append-only tables get SELECT, INSERT only; order lines also UPDATE;
- PII-free by construction: ``shopee_order_lines`` has no buyer / phone / address column;
- ``card_events`` accepts ``whatif_adjusted`` and it is not a single-per-card event;
- ``shop_keyword_seeds`` gains ``role`` / ``item_scope``;
- the keys and CHECKs hold on SQLite.

The Postgres proof (RLS, grants, up / down) is ``tests/integration/test_shopee_profit_db.py``.
Synthetic fixtures only.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from juli_backend.database.tenant_scoped_tables import (
    TABLE_CLASSIFICATION_MAP,
    get_tenant_scoped_tables,
)
from juli_backend.models import card_events as card_models
from juli_backend.models import shop_keywords as seed_models
from juli_backend.models import shopee_profit as models
from juli_backend.models.run_changes import ShopRuleVersion
from juli_backend.models.shop_keywords import ShopKeywordSeed
from juli_backend.models.shopee_profit import (
    AdCampaignPurpose,
    PlatformFeeFormula,
    PlatformItemSnapshot,
    ProductImageAsset,
    ShopeeOrderLine,
)
from juli_backend.orm_base import Base

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "backend/src/juli_backend/database/migrations"
MIGRATION = MIGRATIONS / "versions/112_shopee_profit_and_history.py"
LATER_MIGRATION = MIGRATIONS / "versions/113_shopee_orders_and_logs.py"
KOL_MIGRATION = MIGRATIONS / "versions/118_shopee_kol_lines.py"  # P91 D-9
INCOME_MIGRATION = MIGRATIONS / "versions/119_shopee_order_income.py"
BACKFILL = MIGRATIONS / "deferred/101_write_mode_backfill.py"
NOW = datetime(2026, 11, 3, 3, 0)

TENANT_TABLES = {
    "platform_item_snapshots": PlatformItemSnapshot,
    "product_image_assets": ProductImageAsset,
    "shopee_order_lines": ShopeeOrderLine,
    "shop_rule_versions": ShopRuleVersion,
    "ad_campaign_purposes": AdCampaignPurpose,
}


def _module():
    spec = importlib.util.spec_from_file_location("mig112", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _created_columns(source: str) -> set[str]:
    """Column names the migration creates; ``shop_id`` and ``created_at`` come from helpers."""
    found = set(re.findall(r'sa\.Column\(\s*"(\w+)"', source))
    if "_shop_column()" in source:
        found.add("shop_id")
    if "_created_at()" in source:
        found.add("created_at")
    return found


def _added_columns(source: str) -> set[str]:
    """Columns a later migration adds with ``op.add_column(<table>, sa.Column("x" ...``."""
    return set(re.findall(r'op\.add_column\(\s*LINES_TABLE,\s*sa\.Column\(\s*"(\w+)"', source))


def _income_added_columns() -> set[str]:
    """Migration 119 (P91 D-12) adds ``variation_name`` with ``op.add_column(LINES, ...``."""
    source = INCOME_MIGRATION.read_text("utf-8")
    return set(re.findall(r'op\.add_column\(\s*LINES,\s*sa\.Column\(\s*"(\w+)"', source))


def _upgrade_body() -> str:
    return MIGRATION.read_text("utf-8").split("def upgrade")[1].split("def downgrade")[0]


# =========================================================================== chain


def test_migration_112_fits_alembic_and_the_deferred_tail_moved_onto_it():
    mig = _module()
    assert mig.revision == "112_shopee_profit_and_history" and len(mig.revision) <= 32
    assert mig.down_revision == "111_shopee_keywords"
    # P90 step 2's 113 went on 112 and took the deferred tail.
    later = LATER_MIGRATION.read_text("utf-8")
    assert f'down_revision: str | None = "{mig.revision}"' in later
    assert 'down_revision: str | None = "122_shopee_affiliate_lines"' in BACKFILL.read_text("utf-8")


def test_the_additive_gate_accepts_migration_112():
    sys.path.insert(0, str(REPO / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([MIGRATION])
    assert [finding.render() for finding in result.findings] == []
    assert result.accepted is True


def test_the_only_drop_in_upgrade_is_the_card_events_check_recreated_wider():
    body = _upgrade_body()
    widen = 'op.drop_constraint(EVENT_TYPE_CHECK, EVENTS_TABLE, type_="check")'
    assert body.count(widen) == 1
    assert "op.create_check_constraint(\n        EVENT_TYPE_CHECK" in body
    for verb in ("op.alter_column", "UPDATE public", "DELETE FROM", "DROP "):
        assert verb not in body, verb
    assert body.replace(widen, "").count("op.drop_") == 0


def test_downgrade_drops_every_new_table_and_column():
    down = MIGRATION.read_text("utf-8").split("def downgrade")[1]
    assert "op.drop_column(SEEDS_TABLE" in down
    assert "FORMULAS_TABLE" in down and "TENANT_VERBS" in down and "op.drop_table(table)" in down
    # The narrower CHECK comes back NOT VALID, so rows written meanwhile survive.
    assert "NOT VALID" in down


# =========================================================================== vocabularies


def test_migration_vocabularies_match_the_models():
    mig = _module()
    assert mig.PLATFORMS == models.PLATFORMS
    assert mig.PROMO_KINDS == models.PROMO_KINDS
    assert mig.AD_PURPOSES == models.AD_PURPOSES
    assert mig.SET_BY == models.SET_BY
    assert mig.SEED_ROLES == seed_models.ROLES
    # 114 (P90 assisted execution) appended verified / mismatch / not_seen to the model.
    assert mig.EVENT_TYPES == card_models.EVENT_TYPES[: len(mig.EVENT_TYPES)]
    assert mig.EVENT_TYPES[-1] == "whatif_adjusted"


@pytest.mark.parametrize(
    "model", [*TENANT_TABLES.values(), PlatformFeeFormula], ids=lambda m: m.__tablename__
)
def test_every_model_column_is_created_by_the_migration(model):
    source = MIGRATION.read_text("utf-8")
    created = _created_columns(source)
    if model is ShopeeOrderLine:
        # Migration 113 adds the order-export columns to this table, 118 the KOL, 119 the
        # variation name.
        created |= (
            _added_columns(LATER_MIGRATION.read_text("utf-8"))
            | _added_columns(KOL_MIGRATION.read_text("utf-8"))
            | _income_added_columns()
        )
    for column in model.__table__.columns.keys():
        assert column in created, f"{model.__tablename__}.{column}"
    for column in ("role", "item_scope"):
        assert column in _created_columns(source)


def test_shop_rule_version_fits_the_rule_columns():
    from juli_backend.models.run_changes import ShopRule

    shared = {"shop_id", "rule_key", "scope_ref", "value", "set_by", "set_by_user_id"}
    assert shared <= set(ShopRuleVersion.__table__.columns.keys())
    assert shared <= set(ShopRule.__table__.columns.keys())


# =========================================================================== lanes and grants


def test_the_client_tables_are_tenant_direct_and_the_formulas_are_non_tenant():
    tenant = {table for _schema, table in get_tenant_scoped_tables()}
    for name, model in TENANT_TABLES.items():
        assert TABLE_CLASSIFICATION_MAP[("public", name)] == "tenant_direct", name
        assert name in tenant
        assert "shop_id" in model.__table__.columns
    assert TABLE_CLASSIFICATION_MAP[("public", "platform_fee_formulas")] == "non_tenant"
    assert "shop_id" not in PlatformFeeFormula.__table__.columns


def test_grants_follow_the_lanes():
    mig = _module()
    assert mig.TENANT_VERBS == {
        "platform_item_snapshots": "SELECT, INSERT",
        "product_image_assets": "SELECT, INSERT",
        "shopee_order_lines": "SELECT, INSERT, UPDATE",
        "shop_rule_versions": "SELECT, INSERT",
        "ad_campaign_purposes": "SELECT, INSERT",
    }
    body = _upgrade_body()
    assert "_secure_reference(FORMULAS_TABLE)" in body
    assert "for table, verbs in TENANT_VERBS.items()" in body
    source = MIGRATION.read_text("utf-8")
    assert "GRANT SELECT ON public.{table} TO {APP_ROLE}" in source
    assert "GRANT SELECT, INSERT, UPDATE ON public.{table} TO {OPS_ROLE}" in source
    assert "DELETE" not in re.sub(r"DELETE FROM|ON DELETE", "", source.split("def _revoke")[0])


# =========================================================================== no buyer PII


def test_order_lines_have_no_column_that_could_hold_a_buyer():
    forbidden = ("buyer", "name", "phone", "address", "email", "recipient", "customer", "tel")
    columns = ShopeeOrderLine.__table__.columns.keys()
    # ``buyer_shipping_fee`` (migration 113) is an AMOUNT the buyer paid, not a buyer field;
    # ``variation_name`` (migration 119) is the product's variation ("Combo 3 hộp"), not a person.
    allowed = {"buyer_shipping_fee", "variation_name"}
    assert [c for c in columns if c not in allowed and any(w in c for w in forbidden)] == []
    source = (
        MIGRATION.read_text("utf-8").split("def _create_lines")[1].split("def _create_formulas")[0]
    )
    added = (
        _added_columns(LATER_MIGRATION.read_text("utf-8"))
        | _added_columns(KOL_MIGRATION.read_text("utf-8"))
        | _income_added_columns()
    )
    assert added and added.isdisjoint(_created_columns(source))
    assert _created_columns(source) | added == set(columns)


# =========================================================================== card events


def test_whatif_adjusted_is_an_event_type_but_not_single_per_card():
    assert card_models.EVENT_WHATIF_ADJUSTED == "whatif_adjusted"
    assert "whatif_adjusted" in card_models.EVENT_TYPES
    assert "whatif_adjusted" not in card_models.SINGLE_PER_CARD_EVENT_TYPES
    assert "whatif_adjusted" not in card_models.CARDLESS_EVENT_TYPES
    assert "'whatif_adjusted'" in card_models.CK_EVENT_TYPE


# =========================================================================== SQLite behaviour


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    from juli_backend.models import IngestRawPayload, Shop

    Base.metadata.create_all(
        engine,
        tables=[
            Shop.__table__,
            IngestRawPayload.__table__,
            *(m.__table__ for m in TENANT_TABLES.values()),
            PlatformFeeFormula.__table__,
            ShopKeywordSeed.__table__,
        ],
    )
    with Session(engine) as s:
        yield s


def _line(shop_id: uuid.UUID, **kw) -> ShopeeOrderLine:
    base = {
        "shop_id": shop_id,
        "platform": "shopee",
        "order_ref": "h" * 64,
        "line_no": 1,
        "ordered_at": NOW,
        "status": "completed",
        "item_id": "1001",
        "qty": 2,
        "original_price": Decimal("200000"),
        "deal_price": Decimal("190000"),
        "source": "upload",
        "source_version": "t1",
    }
    return ShopeeOrderLine(**{**base, **kw})


def test_an_order_line_key_is_unique_and_a_line_number_makes_a_new_row(session):
    shop = uuid.uuid4()
    session.add(_line(shop))
    session.add(_line(shop, line_no=2))
    session.commit()
    session.add(_line(shop))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    row = session.scalars(select(ShopeeOrderLine).where(ShopeeOrderLine.line_no == 1)).one()
    assert row.promo_kind == "none" and row.affiliate is False and row.commission is None
    assert row.shop_voucher_share == 0 and row.variation_id == ""


def test_an_order_line_refuses_an_unknown_promo_kind(session):
    session.add(_line(uuid.uuid4(), promo_kind="coupon"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_a_snapshot_instant_is_unique_per_item_and_variation(session):
    shop = uuid.uuid4()

    def snap(**kw):
        return PlatformItemSnapshot(
            shop_id=shop,
            platform="shopee",
            item_id="1001",
            captured_at=NOW,
            source="upload",
            source_rank=2,
            **kw,
        )

    session.add_all([snap(), snap(variation_id="v1")])
    session.commit()
    session.add(snap(title="x"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_an_image_hash_is_unique_per_shop_only(session):
    a, b = uuid.uuid4(), uuid.uuid4()
    for shop in (a, b):
        session.add(
            ProductImageAsset(shop_id=shop, image_hash="abc", storage_path="p", first_seen_at=NOW)
        )
    session.commit()
    session.add(ProductImageAsset(shop_id=a, image_hash="abc", storage_path="q", first_seen_at=NOW))
    with pytest.raises(IntegrityError):
        session.commit()


def test_a_launch_purpose_needs_a_cap_and_an_end_date(session):
    shop = uuid.uuid4()

    def purpose(**kw):
        return AdCampaignPurpose(
            shop_id=shop,
            platform="shopee",
            campaign_key="c1",
            set_by="team",
            set_at=NOW,
            **kw,
        )

    session.add(purpose(purpose="ra_mat", budget_cap_daily=Decimal("50000")))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    session.add(
        purpose(purpose="ra_mat", budget_cap_daily=Decimal("50000"), ends_on=date(2026, 12, 1))
    )
    session.commit()


def test_a_purpose_history_keeps_every_row_and_the_latest_wins(session):
    shop = uuid.uuid4()
    for hour, name in ((1, "hien_thi"), (2, "chuyen_doi")):
        session.add(
            AdCampaignPurpose(
                shop_id=shop,
                platform="shopee",
                campaign_key="c1",
                purpose=name,
                set_by="seller",
                set_at=datetime(2026, 11, 3, hour),
            )
        )
    session.commit()
    latest = session.scalars(
        select(AdCampaignPurpose).order_by(AdCampaignPurpose.set_at.desc()).limit(1)
    ).one()
    assert latest.purpose == "chuyen_doi"
    assert len(session.scalars(select(AdCampaignPurpose)).all()) == 2


def test_rule_versions_are_unique_per_scope_and_version(session):
    shop = uuid.uuid4()

    def version(n, scope=""):
        return ShopRuleVersion(
            shop_id=shop,
            rule_key="max_discount",
            scope_ref=scope,
            value={"pct": 9},
            version=n,
            set_by="seller",
            valid_from=NOW,
        )

    session.add_all([version(1), version(2), version(1, scope="1001")])
    session.commit()
    session.add(version(2))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    session.add(version(0, scope="x"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_fee_formula_versions_are_unique_per_category_and_start(session):
    def formula(**kw):
        return PlatformFeeFormula(
            platform="shopee",
            category_path=["Nhà cửa"],
            effective_from=date(2026, 1, 1),
            components=[{"code": "commission", "kind": "pct", "base": "deal_price", "rate": 0.15}],
            **kw,
        )

    session.add(formula())
    session.commit()
    session.add(formula())
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    session.add(formula(effective_to=date(2025, 1, 1)))
    with pytest.raises(IntegrityError):
        session.commit()


def test_a_seed_role_is_optional_and_checked(session):
    shop = uuid.uuid4()

    def seed(keyword, **kw):
        return ShopKeywordSeed(
            shop_id=shop, platform="shopee", keyword=keyword, pattern="type_function", **kw
        )

    session.add(seed("a"))
    session.add(seed("b", role="chinh", item_scope="1001"))
    session.commit()
    legacy = session.scalars(select(ShopKeywordSeed).where(ShopKeywordSeed.keyword == "a")).one()
    assert legacy.role is None and legacy.item_scope is None
    session.add(seed("c", role="boss"))
    with pytest.raises(IntegrityError):
        session.commit()
