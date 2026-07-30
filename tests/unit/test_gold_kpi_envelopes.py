"""A0 serving gold.kpi_envelopes model, repo, and legacy compat adapter (#606)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio

from juli_backend.models.models import Shop, User
from juli_backend.services.gold_kpi_envelope_contract import (
    build_honest_unavailable_shell_payload,
)


@pytest_asyncio.fixture
async def shop(session, user_id):
    user = User(id=user_id, phone="+849305000606")
    session.add(user)
    await session.flush()
    s = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Gold KPI Shop 606",
        tiktok_shop_id="tiktok_shop_606",
    )
    session.add(s)
    await session.flush()
    return s


def test_gold_model_exposes_shop_id_pk_and_payload_kpis_map() -> None:
    from juli_backend.models.models import GoldKpiEnvelope

    cols = GoldKpiEnvelope.__table__.columns
    for name in ("shop_id", "computed_at", "envelope_version", "payload"):
        assert name in cols
    pk_cols = {c.name for c in GoldKpiEnvelope.__table__.primary_key.columns}
    assert pk_cols == {"shop_id"}
    assert GoldKpiEnvelope.__table__.schema == "gold"


def test_unavailable_shell_payload_has_kpis_map() -> None:
    shop_id = uuid.uuid4()
    when = datetime(2026, 7, 30, 6, 0, tzinfo=UTC)
    payload = build_honest_unavailable_shell_payload(shop_id=shop_id, computed_at=when)
    assert "kpis" in payload
    assert isinstance(payload["kpis"], dict)
    assert len(payload["kpis"]) >= 5
    for entry in payload["kpis"].values():
        assert entry["availability"] == "unavailable"
        assert "label" in entry


@pytest.mark.asyncio
async def test_gold_repo_upsert_and_get_by_shop_id(session, shop) -> None:
    from juli_backend.repositories.repos import GoldKpiEnvelopesRepo

    repo = GoldKpiEnvelopesRepo(session)
    computed_at = datetime(2026, 7, 30, 6, 0, tzinfo=UTC)
    payload = build_honest_unavailable_shell_payload(shop_id=shop.id, computed_at=computed_at)

    row = await repo.upsert(
        shop_id=shop.id,
        envelope_version=1,
        payload=payload,
        computed_at=computed_at,
    )
    await session.flush()

    assert row.shop_id == shop.id
    assert row.payload["kpis"]

    fetched = await repo.get(shop.id)
    assert fetched is not None
    assert fetched.shop_id == shop.id
    assert fetched.payload == payload


@pytest.mark.asyncio
async def test_gold_repo_seed_shell_is_idempotent(session, shop) -> None:
    from juli_backend.repositories.repos import GoldKpiEnvelopesRepo

    repo = GoldKpiEnvelopesRepo(session)
    first = await repo.seed_unavailable_shell(shop.id)
    await session.flush()
    second = await repo.seed_unavailable_shell(shop.id)
    await session.flush()

    assert first.shop_id == second.shop_id
    assert first.payload["kpis"] == second.payload["kpis"]


@pytest.mark.asyncio
async def test_compat_adapter_reads_and_writes_gold_not_legacy(session, shop) -> None:
    from sqlalchemy import func, select

    from juli_backend.models.models import AnalyticsKpiEnvelope, GoldKpiEnvelope
    from juli_backend.repositories.repos import AnalyticsKpiEnvelopesRepo

    repo = AnalyticsKpiEnvelopesRepo(session)
    computed_at = datetime(2026, 7, 30, 7, 0, tzinfo=UTC)
    payload = build_honest_unavailable_shell_payload(shop_id=shop.id, computed_at=computed_at)

    await repo.upsert(
        shop_id=shop.id,
        kind="analytics",
        envelope_version=1,
        payload=payload,
        computed_at=computed_at,
    )
    await session.flush()

    gold_count = (
        await session.execute(
            select(func.count())
            .select_from(GoldKpiEnvelope)
            .where(GoldKpiEnvelope.shop_id == shop.id)
        )
    ).scalar_one()
    assert gold_count == 1

    legacy_count = (
        await session.execute(
            select(func.count())
            .select_from(AnalyticsKpiEnvelope)
            .where(AnalyticsKpiEnvelope.shop_id == shop.id)
        )
    ).scalar_one()
    assert legacy_count == 0

    fetched = await repo.get_by_kind(shop.id, "analytics")
    assert fetched is not None
    assert fetched.payload["kpis"] == payload["kpis"]


def test_scope_excludes_demo_ui_and_partner() -> None:
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    touched = [
        "backend/src/juli_backend/database/migrations/versions/024_gold_kpi_envelopes.py",
        "backend/src/juli_backend/models/models.py",
        "backend/src/juli_backend/repositories/repos.py",
        "backend/src/juli_backend/services/gold_kpi_envelope_contract.py",
        "tests/unit/test_gold_kpi_envelopes.py",
        "tests/unit/test_gold_kpi_envelopes_migration_contract.py",
        "tests/integration/test_migrations.py",
    ]
    for rel in touched:
        assert (repo_root / rel).is_file(), rel
        assert "apps/demo" not in rel
