"""P2.10-A1 Analytics KPI envelope schema + shop-scoped upsert repo (#525)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from juli_backend.models.models import Shop, User


@pytest_asyncio.fixture
async def shop(session, user_id):
    user = User(id=user_id, phone="+849305000525")
    session.add(user)
    await session.flush()
    s = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="KPI Envelope Shop 525",
        tiktok_shop_id="tiktok_shop_525",
    )
    session.add(s)
    await session.flush()
    return s


def _sample_payload(*, shop_id: uuid.UUID, computed_at: datetime) -> dict:
    return {
        "envelope_version": 1,
        "kind": "analytics",
        "shop_id": str(shop_id),
        "computed_at": computed_at.isoformat(),
        "currency": "VND",
        "kpis": {
            "gmv_tiktok": {
                "availability": "available",
                "label": "GMV (TikTok)",
                "series": [{"t": "2026-07-01", "v": 1000.0}],
            }
        },
        "meta": {"source_partitions": ["A-36"], "notes": []},
    }


@pytest.mark.asyncio
async def test_model_exposes_required_columns_and_unique_shop_kind() -> None:
    from juli_backend.models.models import AnalyticsKpiEnvelope

    cols = AnalyticsKpiEnvelope.__table__.columns
    for name in (
        "id",
        "shop_id",
        "kind",
        "envelope_version",
        "payload",
        "computed_at",
        "created_at",
        "updated_at",
    ):
        assert name in cols

    constraint_names = {c.name for c in AnalyticsKpiEnvelope.__table__.constraints if c.name}
    assert "uq_analytics_kpi_envelopes_shop_kind" in constraint_names


@pytest.mark.asyncio
async def test_repo_upsert_inserts_and_fetches_by_shop_kind(session, shop) -> None:
    from juli_backend.repositories.repos import AnalyticsKpiEnvelopesRepo

    repo = AnalyticsKpiEnvelopesRepo(session)
    computed_at = datetime(2026, 7, 27, 6, 0, tzinfo=UTC)
    payload = _sample_payload(shop_id=shop.id, computed_at=computed_at)

    row = await repo.upsert(
        shop_id=shop.id,
        kind="analytics",
        envelope_version=1,
        payload=payload,
        computed_at=computed_at,
    )
    await session.flush()

    assert row.id is not None
    assert row.shop_id == shop.id
    assert row.kind == "analytics"
    assert row.envelope_version == 1
    assert row.payload["kpis"]["gmv_tiktok"]["label"] == "GMV (TikTok)"

    fetched = await repo.get_by_kind(shop.id, "analytics")
    assert fetched is not None
    assert fetched.id == row.id
    assert fetched.payload == payload


@pytest.mark.asyncio
async def test_repo_upsert_is_idempotent_on_shop_kind(session, shop) -> None:
    from juli_backend.repositories.repos import AnalyticsKpiEnvelopesRepo

    repo = AnalyticsKpiEnvelopesRepo(session)
    computed_at = datetime(2026, 7, 27, 6, 0, tzinfo=UTC)
    payload_v1 = _sample_payload(shop_id=shop.id, computed_at=computed_at)

    first = await repo.upsert(
        shop_id=shop.id,
        kind="analytics",
        envelope_version=1,
        payload=payload_v1,
        computed_at=computed_at,
    )
    await session.flush()

    computed_at_2 = datetime(2026, 7, 27, 7, 0, tzinfo=UTC)
    payload_v2 = _sample_payload(shop_id=shop.id, computed_at=computed_at_2)
    payload_v2["kpis"]["gmv_tiktok"]["series"] = [{"t": "2026-07-01", "v": 2000.0}]

    second = await repo.upsert(
        shop_id=shop.id,
        kind="analytics",
        envelope_version=1,
        payload=payload_v2,
        computed_at=computed_at_2,
    )
    await session.flush()

    assert second.id == first.id
    assert second.payload["kpis"]["gmv_tiktok"]["series"][0]["v"] == 2000.0
    assert second.computed_at == computed_at_2

    rows = await repo.list(shop.id, limit=10)
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_repo_supports_multi_shop_keys(session, shop) -> None:
    from juli_backend.repositories.repos import AnalyticsKpiEnvelopesRepo

    other_user = User(id=uuid.uuid4(), phone="+849305000526")
    session.add(other_user)
    await session.flush()
    other_shop = Shop(
        id=uuid.uuid4(),
        user_id=other_user.id,
        shop_name="Second Shop 525",
        tiktok_shop_id="tiktok_shop_525_b",
    )
    session.add(other_shop)
    await session.flush()

    repo = AnalyticsKpiEnvelopesRepo(session)
    computed_at = datetime(2026, 7, 27, 6, 0, tzinfo=UTC)

    a = await repo.upsert(
        shop_id=shop.id,
        kind="analytics",
        envelope_version=1,
        payload=_sample_payload(shop_id=shop.id, computed_at=computed_at),
        computed_at=computed_at,
    )
    b = await repo.upsert(
        shop_id=other_shop.id,
        kind="analytics",
        envelope_version=1,
        payload=_sample_payload(shop_id=other_shop.id, computed_at=computed_at),
        computed_at=computed_at,
    )
    await session.flush()

    assert a.id != b.id
    assert a.shop_id != b.shop_id
    assert (await repo.get_by_kind(shop.id, "analytics")).id == a.id
    assert (await repo.get_by_kind(other_shop.id, "analytics")).id == b.id


def test_scope_excludes_redis_webhook_public_api_demo_ui() -> None:
    """AC: no Redis, webhook, public API, or Demo UI changes required to merge."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    touched = [
        "backend/src/juli_backend/database/migrations/versions/020_analytics_kpi_envelopes.py",
        "backend/src/juli_backend/models/models.py",
        "backend/src/juli_backend/repositories/repos.py",
        "backend/src/juli_backend/database/MODULE.md",
        "tests/unit/test_analytics_kpi_envelopes.py",
        "tests/unit/test_analytics_kpi_envelopes_migration_contract.py",
        "tests/integration/test_migrations.py",
    ]
    for rel in touched:
        assert (repo_root / rel).is_file(), rel
        assert "apps/demo" not in rel
        assert "redis" not in rel.lower()

    migration = (
        (
            repo_root
            / "backend/src/juli_backend/database/migrations/versions"
            / "020_analytics_kpi_envelopes.py"
        )
        .read_text(encoding="utf-8")
        .lower()
    )
    assert "redis" not in migration
    assert "webhook" not in migration
    assert "/v1/demo/analytics" not in migration
    assert "apps/demo" not in migration
