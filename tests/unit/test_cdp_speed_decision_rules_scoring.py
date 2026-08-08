"""Issue #714 — B-2 Rules Scoring Wire, continuous-trigger callable.

AC1 → golden/regression: continuous-trigger scoring output matches manual-refresh
      output for identical fixture inputs
AC2 → the scoring callable is shared — a single implementation used by both the
      continuous job and the manual refresh endpoint (no duplicated business logic)
AC3 → rules copy layer sourced normally (seller-language dictionary, ADR-028) —
      no backend jargon in generated copy

Scope: B-2 delivers the callable and its wiring into the seam only. Action Card
persistence on compute is #715 (B-3); the emission budget is #716 (B-4) — neither
is exercised here.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio

from juli_backend.models.models import Order, Product, Return, Shop, User
from juli_backend.services.aggregates.types import HealthDataSource, ShopLifecycleContext
from juli_backend.services.cdp_speed.decision_rules_scoring import decision_rules_scoring_stage
from juli_backend.services.cdp_speed.shared_compute_orchestrator import SharedComputeJob
from juli_backend.services.cdp_speed.targeted_fetch_planner import TargetedFetchPlan
from juli_backend.services.scoring.pipeline import run_daily_scoring_for_shop
from juli_backend.services.scoring.types import DailyScoringResult

COMPUTED_AT = datetime(2026, 8, 1, 8, 0, tzinfo=UTC)

# Backend-internal identifiers that must never leak into seller-facing rules copy.
_BACKEND_JARGON_TOKENS = (
    "kpi_id",
    "workflow_key",
    "AdvisorySignal",
    "WorkflowRecommendation",
    "signal_type",
    "rules_proxy",
    "T3",
    "T7",
    "None",
    "uuid",
    "Decimal",
)


def _empty_fetch_plan(shop_key: str) -> TargetedFetchPlan:
    return TargetedFetchPlan(catalog_id=None, shop_id=shop_key, resources=())


def _make_job(shop: Shop, *, idempotency_key: str = "job-714-b2") -> SharedComputeJob:
    return SharedComputeJob(
        shop_id=shop.id,
        shop_key=shop.tiktok_shop_id,
        enqueue_reason="webhook_catalog:1",
        fetch_plan=_empty_fetch_plan(shop.tiktok_shop_id),
        idempotency_key=idempotency_key,
    )


@pytest_asyncio.fixture
async def shop_with_synced_data(session, user_id):
    """Mid/large shop with commerce data — same shape used by the manual refresh
    pipeline's own contract tests (test_daily_batch_scoring_contract.py)."""
    user = User(id=user_id, phone="+84901714714")
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name="Continuous Trigger Scoring Shop",
        tiktok_shop_id="tiktok_shop_714_b2",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    session.add_all([user, shop])
    now = COMPUTED_AT
    products = [
        Product(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id="prod-714-a",
            name="Widget A",
            status="ACTIVE",
            revenue=Decimal("800000"),
            units_sold=40,
            update_time=now,
        ),
        Product(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id="prod-714-b",
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
            tiktok_order_id=f"ord-714-{index}",
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
            tiktok_return_id="ret-714-1",
            tiktok_order_id="ord-714-1",
            return_type="refund",
            refund_amount=Decimal("10000"),
            status="COMPLETED",
            update_time=now,
        ),
    ]
    session.add_all([*products, *orders, *returns])
    await session.flush()
    return shop


class TestContinuousTriggerMatchesManualRefreshOutput:
    """AC1 — golden/regression parity between the two entry points."""

    @pytest.mark.asyncio
    async def test_continuous_trigger_output_equals_manual_refresh_output(
        self, session, shop_with_synced_data
    ):
        lifecycle = ShopLifecycleContext(
            probation_status="graduated",
            health_data_source=HealthDataSource.PROXY,
        )

        manual_result = await run_daily_scoring_for_shop(
            session,
            shop_with_synced_data.id,
            lifecycle=lifecycle,
            computed_at=COMPUTED_AT,
        )

        job = _make_job(shop_with_synced_data)
        continuous_result = await decision_rules_scoring_stage(
            session,
            job,
            lifecycle=lifecycle,
            computed_at=COMPUTED_AT,
        )

        assert isinstance(continuous_result, DailyScoringResult)
        # Full structural equality: aggregates, signals, ranked recommendations,
        # and rules copy must be byte-for-byte identical for identical inputs —
        # no forked or parallel scoring math (ADR-021).
        assert continuous_result.aggregates == manual_result.aggregates
        assert continuous_result.signals == manual_result.signals
        assert continuous_result.recommendations == manual_result.recommendations
        assert continuous_result.reasoning_summaries == manual_result.reasoning_summaries
        assert continuous_result == manual_result

        # Sanity: the fixture actually exercises non-trivial output, not two
        # empty results trivially equal to each other.
        assert len(continuous_result.recommendations.recommended_workflows) > 0

    @pytest.mark.asyncio
    async def test_continuous_trigger_defaults_match_manual_refresh_defaults(
        self, session, shop_with_synced_data
    ):
        """Same parity holds with default lifecycle/computed_at (no explicit override)."""
        manual_result = await run_daily_scoring_for_shop(
            session,
            shop_with_synced_data.id,
            computed_at=COMPUTED_AT,
        )
        job = _make_job(shop_with_synced_data, idempotency_key="job-714-b2-defaults")
        continuous_result = await decision_rules_scoring_stage(
            session,
            job,
            computed_at=COMPUTED_AT,
        )

        assert continuous_result == manual_result


class TestScoringCallableIsSharedNoDuplicatedLogic:
    """AC2 — one implementation, reused (not reimplemented) by both entry points."""

    def test_continuous_and_manual_paths_call_the_identical_function_object(self):
        import juli_backend.services.action_cards.refresh as manual_refresh_mod
        import juli_backend.services.cdp_speed.decision_rules_scoring as continuous_mod

        # Both modules must hold a reference to the exact same run_daily_scoring_for_shop
        # function object — proves there is one scoring implementation, not two call
        # sites that happen to produce equal output today and can drift tomorrow.
        assert (
            continuous_mod.run_daily_scoring_for_shop
            is manual_refresh_mod.run_daily_scoring_for_shop
        )

    @pytest.mark.asyncio
    async def test_decision_rules_scoring_stage_delegates_to_run_daily_scoring_for_shop(
        self, session, shop_with_synced_data, monkeypatch
    ):
        import juli_backend.services.cdp_speed.decision_rules_scoring as continuous_mod

        calls: list[tuple[uuid.UUID, object, object]] = []
        original = continuous_mod.run_daily_scoring_for_shop

        async def tracked(session_arg, shop_id, **kwargs):
            calls.append((shop_id, kwargs.get("lifecycle"), kwargs.get("computed_at")))
            return await original(session_arg, shop_id, **kwargs)

        monkeypatch.setattr(continuous_mod, "run_daily_scoring_for_shop", tracked)

        job = _make_job(shop_with_synced_data, idempotency_key="job-714-b2-delegate")
        await decision_rules_scoring_stage(session, job, computed_at=COMPUTED_AT)

        assert calls == [(shop_with_synced_data.id, None, COMPUTED_AT)]

    def test_decision_rules_scoring_module_defines_no_forked_scoring_math(self):
        """Static guard: the adapter module must not reimplement aggregates/signals/
        recommendations/copy logic — it may only import and call the shared pipeline."""
        import inspect

        import juli_backend.services.cdp_speed.decision_rules_scoring as continuous_mod

        source = inspect.getsource(continuous_mod)
        forbidden_reimplementation_markers = (
            "def compute_scoring_signals",
            "def rank_workflow_recommendations",
            "def build_feature_aggregates",
            "def build_reasoning_for_recommendations",
        )
        for marker in forbidden_reimplementation_markers:
            assert marker not in source


class TestWiringIntoTheContinuousTriggerSeam:
    """Wiring of the callable into the B-1 dispatch seam at the production
    continuous-trigger call site (services/webhook/material_worker.py)."""

    @pytest.mark.asyncio
    async def test_hourly_reconcile_wires_decision_rules_scoring_stage(self, session, monkeypatch):
        """Gap-2 (coordinator follow-up on #714): the hourly Mock reconcile path
        (workers/tasks/mock_analytics_reconcile.py) is also a continuous trigger
        per PRD #599 user story 30 — gap reconciliation must heal Decision
        staleness the same way it heals KPI envelope staleness. Mirrors the
        material_worker.py wiring test above for the reconcile call site."""
        from juli_backend.workers.tasks import mock_analytics_reconcile

        captured: dict = {}

        async def spy_run_shared_compute_job(sess, job, **kwargs):
            captured.update(kwargs)
            return None

        monkeypatch.setattr(
            mock_analytics_reconcile, "run_shared_compute_job", spy_run_shared_compute_job
        )

        await mock_analytics_reconcile.run_mock_analytics_reconcile_orchestrated(
            session=session,
            shop_id=uuid.uuid4(),
            shop_key="tiktok_shop_714_b2_reconcile",
        )

        assert captured.get("scoring_stage") is decision_rules_scoring_stage

    @pytest.mark.asyncio
    async def test_default_shared_compute_wires_decision_rules_scoring_stage(
        self, session, shop_with_synced_data, monkeypatch
    ):
        from juli_backend.services.webhook import material_worker

        captured: dict = {}

        async def spy_run_shared_compute_job(sess, job, *, fetch_executor=None, **kwargs):
            captured.update(kwargs)
            captured["fetch_executor"] = fetch_executor
            from juli_backend.services.cdp_speed.shared_compute_orchestrator import (
                SharedComputeResult,
            )

            return SharedComputeResult(bronze_appended=0, silver_promoted=0, gold_written=True)

        monkeypatch.setattr(material_worker, "run_shared_compute_job", spy_run_shared_compute_job)

        job = _make_job(shop_with_synced_data, idempotency_key="job-714-b2-wiring")
        await material_worker._default_shared_compute(session, job)

        assert captured.get("scoring_stage") is decision_rules_scoring_stage

    @pytest.mark.asyncio
    async def test_orchestrator_dispatches_real_scoring_stage_end_to_end(
        self, session, shop_with_synced_data
    ):
        """The real (non-stub) callable runs through SharedComputeOrchestrator when
        the seam is enabled, producing an actual scoring result — not the B-1 no-op."""
        from juli_backend.services.cdp_speed.shared_compute_orchestrator import (
            run_shared_compute_job,
        )

        job = _make_job(shop_with_synced_data, idempotency_key="job-714-b2-e2e")

        async def _no_fetch(sess, *, shop_id, shop_key, fetch_plan, idempotency_key):
            from juli_backend.services.cdp_speed.targeted_fetch_bronze_handoff import (
                BronzeAppendTracker,
            )

            return BronzeAppendTracker()

        result = await run_shared_compute_job(
            session,
            job,
            fetch_executor=_no_fetch,
            scoring_stage=decision_rules_scoring_stage,
            scoring_enabled=True,
        )

        assert result.scoring_dispatched is True
        assert result.scoring_succeeded is True


class TestRulesCopySourcedNormally:
    """AC3 — copy layer sourced via the normal rules-only path (ADR-028), not
    backend jargon."""

    @pytest.mark.asyncio
    async def test_continuous_trigger_reasoning_copy_is_rules_sourced_and_jargon_free(
        self, session, shop_with_synced_data
    ):
        job = _make_job(shop_with_synced_data, idempotency_key="job-714-b2-copy")
        result = await decision_rules_scoring_stage(session, job, computed_at=COMPUTED_AT)

        assert result.reasoning_summaries, "fixture must produce at least one ranked card"

        for summary in result.reasoning_summaries:
            copy = summary.copy
            assert copy.copy_source == "rules"
            assert copy.why.strip()
            assert copy.next_steps
            assert all(step.strip() for step in copy.next_steps)

            copy_text = copy.why + " " + " ".join(copy.next_steps)
            for token in _BACKEND_JARGON_TOKENS:
                assert token not in copy_text, f"backend jargon leaked into copy: {token!r}"

            # Seller-language dictionary output is Vietnamese (ADR-028) — spot check
            # for Vietnamese diacritics or known Vietnamese function words rather than
            # asserting on any single fixed string (templates vary by workflow_key).
            assert re.search(
                r"[àáảãạăằắẳẵặâầấẩẫậđèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ]",
                copy_text.lower(),
            )
