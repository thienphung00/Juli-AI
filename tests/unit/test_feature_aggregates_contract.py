"""Issue #300 — P2-A3 rules-only feature aggregate contract tests.

AC1 → aggregates read only from synced Postgres tables (orders, products, returns)
AC2 → no ML model artifact imports on Phase 2 aggregate paths
AC3 → health_data_source respected; unavailable → no fabricated health scores
AC4 → shop_profile rules-only classifier golden boundary fixtures
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
    AnalyticsPerformanceInterval,
    Order,
    Product,
    Return,
    Shop,
    TikTokSyncState,
    User,
)
from juli_backend.repositories.repos import (
    AnalyticsPerformanceRepo,
    InventoryRepo,
    OrderItemsRepo,
    OrdersRepo,
    ProductsRepo,
    ReturnsRepo,
    TikTokSyncStateRepo,
)
from juli_backend.services.aggregates.builder import (
    SYNCED_DATA_SOURCES,
    build_feature_aggregates,
)
from juli_backend.services.aggregates.health_source import resolve_health_snapshot
from juli_backend.services.aggregates.shop_profile import classify_shop_profile
from juli_backend.services.aggregates.types import (
    HealthDataSource,
    ShopLifecycleContext,
    ShopProfile,
    ShopProfileSignals,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
AGGREGATES_PKG = REPO_ROOT / "backend/src/juli_backend/services/aggregates"

FORBIDDEN_ML_IMPORT_PREFIXES = (
    "juli_backend.ai.seller_stage",
    "juli_backend.ai.features",
    "sklearn",
    "joblib",
    "pickle",
    "src.modules.ml",
)


@pytest_asyncio.fixture
async def shop_with_synced_data(session, user_id):
    user = User(id=user_id, phone="+84901112233")
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name="Fujiwa Aggregate Shop",
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
            tiktok_product_id="prod-1",
            name="Widget A",
            status="ACTIVE",
            revenue=Decimal("500000"),
            units_sold=25,
            update_time=now,
        ),
        Product(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id="prod-2",
            name="Widget B",
            status="ACTIVE",
            revenue=Decimal("300000"),
            units_sold=10,
            update_time=now,
        ),
    ]
    orders = [
        Order(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_order_id="ord-1",
            status="COMPLETED",
            total_amount=Decimal("150000"),
            currency="VND",
            update_time=now,
        ),
        Order(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_order_id="ord-2",
            status="COMPLETED",
            total_amount=Decimal("80000"),
            currency="VND",
            update_time=now,
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
            update_time=now,
        ),
    ]
    session.add_all([*products, *orders, *returns])
    await session.flush()
    return shop


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


class TestSyncedPostgresSourcesOnly:
    def test_builder_declares_synced_table_sources(self):
        assert SYNCED_DATA_SOURCES == frozenset(
            {
                "orders",
                "products",
                "returns",
                "order_items",
                "inventory_items",
                "analytics_performance_intervals",
                "tiktok_sync_state",
            }
        )

    def test_builder_module_imports_only_commerce_repos(self):
        builder_imports = _import_names_from_module(AGGREGATES_PKG / "builder.py")
        assert "juli_backend.repositories.repos" in builder_imports
        forbidden = {
            "juli_backend.integrations.tiktok",
            "juli_backend.services.etl",
            "juli_backend.ai.seller_stage",
        }
        assert builder_imports.isdisjoint(forbidden)

    @pytest.mark.asyncio
    async def test_build_feature_aggregates_reads_synced_tables(
        self, session, shop_with_synced_data, monkeypatch
    ):
        shop = shop_with_synced_data
        calls: list[str] = []

        for repo_cls, table in (
            (OrdersRepo, "orders"),
            (ProductsRepo, "products"),
            (ReturnsRepo, "returns"),
            (OrderItemsRepo, "order_items"),
            (InventoryRepo, "inventory_items"),
        ):
            original_list = repo_cls.list

            def make_wrapped(orig, tbl):
                async def wrapped(self, shop_id, **kwargs):
                    calls.append(tbl)
                    return await orig(self, shop_id, **kwargs)

                return wrapped

            monkeypatch.setattr(repo_cls, "list", make_wrapped(original_list, table))

        lifecycle = ShopLifecycleContext(
            probation_status="graduated",
            health_data_source=HealthDataSource.PROXY,
        )
        snapshot = await build_feature_aggregates(
            session, shop.id, lifecycle=lifecycle
        )

        assert set(calls) == {
            "orders",
            "products",
            "returns",
            "order_items",
            "inventory_items",
        }
        assert snapshot.order_count == 2
        assert snapshot.product_count == 2
        assert snapshot.return_count == 1
        assert snapshot.data_sources == [
            "analytics_performance_intervals",
            "inventory_items",
            "order_items",
            "orders",
            "products",
            "returns",
            "tiktok_sync_state",
        ]
        assert snapshot.computed_kpis is not None


class TestNoMlArtifactsInPhase2Paths:
    def test_no_ml_inference_artifacts_in_phase2_paths(self):
        for py_file in AGGREGATES_PKG.glob("*.py"):
            imports = _import_names_from_module(py_file)
            for forbidden in FORBIDDEN_ML_IMPORT_PREFIXES:
                matches = [name for name in imports if name.startswith(forbidden)]
                assert not matches, f"{py_file.name} imports forbidden ML path: {matches}"

    def test_builder_does_not_reference_model_artifact_extensions(self):
        source = (AGGREGATES_PKG / "builder.py").read_text(encoding="utf-8")
        for token in (".pkl", ".joblib", ".onnx", "load_model", "predict("):
            assert token not in source


class TestHealthDataSourceContract:
    def test_unavailable_emits_no_fabricated_health_scores(self):
        snapshot = resolve_health_snapshot(
            health_data_source=HealthDataSource.UNAVAILABLE,
            api_sps_score=99.0,
            api_vp_score=4.5,
            api_ahr_score=95.0,
        )
        assert snapshot.health_data_source == HealthDataSource.UNAVAILABLE
        assert snapshot.sps_score is None
        assert snapshot.vp_score is None
        assert snapshot.ahr_score is None

    def test_api_tier_uses_verified_scores_only(self):
        snapshot = resolve_health_snapshot(
            health_data_source=HealthDataSource.API,
            api_sps_score=4.2,
            api_vp_score=None,
            api_ahr_score=88.0,
        )
        assert snapshot.sps_score == 4.2
        assert snapshot.vp_score is None
        assert snapshot.ahr_score == 88.0

    @pytest.mark.asyncio
    async def test_build_feature_aggregates_unavailable_health(
        self, session, shop_with_synced_data
    ):
        lifecycle = ShopLifecycleContext(
            probation_status="graduated",
            health_data_source=HealthDataSource.UNAVAILABLE,
            api_sps_score=5.0,
        )
        snapshot = await build_feature_aggregates(
            session, shop_with_synced_data.id, lifecycle=lifecycle
        )
        assert snapshot.health_data_source == HealthDataSource.UNAVAILABLE
        assert snapshot.sps_score is None
        assert snapshot.vp_score is None
        assert snapshot.ahr_score is None


PROFILE_BOUNDARY_FIXTURES: list[tuple[str, ShopProfileSignals, ShopProfile]] = [
    (
        "boundary-active-probation",
        ShopProfileSignals(
            probation_status="active",
            shop_age_days=100,
            sps_current=3.5,
            sps_threshold=4.0,
            ahr_current=85,
            ahr_threshold=90,
        ),
        ShopProfile.NEW_SHOP,
    ),
    (
        "boundary-unmet-graduation-scores",
        ShopProfileSignals(
            probation_status="active",
            shop_age_days=100,
            sps_current=3.9,
            sps_threshold=4.0,
            ahr_current=89,
            ahr_threshold=90,
        ),
        ShopProfile.NEW_SHOP,
    ),
    (
        "boundary-graduated-mid-large-age",
        ShopProfileSignals(
            probation_status="graduated",
            shop_age_days=90,
            product_gmv_total=Decimal("1000000"),
            product_units_sold_total=50,
        ),
        ShopProfile.MID_LARGE_SHOP,
    ),
    (
        "boundary-graduated-young-with-gmv-metrics",
        ShopProfileSignals(
            probation_status="graduated",
            shop_age_days=60,
            product_gmv_total=Decimal("500000"),
            product_units_sold_total=20,
            ad_revenue_total=Decimal("100000"),
        ),
        ShopProfile.MID_LARGE_SHOP,
    ),
    (
        "boundary-graduated-young-insufficient-gmv",
        ShopProfileSignals(
            probation_status="graduated",
            shop_age_days=45,
            product_gmv_total=Decimal("300000"),
            product_units_sold_total=0,
        ),
        ShopProfile.NEW_SHOP,
    ),
]


class TestShopProfileClassifier:
    @pytest.mark.parametrize(
        "fixture_id,signals,expected",
        PROFILE_BOUNDARY_FIXTURES,
        ids=[row[0] for row in PROFILE_BOUNDARY_FIXTURES],
    )
    def test_golden_boundary_fixtures(self, fixture_id, signals, expected):
        assert classify_shop_profile(signals) == expected


ANCHOR = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def shop_with_analytics_data(session, user_id):
    user = User(id=user_id, phone="+84901113344")
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name="Analytics Aggregate Shop",
        tiktok_shop_id="7658073774813611785",
        created_at=datetime.now(UTC) - timedelta(days=120),
    )
    session.add_all([user, shop])
    await session.flush()

    now = datetime.now(UTC)
    analytics_rows = [
        AnalyticsPerformanceInterval(
            id=uuid.uuid4(),
            shop_id=shop.id,
            snapshot_key="shop:2026-07-13:2026-07-14",
            grain="shop",
            start_date=datetime(2026, 7, 13).date(),
            end_date=datetime(2026, 7, 14).date(),
            gmv=Decimal("6408074.00"),
            gmv_currency="VND",
            conversion_rate=Decimal("0.0759"),
            visitors=303,
            update_time=now,
        ),
        AnalyticsPerformanceInterval(
            id=uuid.uuid4(),
            shop_id=shop.id,
            snapshot_key="product:prod-1:2026-07-13:2026-07-14",
            grain="product",
            start_date=datetime(2026, 7, 13).date(),
            end_date=datetime(2026, 7, 14).date(),
            tiktok_product_id="prod-1",
            gmv=Decimal("500000.00"),
            gmv_currency="VND",
            ctr=Decimal("0.042000"),
            update_time=now,
        ),
        AnalyticsPerformanceInterval(
            id=uuid.uuid4(),
            shop_id=shop.id,
            snapshot_key="product:prod-2:2026-07-13:2026-07-14",
            grain="product",
            start_date=datetime(2026, 7, 13).date(),
            end_date=datetime(2026, 7, 14).date(),
            tiktok_product_id="prod-2",
            gmv=Decimal("300000.00"),
            gmv_currency="VND",
            ctr=Decimal("0.058000"),
            update_time=now,
        ),
        AnalyticsPerformanceInterval(
            id=uuid.uuid4(),
            shop_id=shop.id,
            snapshot_key="sku:sku-1:2026-07-13:2026-07-14",
            grain="sku",
            start_date=datetime(2026, 7, 13).date(),
            end_date=datetime(2026, 7, 14).date(),
            tiktok_sku_id="sku-1",
            tiktok_product_id="prod-1",
            gmv=Decimal("250000.00"),
            gmv_currency="VND",
            update_time=now,
        ),
    ]
    session.add_all(analytics_rows)
    session.add(
        TikTokSyncState(
            id=uuid.uuid4(),
            shop_id=shop.id,
            endpoint="promotion_activity",
            last_update_time=1_700_000_000,
        )
    )
    await session.flush()
    return shop


class TestAnalyticsBackedAggregates:
    @pytest.mark.asyncio
    async def test_build_feature_aggregates_reads_analytics_sources(
        self, session, shop_with_analytics_data, monkeypatch
    ):
        shop = shop_with_analytics_data
        calls: list[str] = []

        original_analytics_list = AnalyticsPerformanceRepo.list
        original_sync_load = TikTokSyncStateRepo.load

        async def analytics_wrapped(self, shop_id, **kwargs):
            calls.append("analytics_performance_intervals")
            return await original_analytics_list(self, shop_id, **kwargs)

        async def sync_wrapped(self, shop_id):
            calls.append("tiktok_sync_state")
            return await original_sync_load(self, shop_id)

        monkeypatch.setattr(AnalyticsPerformanceRepo, "list", analytics_wrapped)
        monkeypatch.setattr(TikTokSyncStateRepo, "load", sync_wrapped)

        snapshot = await build_feature_aggregates(session, shop.id, computed_at=ANCHOR)

        assert "analytics_performance_intervals" in calls
        assert "tiktok_sync_state" in calls
        assert "analytics_performance_intervals" in snapshot.data_sources
        assert "tiktok_sync_state" in snapshot.data_sources

    @pytest.mark.asyncio
    async def test_analytics_shop_traffic_conversion_from_a36(
        self, session, shop_with_analytics_data
    ):
        snapshot = await build_feature_aggregates(
            session, shop_with_analytics_data.id, computed_at=ANCHOR
        )
        kpis = snapshot.computed_kpis
        assert kpis is not None
        assert kpis.shop_traffic_conversion_rate == pytest.approx(0.0759)
        assert kpis.analytics_shop_gmv_30d == Decimal("6408074.00")

    @pytest.mark.asyncio
    async def test_analytics_product_gmv_and_ctr_rollups(
        self, session, shop_with_analytics_data
    ):
        snapshot = await build_feature_aggregates(
            session, shop_with_analytics_data.id, computed_at=ANCHOR
        )
        kpis = snapshot.computed_kpis
        assert kpis is not None
        assert kpis.analytics_product_gmv_30d == Decimal("800000.00")
        assert kpis.analytics_sku_gmv_30d == Decimal("250000.00")
        assert kpis.analytics_weighted_product_ctr == pytest.approx(0.05)

    @pytest.mark.asyncio
    async def test_promotion_activity_join_for_revenue_denominator(
        self, session, shop_with_analytics_data
    ):
        snapshot = await build_feature_aggregates(
            session, shop_with_analytics_data.id, computed_at=ANCHOR
        )
        kpis = snapshot.computed_kpis
        assert kpis is not None
        assert kpis.promotion_activity_partition_present is True
        assert kpis.analytics_revenue_denominator == Decimal("6408074.00")
        assert kpis.analytics_spend_denominator is None

    @pytest.mark.asyncio
    async def test_null_when_analytics_partition_missing(
        self, session, shop_with_synced_data
    ):
        snapshot = await build_feature_aggregates(
            session, shop_with_synced_data.id, computed_at=ANCHOR
        )
        kpis = snapshot.computed_kpis
        assert kpis is not None
        assert kpis.shop_traffic_conversion_rate is None
        assert kpis.analytics_shop_gmv_30d is None
        assert kpis.analytics_product_gmv_30d is None
        assert kpis.analytics_sku_gmv_30d is None
        assert kpis.analytics_weighted_product_ctr is None
        assert kpis.analytics_revenue_denominator is None
        assert kpis.promotion_activity_partition_present is False
