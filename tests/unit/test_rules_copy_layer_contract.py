"""Issue #304 / #427 — P2-B2 rules-based copy layer contract tests.

AC1 → copy generated from rule signals without Ollama/Claude
AC2 → template catalog documented (MODULE.md + WORKFLOW_COPY_TEMPLATE_KEYS)
#427 → Ads KPI-linked recommendations emit rules copy with signal one_line in why
"""

from __future__ import annotations

import ast
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio

from juli_backend.models.models import Order, Product, Return, Shop, User
from juli_backend.services.aggregates.computed_kpis import ComputedKpiMetrics
from juli_backend.services.aggregates.types import (
    FeatureAggregateSnapshot,
    HealthDataSource,
    ShopLifecycleContext,
    ShopProfile,
)
from juli_backend.services.scoring.copy_layer import (
    COPY_SOURCE_RULES,
    WORKFLOW_COPY_TEMPLATE_KEYS,
    build_reasoning_for_recommendations,
    build_workflow_reasoning_copy,
)
from juli_backend.services.scoring.kpi_catalog import (
    MID_LARGE_WORKFLOW_KEYS,
    NEW_SHOP_WORKFLOW_KEYS,
)
from juli_backend.services.scoring.pipeline import run_daily_scoring_for_shop
from juli_backend.services.scoring.recommendations import rank_workflow_recommendations
from juli_backend.services.scoring.signals import compute_scoring_signals
from juli_backend.services.scoring.types import WorkflowReasoningCopy

REPO_ROOT = Path(__file__).resolve().parents[2]
COPY_LAYER_PATH = REPO_ROOT / "backend/src/juli_backend/services/scoring/copy_layer.py"
SCORING_MODULE = REPO_ROOT / "backend/src/juli_backend/services/scoring/MODULE.md"

FORBIDDEN_LLM_IMPORT_PREFIXES = (
    "anthropic",
    "ollama",
    "openai",
    "langchain",
    "dspy",
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


def _mid_large_snapshot() -> FeatureAggregateSnapshot:
    return FeatureAggregateSnapshot(
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


def _snapshot_with_computed_kpis(**kpi_overrides: object) -> FeatureAggregateSnapshot:
    defaults: dict[str, object] = {
        "total_units_sold_30d": 0,
        "avg_on_hand_inventory": None,
        "sku_count_with_inventory": 0,
        "stockout_sku_count": 0,
        "orders_with_ship_time_30d": 0,
        "orders_fulfilled_without_seller_fault_30d": 0,
        "orders_at_sla_risk_count": 0,
        "seller_fault_order_count_30d": 0,
        "order_items_count_30d": 0,
        "top_category_name": None,
        "unique_buyers_30d": 10,
        "repeat_buyers_30d": 0,
        "return_rate_30d": None,
        "inventory_turnover": None,
        "dsi_days": None,
        "stockout_rate": None,
        "fulfillment_accuracy_rate": None,
        "seller_fault_cancellation_rate": None,
        "conversion_rate_by_category": None,
        "repeat_purchase_rate": None,
        "after_sales_handling_time_hours": None,
        "csat_proxy_score": None,
        "shop_traffic_conversion_rate": None,
        "analytics_shop_gmv_30d": None,
        "analytics_product_gmv_30d": None,
        "analytics_sku_gmv_30d": None,
        "analytics_weighted_product_ctr": None,
        "promotion_activity_partition_present": False,
        "analytics_revenue_denominator": None,
        "analytics_spend_denominator": None,
    }
    defaults.update(kpi_overrides)
    return FeatureAggregateSnapshot(
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
        data_sources=["orders", "products", "returns", "analytics_performance_intervals"],
        computed_kpis=ComputedKpiMetrics(**defaults),  # type: ignore[arg-type]
    )


_FIXED_AT = datetime(2026, 7, 12, 8, 0, tzinfo=UTC)


def _ads_kpi_linked_copy(
    kpi_id: str,
    **kpi_overrides: object,
) -> tuple[WorkflowReasoningCopy, str, str]:
    """Build rules copy for the first recommendation linked to an Ads KPI."""
    snapshot = _snapshot_with_computed_kpis(**kpi_overrides)
    signals = compute_scoring_signals(snapshot, computed_at=_FIXED_AT, products=[])
    signal = signals.kpis[kpi_id]
    assert signal.signal_type != "unavailable", f"{kpi_id} must emit live signal"

    recommendations = rank_workflow_recommendations(ShopProfile.MID_LARGE_SHOP, signals)
    linked = [
        item
        for item in recommendations.recommended_workflows
        if kpi_id in item.source_kpi_ids
    ]
    assert linked, f"expected workflow recommendation linked to {kpi_id}"

    copy = build_workflow_reasoning_copy(linked[0], signals)
    return copy, signal.one_line, linked[0].workflow_key


class TestNoLlmImportsInCopyLayer:
    def test_copy_layer_module_has_no_llm_provider_imports(self):
        imports = _import_names_from_module(COPY_LAYER_PATH)
        for forbidden in FORBIDDEN_LLM_IMPORT_PREFIXES:
            matches = [name for name in imports if name.startswith(forbidden)]
            assert not matches, f"copy_layer imports forbidden LLM path: {matches}"


class TestWorkflowReasoningCopyEnvelope:
    def test_build_workflow_reasoning_copy_returns_rules_envelope(self):
        snapshot = _mid_large_snapshot()
        signals = compute_scoring_signals(
            snapshot,
            computed_at=datetime(2026, 7, 12, 8, 0, tzinfo=UTC),
            products=[],
        )
        recommendations = rank_workflow_recommendations(ShopProfile.MID_LARGE_SHOP, signals)
        assert recommendations.recommended_workflows

        reasoning = build_workflow_reasoning_copy(
            recommendations.recommended_workflows[0],
            signals,
        )

        assert isinstance(reasoning, WorkflowReasoningCopy)
        assert reasoning.copy_source == COPY_SOURCE_RULES
        assert len(reasoning.why) > 10
        assert len(reasoning.expected_impact) > 5
        assert len(reasoning.next_steps) >= 2
        assert reasoning.source_kpi_ids == recommendations.recommended_workflows[0].source_kpi_ids


class TestTemplateCatalogCoverage:
    def test_template_keys_cover_all_profile_eligible_workflows(self):
        eligible = NEW_SHOP_WORKFLOW_KEYS | MID_LARGE_WORKFLOW_KEYS
        assert WORKFLOW_COPY_TEMPLATE_KEYS == eligible

    def test_module_documents_template_catalog(self):
        text = SCORING_MODULE.read_text(encoding="utf-8")
        assert "Template catalog" in text
        for key in sorted(WORKFLOW_COPY_TEMPLATE_KEYS):
            assert key in text


class TestAdsKpiLinkedCopyContract:
    """Issue #427 — live Ads KPI signals produce rules copy without new templates."""

    @pytest.mark.parametrize(
        ("kpi_id", "kpi_overrides", "why_fragment", "workflow_key"),
        [
            (
                "ctr",
                {"analytics_weighted_product_ctr": 0.012},
                "CTR 1.2%",
                "create_activity_7a",
            ),
            (
                "ctr",
                {"analytics_weighted_product_ctr": 0.035},
                "CTR 3.5%",
                "create_activity_7a",
            ),
            (
                "roas",
                {
                    "promotion_activity_partition_present": True,
                    "analytics_spend_denominator": 1_000_000.0,
                    "analytics_revenue_denominator": 1_500_000.0,
                },
                "ROAS 1.5x",
                "create_activity_7a",
            ),
            (
                "roas",
                {
                    "promotion_activity_partition_present": True,
                    "analytics_spend_denominator": 1_000_000.0,
                    "analytics_revenue_denominator": 3_000_000.0,
                },
                "ROAS 3.0x",
                "create_activity_7a",
            ),
            (
                "cac",
                {
                    "promotion_activity_partition_present": True,
                    "analytics_spend_denominator": 6_000_000.0,
                    "unique_buyers_30d": 10,
                },
                "CAC 600,000",
                "delete_activity_7b",
            ),
            (
                "cac",
                {
                    "promotion_activity_partition_present": True,
                    "analytics_spend_denominator": 2_000_000.0,
                    "unique_buyers_30d": 10,
                },
                "CAC 200,000",
                "delete_activity_7b",
            ),
        ],
    )
    def test_ads_kpi_linked_recommendation_emits_rules_copy(
        self,
        kpi_id: str,
        kpi_overrides: dict[str, object],
        why_fragment: str,
        workflow_key: str,
    ):
        copy, one_line, linked_workflow = _ads_kpi_linked_copy(kpi_id, **kpi_overrides)

        assert copy.copy_source == COPY_SOURCE_RULES
        assert linked_workflow == workflow_key
        assert one_line in copy.why
        assert why_fragment in copy.why
        assert len(copy.next_steps) >= 2
        joined_steps = " ".join(copy.next_steps)
        assert "ROAS" in joined_steps or "CAC" in joined_steps or "quảng cáo" in joined_steps


class TestCopyReferencesOnlySourceSignals:
    def test_why_text_derives_from_linked_advisory_signals_only(self):
        snapshot = _mid_large_snapshot()
        signals = compute_scoring_signals(
            snapshot,
            computed_at=datetime(2026, 7, 12, 8, 0, tzinfo=UTC),
            products=[],
        )
        recommendations = rank_workflow_recommendations(ShopProfile.MID_LARGE_SHOP, signals)
        top = recommendations.recommended_workflows[0]
        reasoning = build_workflow_reasoning_copy(top, signals)

        linked_lines = [
            signals.kpis[kpi_id].one_line
            for kpi_id in top.source_kpi_ids
            if signals.kpis[kpi_id].signal_type != "unavailable"
        ]
        assert linked_lines
        assert any(fragment in reasoning.why for fragment in linked_lines)


class TestDeterministicCopyGeneration:
    def test_same_inputs_produce_identical_reasoning(self):
        snapshot = _mid_large_snapshot()
        fixed_at = datetime(2026, 7, 12, 8, 0, tzinfo=UTC)
        signals = compute_scoring_signals(snapshot, computed_at=fixed_at, products=[])
        recommendations = rank_workflow_recommendations(ShopProfile.MID_LARGE_SHOP, signals)

        first = build_reasoning_for_recommendations(recommendations, signals)
        second = build_reasoning_for_recommendations(recommendations, signals)
        assert first == second


class TestPipelineWiresCopyLayer:
    @pytest_asyncio.fixture
    async def mid_large_shop_with_synced_data(self, session, user_id):
        user = User(id=user_id, phone="+84901112233")
        shop = Shop(
            id=uuid.uuid4(),
            user_id=user_id,
            shop_name="Copy Layer Shop",
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

    @pytest.mark.asyncio
    async def test_daily_scoring_result_includes_reasoning_summaries(
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

        assert len(result.reasoning_summaries) == len(result.recommendations.recommended_workflows)
        for summary in result.reasoning_summaries:
            assert summary.copy.copy_source == COPY_SOURCE_RULES
            assert summary.workflow_key
            assert summary.copy.why
