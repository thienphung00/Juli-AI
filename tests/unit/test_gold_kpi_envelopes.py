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
    from juli_backend.services.gold_kpi_envelope_serving import seed_unavailable_shell

    first = await seed_unavailable_shell(session, shop.id)
    await session.flush()
    second = await seed_unavailable_shell(session, shop.id)
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


@pytest.mark.asyncio
async def test_live_hours_resolves_from_shop_grain_rows(session, shop, user_id) -> None:
    """live_hours must resolve from shop-grain analytics_performance_intervals rows."""
    from decimal import Decimal

    from juli_backend.models.models import AnalyticsPerformanceInterval
    from juli_backend.services.gold_kpi_envelope_serving import (
        compute_demo_main_kpis_payload,
    )

    # Add a shop-grain row with live_hours populated
    interval = AnalyticsPerformanceInterval(
        shop_id=shop.id,
        snapshot_key=f"{shop.id}:shop:2026-08-01",
        grain="shop",
        start_date=datetime(2026, 8, 1, tzinfo=UTC).date(),
        end_date=datetime(2026, 8, 1, tzinfo=UTC).date(),
        live_hours=Decimal("12.5"),
        update_time=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )
    session.add(interval)
    await session.flush()

    payload = await compute_demo_main_kpis_payload(session, shop.id)

    # live_hours should be available with the value from the interval
    assert payload["kpis"]["live_hours"]["availability"] == "available"
    assert payload["kpis"]["live_hours"]["value"] == 12.5
    assert payload["kpis"]["live_hours"]["label"] == "LIVE hours"


@pytest.mark.asyncio
async def test_ctor_is_gmv_weighted_click_order_rate_from_product_grain(
    session, shop, user_id
) -> None:
    """CTOR must be GMV-weighted click_order_rate over product-grain rows."""
    from decimal import Decimal

    from juli_backend.models.models import AnalyticsPerformanceInterval
    from juli_backend.services.gold_kpi_envelope_serving import (
        compute_demo_main_kpis_payload,
    )

    # Add product-grain rows with click_order_rate and gmv
    # Row 1: 100 GMV, 0.05 click_order_rate (5 orders)
    interval1 = AnalyticsPerformanceInterval(
        shop_id=shop.id,
        snapshot_key=f"{shop.id}:product:sku1:2026-08-01",
        grain="product",
        start_date=datetime(2026, 8, 1, tzinfo=UTC).date(),
        end_date=datetime(2026, 8, 1, tzinfo=UTC).date(),
        tiktok_product_id="prod1",
        tiktok_sku_id="sku1",
        gmv=Decimal("100.00"),
        click_order_rate=Decimal("0.05"),
        update_time=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )
    # Row 2: 200 GMV, 0.10 click_order_rate (20 orders)
    interval2 = AnalyticsPerformanceInterval(
        shop_id=shop.id,
        snapshot_key=f"{shop.id}:product:sku2:2026-08-01",
        grain="product",
        start_date=datetime(2026, 8, 1, tzinfo=UTC).date(),
        end_date=datetime(2026, 8, 1, tzinfo=UTC).date(),
        tiktok_product_id="prod2",
        tiktok_sku_id="sku2",
        gmv=Decimal("200.00"),
        click_order_rate=Decimal("0.10"),
        update_time=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )
    session.add(interval1)
    session.add(interval2)
    await session.flush()

    payload = await compute_demo_main_kpis_payload(session, shop.id)

    # CTOR should be GMV-weighted average of click_order_rate
    # weighted_ctor = (100 * 0.05 + 200 * 0.10) / (100 + 200) = 25 / 300 = 0.0833...
    assert payload["kpis"]["ctor"]["availability"] == "available"
    expected_ctor = (100 * 0.05 + 200 * 0.10) / (100 + 200)
    assert abs(float(payload["kpis"]["ctor"]["value"]) - expected_ctor) < 0.0001
    assert payload["kpis"]["ctor"]["label"] == "CTOR (click→đơn)"


@pytest.mark.asyncio
async def test_live_hours_and_ctor_unavailable_when_no_rows(session, shop, user_id) -> None:
    """live_hours and ctor must fall back to unavailable (ADR-044) when no analytics rows exist."""
    from juli_backend.services.gold_kpi_envelope_serving import (
        compute_demo_main_kpis_payload,
    )

    # No analytics rows added
    payload = await compute_demo_main_kpis_payload(session, shop.id)

    # Both should be unavailable with no value key
    assert payload["kpis"]["live_hours"]["availability"] == "unavailable"
    assert "value" not in payload["kpis"]["live_hours"]
    assert payload["kpis"]["ctor"]["availability"] == "unavailable"
    assert "value" not in payload["kpis"]["ctor"]


@pytest.mark.asyncio
async def test_live_hours_zero_is_available_not_unavailable(session, shop, user_id) -> None:
    """live_hours must report value: 0.0 when rows exist but sum is zero (honest measurement)."""
    from decimal import Decimal

    from juli_backend.models.models import AnalyticsPerformanceInterval
    from juli_backend.services.gold_kpi_envelope_serving import (
        compute_demo_main_kpis_payload,
    )

    # Add shop-grain rows with live_hours = 0
    interval = AnalyticsPerformanceInterval(
        shop_id=shop.id,
        snapshot_key=f"{shop.id}:shop:2026-08-01",
        grain="shop",
        start_date=datetime(2026, 8, 1, tzinfo=UTC).date(),
        end_date=datetime(2026, 8, 1, tzinfo=UTC).date(),
        live_hours=Decimal("0.0"),
        update_time=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )
    session.add(interval)
    await session.flush()

    payload = await compute_demo_main_kpis_payload(session, shop.id)

    # Should be available (rows exist) with value 0.0, not unavailable
    assert payload["kpis"]["live_hours"]["availability"] == "available"
    assert payload["kpis"]["live_hours"]["value"] == 0.0


@pytest.mark.asyncio
async def test_ctor_zero_is_available_when_gmv_exists(session, shop, user_id) -> None:
    """CTOR must report value: 0.0 when rows with sum(gmv) > 0 but all rates are 0."""
    from decimal import Decimal

    from juli_backend.models.models import AnalyticsPerformanceInterval
    from juli_backend.services.gold_kpi_envelope_serving import (
        compute_demo_main_kpis_payload,
    )

    # Add product-grain rows with gmv > 0 but click_order_rate = 0
    interval = AnalyticsPerformanceInterval(
        shop_id=shop.id,
        snapshot_key=f"{shop.id}:product:sku1:2026-08-01",
        grain="product",
        start_date=datetime(2026, 8, 1, tzinfo=UTC).date(),
        end_date=datetime(2026, 8, 1, tzinfo=UTC).date(),
        tiktok_product_id="prod1",
        tiktok_sku_id="sku1",
        gmv=Decimal("100.00"),
        click_order_rate=Decimal("0.0"),
        update_time=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )
    session.add(interval)
    await session.flush()

    payload = await compute_demo_main_kpis_payload(session, shop.id)

    # Should be available (sum(gmv) > 0) with value 0.0, not unavailable
    assert payload["kpis"]["ctor"]["availability"] == "available"
    assert payload["kpis"]["ctor"]["value"] == 0.0


@pytest.mark.asyncio
async def test_ctor_unavailable_when_no_gmv_denominator(session, shop, user_id) -> None:
    """CTOR must be unavailable when sum(gmv) == 0 (undefined weighted mean)."""
    from decimal import Decimal

    from juli_backend.models.models import AnalyticsPerformanceInterval
    from juli_backend.services.gold_kpi_envelope_serving import (
        compute_demo_main_kpis_payload,
    )

    # Add product-grain rows but all gmv = 0 (no denominator)
    interval = AnalyticsPerformanceInterval(
        shop_id=shop.id,
        snapshot_key=f"{shop.id}:product:sku1:2026-08-01",
        grain="product",
        start_date=datetime(2026, 8, 1, tzinfo=UTC).date(),
        end_date=datetime(2026, 8, 1, tzinfo=UTC).date(),
        tiktok_product_id="prod1",
        tiktok_sku_id="sku1",
        gmv=Decimal("0.00"),
        click_order_rate=Decimal("0.05"),
        update_time=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )
    session.add(interval)
    await session.flush()

    payload = await compute_demo_main_kpis_payload(session, shop.id)

    # Should be unavailable (no denominator, undefined) with no value key
    assert payload["kpis"]["ctor"]["availability"] == "unavailable"
    assert "value" not in payload["kpis"]["ctor"]


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
