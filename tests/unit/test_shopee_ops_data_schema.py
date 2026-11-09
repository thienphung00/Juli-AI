"""ADR-117, migration 108: Shopee Seller Centre files, contract KPIs, the public market lane.

On the unit substrate (source text + SQLite):

- the chain: revision id fits ``alembic_version`` (32), sits on 107, and the deferred tail
  (101 -> 074) moved onto it;
- the additive deploy gate accepts it, and its upgrade only adds;
- every model column is created by the migration and the vocabularies match the models;
- classification: the four client-lane tables are tenant-direct, the KPI / lever /
  forecast and public-market tables are Ops-only, and ``juli_app`` is never granted an
  Ops-only table;
- the public-lane tables carry no ``shop_id``;
- the new keys hold on SQLite: a period row and a daily row never share a table, a
  duplicate key is refused, a variation and its item are different rows.

The Postgres proof (RLS, grants, round trip) is
``tests/integration/test_shopee_ops_data_db.py``. Synthetic fixtures only.
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
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP
from juli_backend.models.ingest import ORDER_TYPE_NONE, ORDER_TYPES, PLATFORMS, PlatformDailyMetric
from juli_backend.models.kpi_contracts import (
    CONTRACT_STATUSES,
    TARGET_ROLES,
    KpiAdjustment,
    KpiContract,
    KpiExclusion,
    KpiForecast,
    KpiTarget,
    LeverPlan,
)
from juli_backend.models.market import MarketKeywordSnapshot, MarketListingSnapshot
from juli_backend.models.platform_data import (
    PRODUCT_FLAGS,
    PlatformItem,
    PlatformPeriodMetric,
    PlatformProductFlag,
    PlatformPromotion,
)
from juli_backend.orm_base import Base

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "backend/src/juli_backend/database/migrations"
MIGRATION = MIGRATIONS / "versions/108_shopee_ops_data.py"
BACKFILL = MIGRATIONS / "deferred/101_write_mode_backfill.py"

TENANT_MODELS = (PlatformPeriodMetric, PlatformItem, PlatformProductFlag, PlatformPromotion)
OPS_MODELS = (KpiContract, KpiTarget, KpiAdjustment, KpiExclusion, LeverPlan, KpiForecast)
PUBLIC_MODELS = (MarketListingSnapshot, MarketKeywordSnapshot)


def _module():
    spec = importlib.util.spec_from_file_location("mig108", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _upgrade_body() -> str:
    return MIGRATION.read_text("utf-8").split("def upgrade")[1].split("def downgrade")[0]


# =========================================================================== migration 108


def test_migration_108_fits_alembic_and_the_deferred_tail_moved_onto_it():
    mig = _module()
    assert mig.revision == "108_shopee_ops_data" and len(mig.revision) <= 32
    assert mig.down_revision == "107_ops_pooled_consent"
    # ADR-118 put `109_shop_proposals` on 108; the deferred tail moved onto 109.
    later = (MIGRATIONS / "versions/109_shop_proposals.py").read_text("utf-8")
    assert f'down_revision: str | None = "{mig.revision}"' in later
    assert 'down_revision: str | None = "122_shopee_affiliate_lines"' in BACKFILL.read_text("utf-8")


def test_the_additive_gate_accepts_migration_108():
    sys.path.insert(0, str(REPO / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([MIGRATION])
    assert [finding.render() for finding in result.findings] == []
    assert result.accepted is True
    assert result.inspected == ["108_shopee_ops_data"]


def test_the_upgrade_only_adds():
    body = _upgrade_body()
    for verb in ("op.drop_", "op.alter_column", "UPDATE public", "DELETE FROM", "DROP "):
        assert verb not in body, verb


def test_mapper_version_is_a_nullable_column_on_the_daily_table():
    source = MIGRATION.read_text("utf-8")
    assert (
        'op.add_column(DAILY_TABLE, sa.Column("mapper_version", sa.SmallInteger(), nullable=True))'
        in source
    )
    assert "mapper_version" in PlatformDailyMetric.__table__.columns
    assert PlatformDailyMetric.__table__.columns["mapper_version"].nullable


def test_migration_vocabularies_match_the_models():
    mig = _module()
    assert mig.PLATFORMS == PLATFORMS
    assert mig.ORDER_TYPES == (ORDER_TYPE_NONE, *ORDER_TYPES)
    assert mig.FLAGS == PRODUCT_FLAGS
    assert mig.CONTRACT_STATUSES == CONTRACT_STATUSES
    assert mig.TARGET_ROLES == TARGET_ROLES


@pytest.mark.parametrize("model", TENANT_MODELS + OPS_MODELS + PUBLIC_MODELS)
def test_every_model_column_is_created_by_the_migration(model):
    """The two lists must agree, or SQLite-backed tests pass over a schema Postgres lacks."""
    source = MIGRATION.read_text("utf-8")
    shared = {
        "extra",
        "source",
        "source_rank",
        "source_version",
        "mapper_version",
        "raw_payload_id",
        "captured_at",
        "created_at",
        "updated_at",
    }
    metric = {
        "impressions",
        "clicks",
        "ctr",
        "orders",
        "gmv",
        "buyers",
        "visitors",
        "add_to_cart",
        "units",
        "page_views",
        "bounce_rate",
    }
    for column in model.__table__.columns.keys():
        if model in TENANT_MODELS and column in shared:
            assert f'sa.Column("{column}"' in source  # _source_columns()
            continue
        if model is PlatformPeriodMetric and column in metric:
            assert f'sa.Column("{column}"' in source  # _metric_columns()
            continue
        assert f'sa.Column("{column}"' in source, f"{model.__tablename__}.{column}"


def test_migration_and_models_name_the_same_tables():
    mig = _module()
    migrated = set(mig.TENANT_GRANTS) | set(mig.OPS_GRANTS)
    modelled = {m.__tablename__ for m in TENANT_MODELS + OPS_MODELS + PUBLIC_MODELS}
    assert migrated == modelled


# =========================================================================== classification


def test_client_lane_tables_are_tenant_direct_and_granted_to_the_app():
    mig = _module()
    for model in TENANT_MODELS:
        name = model.__tablename__
        assert TABLE_CLASSIFICATION_MAP[("public", name)] == "tenant_direct"
        assert "shop_id" in model.__table__.columns
        assert mig.TENANT_GRANTS[name] == "SELECT, INSERT, UPDATE"


def test_ops_tables_are_ops_only_and_the_app_role_is_never_granted_them():
    mig = _module()
    for model in OPS_MODELS + PUBLIC_MODELS:
        assert TABLE_CLASSIFICATION_MAP[("public", model.__tablename__)] == "ops_only"
        assert model.__tablename__ in mig.OPS_GRANTS
    source = MIGRATION.read_text("utf-8")
    ops_helper = source.split("def _secure_ops")[1].split("def upgrade")[0]
    assert "GRANT {verbs} ON public.{table} TO {OPS_ROLE}" in ops_helper
    assert "TO {APP_ROLE}" not in ops_helper
    assert "FOR ALL TO {OPS_ROLE}" in ops_helper


def test_append_only_ops_tables_get_no_update_or_delete():
    mig = _module()
    for table in ("kpi_targets", "kpi_adjustments", "kpi_exclusions", "kpi_forecasts"):
        assert mig.OPS_GRANTS[table] == "SELECT, INSERT", table
    assert "DELETE" not in mig.OPS_GRANTS["kpi_contracts"]


def test_public_lane_tables_carry_no_shop_id():
    for model in PUBLIC_MODELS:
        columns = set(model.__table__.columns.keys())
        assert "shop_id" not in columns, model.__tablename__
    assert "platform_shop_id" in MarketListingSnapshot.__table__.columns


def test_rank_is_not_a_listing_column():
    """D61.9: ``page`` / ``pos`` are provenance; there is no ``rank`` to model on."""
    assert "rank" not in MarketListingSnapshot.__table__.columns
    assert not re.search(r'sa\.Column\("rank"', MIGRATION.read_text("utf-8"))


# =========================================================================== keys on SQLite


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    tables = [m.__table__ for m in TENANT_MODELS + OPS_MODELS + PUBLIC_MODELS]
    # Parents the new tables point at, as bare stand-ins.
    from juli_backend.models import IngestRawPayload, OpsSimScenario, OpsStaff, Shop

    Base.metadata.create_all(
        engine,
        tables=[
            Shop.__table__,
            IngestRawPayload.__table__,
            OpsStaff.__table__,
            OpsSimScenario.__table__,
            *tables,
        ],
    )
    with Session(engine) as s:
        yield s


def _period(shop_id, **overrides):
    now = datetime(2026, 11, 1, 3, 0, 0)
    row = {
        "shop_id": shop_id,
        "platform": "shopee",
        "dataset": "product_period",
        "period_start": date(2026, 10, 1),
        "period_end": date(2026, 10, 28),
        "item_id": "1001",
        "variation_id": "",
        "stream": "total",
        "order_type": "confirmed",
        "orders": Decimal("3"),
        "gmv": Decimal("150000"),
        "confidence": "high",
        "extra": {},
        "source": "file",
        "source_rank": 2,
        "source_version": "seller-centre-xlsx-1",
        "mapper_version": 1,
        "captured_at": now,
        "updated_at": now,
    }
    row.update(overrides)
    return PlatformPeriodMetric(**row)


def test_a_duplicate_period_key_is_refused_and_a_variation_is_its_own_row(session):
    shop_id = uuid.uuid4()
    session.add_all([_period(shop_id), _period(shop_id, variation_id="2001")])
    session.flush()
    assert {r.variation_id for r in session.query(PlatformPeriodMetric)} == {"", "2001"}
    session.add(_period(shop_id, gmv=Decimal("1")))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
    assert session.query(PlatformPeriodMetric).count() == 0


def test_two_periods_starting_the_same_day_do_not_collide(session):
    shop_id = uuid.uuid4()
    session.add_all([_period(shop_id), _period(shop_id, period_end=date(2026, 10, 31))])
    session.flush()
    assert session.query(PlatformPeriodMetric).count() == 2


def test_one_contract_version_per_ref(session):
    shop_id = uuid.uuid4()
    session.add_all(
        [
            KpiContract(
                shop_id=shop_id, contract_ref="01/2026", version=1, status="sent", params={}
            ),
            KpiContract(
                shop_id=shop_id, contract_ref="01/2026", version=2, status="draft", params={}
            ),
        ]
    )
    session.flush()
    assert sorted(c.version for c in session.query(KpiContract)) == [1, 2]
    session.add(
        KpiContract(shop_id=shop_id, contract_ref="01/2026", version=2, status="draft", params={})
    )
    with pytest.raises(IntegrityError):
        session.flush()
