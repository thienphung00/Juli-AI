"""Issue #303 — P2-B1 daily batch rules pipeline contract tests.

AC1 → batch job runs on synced Postgres aggregates (via build_feature_aggregates)
AC2 → deterministic visual_layer advisory signals + ranked execution_layer recommendations
AC3 → schedule aligns with phase-2-mvp.md (08:00 UTC scoring window)
"""

from __future__ import annotations

import ast
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio

from juli_backend.models.models import (
    InventoryItem,
    Order,
    OrderItem,
    Product,
    Return,
    Shop,
    User,
)
from juli_backend.services.aggregates.types import (
    FeatureAggregateSnapshot,
    HealthDataSource,
    ShopLifecycleContext,
    ShopProfile,
)
from juli_backend.services.scoring.advisory import format_advisory_one_line
from juli_backend.services.scoring.batch import run_daily_scoring_batch
from juli_backend.services.scoring.kpi_catalog import (
    MID_LARGE_WORKFLOW_KEYS,
    NEW_SHOP_WORKFLOW_KEYS,
    get_workflows_for_profile,
)
from juli_backend.services.scoring.pipeline import run_daily_scoring_for_shop
from juli_backend.services.scoring.recommendations import rank_workflow_recommendations
from juli_backend.services.scoring.schedule import (
    DAILY_SCORING_CRON_UTC,
    DAILY_SCORING_UTC_HOUR,
    DAILY_SCORING_UTC_MINUTE,
)
from juli_backend.services.scoring.signals import compute_scoring_signals
from juli_backend.services.scoring.types import (
    VISUAL_LAYER_KPI_IDS,
    VisualLayerDomain,
    WorkflowRecommendations,
)

COMPUTED_AT = datetime(2026, 7, 12, 8, 0, tzinfo=UTC)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCORING_PKG = REPO_ROOT / "backend/src/juli_backend/services/scoring"

FORBIDDEN_ML_IMPORT_PREFIXES = (
    "juli_backend.ai.seller_stage",
    "juli_backend.ai.features",
    "sklearn",
    "joblib",
    "pickle",
    "src.modules.ml",
)


def _import_names_from_module(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest_asyncio.fixture
async def mid_large_shop_with_synced_data(session, user_id):
    user = User(id=user_id, phone="+84901112233")
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name="Batch Scoring Shop",
        tiktok_shop_id="7658073774813611784",
        created_at=datetime.now(UTC) - timedelta(days=120),
    )
    session.add_all([user, shop])
    await session.flush()

    now = datetime.now(UTC)
    products = [
        Product(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id="prod-a",
            name="Widget A",
            status="ACTIVE",
            revenue=Decimal("800000"),
            units_sold=40,
            update_time=now,
        ),
        Product(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id="prod-b",
            name="Widget B",
            status="ACTIVE",
            revenue=Decimal("200000"),
            units_sold=10,
            update_time=now,
        ),
    ]
    orders = [
        Order(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_order_id=f"ord-{index}",
            status="COMPLETED",
            total_amount=Decimal("150000"),
            currency="VND",
            update_time=now,
        )
        for index in range(1, 6)
    ]
    returns = [
        Return(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_return_id="ret-1",
            tiktok_order_id="ord-1",
            return_type="refund",
            refund_amount=Decimal("10000"),
            status="COMPLETED",
            update_time=now,
        ),
    ]
    session.add_all([*products, *orders, *returns])
    await session.flush()
    return shop


class TestScheduleAlignsWithPhase2Mvp:
    def test_daily_scoring_window_is_08_00_utc(self):
        assert DAILY_SCORING_UTC_HOUR == 8
        assert DAILY_SCORING_UTC_MINUTE == 0

    def test_cron_expression_matches_08_00_utc(self):
        assert DAILY_SCORING_CRON_UTC == "0 8 * * *"


class TestNoMlArtifactsInPhase2ScoringPaths:
    def test_no_ml_inference_artifacts_in_scoring_package(self):
        for py_file in SCORING_PKG.glob("*.py"):
            imports = _import_names_from_module(py_file)
            for forbidden in FORBIDDEN_ML_IMPORT_PREFIXES:
                matches = [name for name in imports if name.startswith(forbidden)]
                assert not matches, f"{py_file.name} imports forbidden ML path: {matches}"


class TestVisualLayerAdvisorySignals:
    def test_one_line_format_matches_visual_layer_pattern(self):
        line = format_advisory_one_line(
            "SPS 3.5/4.0 (thiếu 0.5 điểm)",
            "risk",
            "performance deteriorating · investigate fulfillment",
        )
        assert line.count("·") == 2
        assert "risk:" in line

    def test_compute_scoring_signals_covers_all_visual_layer_kpis(self):
        snapshot = FeatureAggregateSnapshot(
            shop_id=uuid.uuid4(),
            shop_profile=ShopProfile.MID_LARGE_SHOP,
            health_data_source=HealthDataSource.PROXY,
            sps_score=None,
            vp_score=None,
            ahr_score=None,
            order_count=5,
            product_count=2,
            return_count=1,
            total_order_value=Decimal("450000"),
            total_product_revenue=Decimal("1000000"),
            total_units_sold=50,
            return_rate_proxy=0.2,
            data_sources=["orders", "products", "returns"],
        )
        signals = compute_scoring_signals(
            snapshot,
            computed_at=datetime(2026, 7, 12, 8, 0, tzinfo=UTC),
            products=[],
        )
        assert set(signals.kpis.keys()) == VISUAL_LAYER_KPI_IDS

    def test_proxy_tier_emits_available_revenue_and_return_signals(self):
        snapshot = FeatureAggregateSnapshot(
            shop_id=uuid.uuid4(),
            shop_profile=ShopProfile.MID_LARGE_SHOP,
            health_data_source=HealthDataSource.PROXY,
            sps_score=None,
            vp_score=None,
            ahr_score=None,
            order_count=5,
            product_count=2,
            return_count=1,
            total_order_value=Decimal("450000"),
            total_product_revenue=Decimal("1000000"),
            total_units_sold=50,
            return_rate_proxy=0.2,
            data_sources=["orders", "products", "returns"],
        )
        signals = compute_scoring_signals(
            snapshot,
            computed_at=datetime(2026, 7, 12, 8, 0, tzinfo=UTC),
            products=[],
        )
        assert signals.kpis["net_revenue"].domain == VisualLayerDomain.REVENUE
        assert signals.kpis["net_revenue"].signal_type in {"risk", "opportunity"}
        assert signals.kpis["roas"].signal_type == "unavailable"
        assert signals.kpis["roas"].action_hint == "Chờ đồng bộ Promotion API"
        assert signals.kpis["csat"].signal_type == "unavailable"


class TestDeterministicRulesProduceRankedRecommendations:
    @pytest.mark.asyncio
    async def test_mid_large_shop_returns_execution_layer_workflow_keys(
        self, session, mid_large_shop_with_synced_data
    ):
        lifecycle = ShopLifecycleContext(
            probation_status="graduated",
            health_data_source=HealthDataSource.PROXY,
        )
        result = await run_daily_scoring_for_shop(
            session,
            mid_large_shop_with_synced_data.id,
            lifecycle=lifecycle,
            computed_at=datetime(2026, 7, 12, 8, 0, tzinfo=UTC),
        )

        recs = result.recommendations
        assert isinstance(recs, WorkflowRecommendations)
        assert recs.shop_profile == ShopProfile.MID_LARGE_SHOP
        assert len(recs.recommended_workflows) > 0

        priorities = [item.priority for item in recs.recommended_workflows]
        assert priorities == list(range(1, len(priorities) + 1))

        workflow_keys = {item.workflow_key for item in recs.recommended_workflows}
        assert workflow_keys.issubset(MID_LARGE_WORKFLOW_KEYS)
        assert "npl" not in workflow_keys
        assert "refund_spike_detection" not in workflow_keys

        first = recs.recommended_workflows[0]
        assert first.workflow_name
        assert "·" in first.rationale
        assert first.source_kpi_ids

    @pytest.mark.asyncio
    async def test_same_inputs_produce_identical_recommendations(
        self, session, mid_large_shop_with_synced_data
    ):
        lifecycle = ShopLifecycleContext(
            probation_status="graduated",
            health_data_source=HealthDataSource.PROXY,
        )
        fixed_at = datetime(2026, 7, 12, 8, 0, tzinfo=UTC)
        kwargs = {"lifecycle": lifecycle, "computed_at": fixed_at}

        first = await run_daily_scoring_for_shop(
            session, mid_large_shop_with_synced_data.id, **kwargs
        )
        second = await run_daily_scoring_for_shop(
            session, mid_large_shop_with_synced_data.id, **kwargs
        )

        assert first.recommendations == second.recommendations

    def test_new_shop_profile_gates_probation_workflows_only(self):
        snapshot = FeatureAggregateSnapshot(
            shop_id=uuid.uuid4(),
            shop_profile=ShopProfile.NEW_SHOP,
            health_data_source=HealthDataSource.API,
            sps_score=3.5,
            vp_score=1.0,
            ahr_score=85.0,
            order_count=10,
            product_count=2,
            return_count=1,
            total_order_value=Decimal("1000000"),
            total_product_revenue=Decimal("500000"),
            total_units_sold=20,
            return_rate_proxy=0.1,
            data_sources=["orders", "products", "returns"],
        )
        lifecycle = ShopLifecycleContext(
            probation_status="active",
            health_data_source=HealthDataSource.API,
            api_sps_score=3.5,
            api_ahr_score=85.0,
        )
        signals = compute_scoring_signals(
            snapshot,
            lifecycle=lifecycle,
            computed_at=datetime(2026, 7, 12, 8, 0, tzinfo=UTC),
            products=[],
        )
        recs = rank_workflow_recommendations(ShopProfile.NEW_SHOP, signals)

        workflow_keys = {item.workflow_key for item in recs.recommended_workflows}
        assert workflow_keys.issubset(NEW_SHOP_WORKFLOW_KEYS)
        assert workflow_keys.isdisjoint(MID_LARGE_WORKFLOW_KEYS - NEW_SHOP_WORKFLOW_KEYS)
        assert get_workflows_for_profile(ShopProfile.NEW_SHOP) == NEW_SHOP_WORKFLOW_KEYS


class TestBatchJobRunsOnSyncedAggregates:
    @pytest.mark.asyncio
    async def test_batch_scoring_uses_feature_aggregates_from_synced_tables(
        self, session, mid_large_shop_with_synced_data, monkeypatch
    ):
        from juli_backend.services.scoring import pipeline as scoring_pipeline

        calls: list[str] = []

        original = scoring_pipeline.build_feature_aggregates

        async def tracked_build(session_arg, shop_id, **kwargs):
            calls.append("build_feature_aggregates")
            return await original(session_arg, shop_id, **kwargs)

        monkeypatch.setattr(
            scoring_pipeline,
            "build_feature_aggregates",
            tracked_build,
        )

        lifecycle = ShopLifecycleContext(
            probation_status="graduated",
            health_data_source=HealthDataSource.PROXY,
        )
        results = await run_daily_scoring_batch(
            session,
            shop_ids=[mid_large_shop_with_synced_data.id],
            lifecycle_for_shop=lambda _shop_id: lifecycle,
            computed_at=datetime(2026, 7, 12, 8, 0, tzinfo=UTC),
        )

        assert calls == ["build_feature_aggregates"]
        assert len(results) == 1
        assert results[0].aggregates.data_sources == [
            "inventory_items",
            "order_items",
            "orders",
            "products",
            "returns",
        ]
        assert results[0].recommendations.recommended_workflows


class TestComputedKpisFlipUnavailableSignals:
    @pytest_asyncio.fixture
    async def shop_with_computed_kpi_data(self, session, user_id):
        user = User(id=user_id, phone="+84901112233")
        shop = Shop(
            id=uuid.uuid4(),
            user_id=user_id,
            shop_name="Computed KPI Shop",
            tiktok_shop_id="7658073774813611784",
            created_at=datetime.now(UTC) - timedelta(days=120),
        )
        session.add_all([user, shop])
        await session.flush()

        now = COMPUTED_AT
        payment_time = COMPUTED_AT - timedelta(days=5)
        products = [
            Product(
                id=uuid.uuid4(),
                shop_id=shop.id,
                tiktok_product_id="prod-a",
                name="Widget A",
                status="ACTIVE",
                category="Electronics",
                revenue=Decimal("800000"),
                units_sold=40,
                update_time=now,
            ),
        ]
        orders = [
            Order(
                id=uuid.uuid4(),
                shop_id=shop.id,
                tiktok_order_id="ord-1",
                status="COMPLETED",
                buyer_id="buyer-1",
                total_amount=Decimal("150000"),
                currency="VND",
                payment_time=payment_time,
                ship_time=payment_time + timedelta(hours=6),
                update_time=now,
                created_at=payment_time,
            ),
            Order(
                id=uuid.uuid4(),
                shop_id=shop.id,
                tiktok_order_id="ord-2",
                status="COMPLETED",
                buyer_id="buyer-1",
                total_amount=Decimal("120000"),
                currency="VND",
                payment_time=payment_time,
                ship_time=payment_time + timedelta(hours=8),
                update_time=now,
                created_at=payment_time,
            ),
        ]
        order_items = [
            OrderItem(
                id=uuid.uuid4(),
                shop_id=shop.id,
                order_id=orders[0].id,
                tiktok_order_id="ord-1",
                tiktok_product_id="prod-a",
                tiktok_sku_id="sku-a",
                quantity=4,
                unit_price=Decimal("25000"),
                line_total=Decimal("100000"),
                update_time=now,
                created_at=payment_time,
            ),
            OrderItem(
                id=uuid.uuid4(),
                shop_id=shop.id,
                order_id=orders[1].id,
                tiktok_order_id="ord-2",
                tiktok_product_id="prod-a",
                tiktok_sku_id="sku-a",
                quantity=2,
                unit_price=Decimal("25000"),
                line_total=Decimal("50000"),
                update_time=now,
                created_at=payment_time,
            ),
        ]
        inventory_items = [
            InventoryItem(
                id=uuid.uuid4(),
                shop_id=shop.id,
                tiktok_product_id="prod-a",
                tiktok_sku_id="sku-a",
                quantity=10,
                update_time=now,
                created_at=now,
            ),
            InventoryItem(
                id=uuid.uuid4(),
                shop_id=shop.id,
                tiktok_product_id="prod-b",
                tiktok_sku_id="sku-b",
                quantity=0,
                update_time=now,
                created_at=now,
            ),
        ]
        returns = [
            Return(
                id=uuid.uuid4(),
                shop_id=shop.id,
                tiktok_return_id="ret-1",
                tiktok_order_id="ord-1",
                return_type="refund",
                refund_amount=Decimal("10000"),
                status="COMPLETED",
                created_at=payment_time,
                update_time=payment_time + timedelta(hours=12),
            ),
        ]
        session.add_all([*products, *orders, *order_items, *inventory_items, *returns])
        await session.flush()
        return shop

    @pytest.mark.asyncio
    async def test_daily_batch_flips_previously_unavailable_kpis(
        self, session, shop_with_computed_kpi_data
    ):
        lifecycle = ShopLifecycleContext(
            probation_status="graduated",
            health_data_source=HealthDataSource.PROXY,
        )
        result = await run_daily_scoring_for_shop(
            session,
            shop_with_computed_kpi_data.id,
            lifecycle=lifecycle,
            computed_at=COMPUTED_AT,
        )

        live_kpis = {
            "inventory_turnover",
            "dsi",
            "stockout_rate",
            "fulfillment_accuracy_rate",
            "orders_at_sla_risk",
            "seller_fault_cancellation_rate",
            "conversion_rate_by_category",
            "repeat_purchase_rate",
            "after_sales_handling_time",
            "csat",
        }
        for kpi_id in live_kpis:
            signal = result.signals.kpis[kpi_id]
            assert signal.signal_type in {"risk", "opportunity", "healthy"}, kpi_id
            assert signal.technique == "rules_proxy", kpi_id

        for ads_kpi in ("roas", "cac", "ctr"):
            assert result.signals.kpis[ads_kpi].signal_type == "unavailable"
            assert (
                result.signals.kpis[ads_kpi].action_hint == "Chờ đồng bộ Promotion API"
            )

        assert result.signals.kpis["csat"].workflow_keys == ()
        assert result.aggregates.computed_kpis is not None
