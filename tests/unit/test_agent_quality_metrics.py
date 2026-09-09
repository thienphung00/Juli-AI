"""Three metrics, three sources, three denominators — never averaged
(issue #1656 / W8-D / P10-4, parent PRD #1652).

``services.operations.quality_metrics`` answers three of P10's four questions,
each from its OWN source and over its OWN denominator:

    Was Juli right?        recommendation quality  / recommendations with an
                                                     observed outcome
    Did sellers agree?     approval rate           / cards surfaced
    Did Juli do the job?   execution quality       / runs started

**The refusal is the requirement.** There is no function, field or return
value anywhere in the module that blends the three into one number, and that
is asserted STRUCTURALLY here rather than left to review — a blended score is
the one artefact that lets a good approval rate hide a bad outcome.

**Real Postgres, never SQLite.** The empty-denominator rule turns on what an
aggregate over zero rows actually returns, and the seller-decision counts ride
on outer-join semantics across ``action_cards`` and ``workflow_runs``; both
are Postgres behaviours. This module spins up its own throwaway database
migrated to head, exactly as ``tests/unit/test_outcome_chain_query.py`` does,
and skips loudly when ``DATABASE_URL`` is not a reachable Postgres.

**The load-bearing run is a REAL run.** The recommendation-quality dataset
goes through the real ``WorkflowRunner`` and the real ``ToolExecutionLedger``
(``tests/support/quality_metrics.py``), because ``impact_readings`` cannot
exist without a ``tool_executions`` row and because the one case #1220
preserved — ``stop_reason=final_response`` with ``required_steps_completed
=False`` — is produced here by the runner itself rather than asserted against
a hand-set column.
"""

from __future__ import annotations

import inspect
import typing
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from juli_backend.core.config.runtime import async_database_url
from juli_backend.models.models import ImpactReading
from juli_backend.services.action_cards.persist import IN_FLIGHT_STATUSES
from juli_backend.services.agent.status import StopReason, WorkflowRunStatus
from juli_backend.services.operations import quality_metrics
from juli_backend.services.operations.quality_metrics import (
    ApprovalRate,
    ExecutionQuality,
    NoData,
    RecommendationQuality,
    approval_rate,
    execution_quality,
    recommendation_quality,
)
from tests.support.outcome_chain import (
    create_disposable_database_at_head,
    seed_shop_and_product,
)
from tests.support.postgres import requires_postgres
from tests.support.quality_metrics import (
    seed_card,
    seed_recommendation_with_observed_outcome,
    seed_run,
    set_run_outcome,
)

pytestmark = requires_postgres

#: The complete ``action_cards.status`` vocabulary in the tree today —
#: ``persist.py``'s own ``IN_FLIGHT_STATUSES`` plus the ``"active"`` candidate
#: status it upserts. Built from the production constant rather than retyped,
#: so a new status value fails these tests instead of silently landing in a
#: residual bucket.
CARD_STATUSES = frozenset({"active"}) | IN_FLIGHT_STATUSES


@pytest.fixture(scope="module")
def disposable_postgres_url() -> Iterator[str]:
    yield from create_disposable_database_at_head("juli_quality_metrics")


@pytest_asyncio.fixture
async def session_factory(disposable_postgres_url: str):
    engine = create_async_engine(async_database_url(disposable_postgres_url), poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def sync_session(disposable_postgres_url: str) -> Iterator[Session]:
    engine = create_engine(disposable_postgres_url)
    sess = sessionmaker(bind=engine)()
    try:
        yield sess
    finally:
        sess.close()
        engine.dispose()


@dataclass(frozen=True, slots=True)
class Dataset:
    """One shared population the three metrics disagree about, on purpose."""

    shop_id: uuid.UUID
    product_id: uuid.UUID
    tiktok_product_id: str
    approved_card_id: uuid.UUID
    dismissed_card_id: uuid.UUID
    pending_card_id: uuid.UUID
    unsurfaced_card_id: uuid.UUID
    observed_card_id: uuid.UUID
    real_run_id: uuid.UUID
    completed_run_id: uuid.UUID
    undetermined_run_id: uuid.UUID


@pytest_asyncio.fixture
async def dataset(session_factory, sync_session: Session) -> Dataset:
    """Four surfaced cards, three started runs, one recommendation with an
    observed outcome — three populations of three different sizes, seeded
    source by source so no helper writes two sources at once.
    """
    now = datetime.now(UTC)
    shop_id, product_id, tiktok_product_id = await seed_shop_and_product(session_factory)

    observed_card_id, real_run_id, _ = await seed_recommendation_with_observed_outcome(
        session_factory,
        sync_session,
        shop_id=shop_id,
        product_id=product_id,
        tiktok_product_id=tiktok_product_id,
        pre=Decimal("100.00"),
        post=Decimal("120.00"),
    )

    approved_card_id = await seed_card(
        session_factory, shop_id, status="approved", surfaced_at=now, approved_at=now
    )
    dismissed_card_id = await seed_card(
        session_factory, shop_id, status="dismissed", surfaced_at=now, dismissed_at=now
    )
    pending_card_id = await seed_card(session_factory, shop_id, status="active", surfaced_at=now)
    unsurfaced_card_id = await seed_card(
        session_factory, shop_id, status="active", suppressed_reason="active_cap"
    )

    completed_run_id = await seed_run(
        session_factory,
        shop_id,
        product_id,
        status=WorkflowRunStatus.COMPLETED,
        stop_reason=StopReason.FINAL_RESPONSE,
        required_steps_completed=True,
    )
    undetermined_run_id = await seed_run(
        session_factory,
        shop_id,
        product_id,
        status=WorkflowRunStatus.FAILED,
        stop_reason=StopReason.LLM_ERROR,
        required_steps_completed=None,
    )

    return Dataset(
        shop_id=shop_id,
        product_id=product_id,
        tiktok_product_id=tiktok_product_id,
        approved_card_id=approved_card_id,
        dismissed_card_id=dismissed_card_id,
        pending_card_id=pending_card_id,
        unsurfaced_card_id=unsurfaced_card_id,
        observed_card_id=observed_card_id,
        real_run_id=real_run_id,
        completed_run_id=completed_run_id,
        undetermined_run_id=undetermined_run_id,
    )


async def _all_three(session_factory, shop_id: uuid.UUID):
    async with session_factory() as session:
        return (
            await recommendation_quality(session, shop_id),
            await approval_rate(session, shop_id),
            await execution_quality(session, shop_id),
        )


# --------------------------------------------------------------------------
# AC1 — each metric is computed from its own source
# --------------------------------------------------------------------------


class TestOwnSourceIsolation:
    """Mutating exactly one source moves exactly one metric; the other two
    come back byte-identical (#1656 AC1)."""

    async def test_adding_action_cards_moves_only_the_approval_rate(
        self, session_factory, dataset: Dataset
    ):
        before_rec, before_approval, before_exec = await _all_three(
            session_factory, dataset.shop_id
        )

        await seed_card(
            session_factory,
            dataset.shop_id,
            status="approved",
            surfaced_at=datetime.now(UTC),
            approved_at=datetime.now(UTC),
        )

        after_rec, after_approval, after_exec = await _all_three(session_factory, dataset.shop_id)

        assert after_approval != before_approval
        assert after_approval.denominator == before_approval.denominator + 1
        assert after_rec == before_rec
        assert after_exec == before_exec

    async def test_changing_run_outcome_columns_moves_only_the_execution_quality(
        self, session_factory, dataset: Dataset
    ):
        before_rec, before_approval, before_exec = await _all_three(
            session_factory, dataset.shop_id
        )

        await set_run_outcome(
            session_factory,
            dataset.undetermined_run_id,
            stop_reason=StopReason.FINAL_RESPONSE,
            required_steps_completed=True,
        )

        after_rec, after_approval, after_exec = await _all_three(session_factory, dataset.shop_id)

        assert after_exec != before_exec
        assert after_exec.undetermined == before_exec.undetermined - 1
        assert after_rec == before_rec
        assert after_approval == before_approval

    async def test_changing_the_observed_outcome_moves_only_the_recommendation_quality(
        self, session_factory, dataset: Dataset
    ):
        """Flipping the reading to ``suppressed`` removes the only observed
        outcome — #1226/#1338's exclusion, reused rather than recopied."""
        before_rec, before_approval, before_exec = await _all_three(
            session_factory, dataset.shop_id
        )

        async with session_factory() as session:
            await session.execute(
                update(ImpactReading)
                .where(ImpactReading.run_id == dataset.real_run_id)
                .values(confidence="suppressed")
            )
            await session.commit()

        after_rec, after_approval, after_exec = await _all_three(session_factory, dataset.shop_id)

        assert after_rec != before_rec
        assert before_rec.denominator == 1
        assert after_rec.denominator == 0
        assert after_approval == before_approval
        assert after_exec == before_exec


# --------------------------------------------------------------------------
# AC2 — two disagreeing values, never averaged
# --------------------------------------------------------------------------


class TestMetricsThatDisagree:
    """A population with a HIGH approval rate and a LOW execution quality
    produces exactly that, as two separate values (#1656 AC2)."""

    async def test_high_approval_and_low_execution_stay_high_and_low(self, session_factory):
        now = datetime.now(UTC)
        shop_id, product_id, _ = await seed_shop_and_product(session_factory)

        for _ in range(9):
            await seed_card(
                session_factory, shop_id, status="approved", surfaced_at=now, approved_at=now
            )
        await seed_card(
            session_factory, shop_id, status="dismissed", surfaced_at=now, dismissed_at=now
        )

        await seed_run(
            session_factory,
            shop_id,
            product_id,
            status=WorkflowRunStatus.COMPLETED,
            stop_reason=StopReason.FINAL_RESPONSE,
            required_steps_completed=True,
        )
        for _ in range(9):
            await seed_run(
                session_factory,
                shop_id,
                product_id,
                status=WorkflowRunStatus.COMPLETED,
                stop_reason=StopReason.FINAL_RESPONSE,
                required_steps_completed=False,
            )

        async with session_factory() as session:
            approval = await approval_rate(session, shop_id)
            execution = await execution_quality(session, shop_id)

        assert approval.numerator == 9
        assert approval.denominator == 10
        assert approval.ratio == pytest.approx(0.9)

        assert execution.numerator == 1
        assert execution.denominator == 10
        assert execution.ratio == pytest.approx(0.1)

        # The average of the two (0.5) is nowhere in either answer.
        assert approval.ratio != execution.ratio


# --------------------------------------------------------------------------
# AC2 (second half) — the refusal, asserted structurally
# --------------------------------------------------------------------------


BLENDING_WORDS = (
    "aggregate",
    "overall",
    "score",
    "composite",
    "combined",
    "combine",
    "blend",
    "weighted",
    "health",
    "average",
)

METRIC_RESULTS = (RecommendationQuality, ApprovalRate, ExecutionQuality)


def _public_functions() -> dict[str, object]:
    return {
        name: getattr(quality_metrics, name)
        for name in quality_metrics.__all__
        if inspect.isfunction(getattr(quality_metrics, name))
    }


class TestNoBlendedFigure:
    """No code path returns a combined figure — enforced by a test, not only
    by review (#1656 AC2)."""

    def test_the_public_surface_names_no_blended_quantity(self):
        exported = set(quality_metrics.__all__)

        assert exported, "the module must declare its public surface in __all__"
        for name in exported:
            lowered = name.lower()
            for word in BLENDING_WORDS:
                assert word not in lowered, f"{name!r} names a blended quantity ({word!r})"

    def test_every_public_name_defined_in_the_module_is_declared(self):
        """``__all__`` is what the other structural tests read, so nothing may
        hide from them behind an undeclared public name."""
        defined = {
            name
            for name, obj in vars(quality_metrics).items()
            if not name.startswith("_")
            and getattr(obj, "__module__", None) == quality_metrics.__name__
        }

        assert defined <= set(quality_metrics.__all__)

    def test_exactly_three_public_functions_each_returning_one_metric(self):
        functions = _public_functions()

        assert set(functions) == {"approval_rate", "execution_quality", "recommendation_quality"}

        returned = []
        for name, func in functions.items():
            hints = typing.get_type_hints(func)
            annotation = hints["return"]
            assert annotation in METRIC_RESULTS, f"{name} does not return exactly one metric result"
            returned.append(annotation)

        assert len(set(returned)) == 3, "two functions return the same metric result type"

    def test_no_public_function_consumes_a_metric_result(self):
        """A function taking two results could only be building a third from
        them, which is the blend this slice refuses."""
        for name, func in _public_functions().items():
            hints = typing.get_type_hints(func)
            for parameter, annotation in hints.items():
                if parameter == "return":
                    continue
                assert annotation not in METRIC_RESULTS, (
                    f"{name} takes a metric result as {parameter!r}"
                )

    def test_no_metric_result_carries_another_metrics_denominator(self):
        """Each result owns its denominator; none reaches for a sibling's."""
        for result_type in METRIC_RESULTS:
            hints = typing.get_type_hints(result_type)
            for field, annotation in hints.items():
                assert annotation not in METRIC_RESULTS, (
                    f"{result_type.__name__}.{field} embeds another metric"
                )


# --------------------------------------------------------------------------
# AC3 — numerator and denominator, not a bare ratio
# --------------------------------------------------------------------------


class TestNumeratorAndDenominatorAreReadable:
    """An n of 3 must be visible, so every result exposes both terms
    (#1656 AC3)."""

    async def test_each_metric_reports_both_terms_alongside_its_ratio(
        self, session_factory, dataset: Dataset
    ):
        rec, approval, execution = await _all_three(session_factory, dataset.shop_id)

        for result in (rec, approval, execution):
            assert isinstance(result.numerator, int)
            assert isinstance(result.denominator, int)
            assert not isinstance(result, float)

        assert (rec.numerator, rec.denominator) == (1, 1)
        assert (approval.numerator, approval.denominator) == (2, 4)
        assert (execution.numerator, execution.denominator) == (1, 3)

    async def test_the_ratio_is_derivable_from_the_two_terms_the_result_carries(
        self, session_factory, dataset: Dataset
    ):
        _, approval, _ = await _all_three(session_factory, dataset.shop_id)

        assert approval.ratio == pytest.approx(approval.numerator / approval.denominator)


# --------------------------------------------------------------------------
# The three denominators are three different populations
# --------------------------------------------------------------------------


class TestThreeDifferentDenominators:
    """'Recommendations with an observed outcome', 'cards surfaced' and 'runs
    started' are not the same count and are never divided by one shared
    number."""

    async def test_one_dataset_yields_three_different_denominators(
        self, session_factory, dataset: Dataset
    ):
        rec, approval, execution = await _all_three(session_factory, dataset.shop_id)

        denominators = (rec.denominator, approval.denominator, execution.denominator)

        assert denominators == (1, 4, 3)
        assert len(set(denominators)) == 3

    async def test_an_unsurfaced_card_is_outside_cards_surfaced(
        self, session_factory, dataset: Dataset
    ):
        """The denominator is 'cards surfaced', not 'cards scored' — the
        suppressed candidate the emission budget never surfaced is not a card
        any seller was asked about."""
        _, approval, _ = await _all_three(session_factory, dataset.shop_id)

        assert approval.denominator == 4
        assert dataset.unsurfaced_card_id is not None


# --------------------------------------------------------------------------
# AC4 — an empty denominator is "no data", never 0
# --------------------------------------------------------------------------


class TestEmptyDenominator:
    """ "We measured nothing" and "we measured no successes" are different
    facts, and the results are asserted UNEQUAL (#1656 AC4)."""

    async def test_an_empty_population_returns_no_data_for_all_three(self, session_factory):
        shop_id, _, _ = await seed_shop_and_product(session_factory)

        rec, approval, execution = await _all_three(session_factory, shop_id)

        for result in (rec, approval, execution):
            assert result.denominator == 0
            assert isinstance(result.ratio, NoData)
            assert result.ratio != 0
            assert result.ratio != 0.0
            assert not isinstance(result.ratio, float)

    async def test_no_data_is_not_equal_to_a_genuine_zero_numerator(
        self, session_factory, sync_session: Session
    ):
        now = datetime.now(UTC)
        empty_shop_id, _, _ = await seed_shop_and_product(session_factory)
        # A shop measured for the two row-counted metrics, and a second one
        # for recommendation quality: seeding an observed outcome necessarily
        # approves and surfaces a card, which would move the approval
        # numerator off zero and stop this test proving what it is about.
        counted_shop_id, counted_product_id, _ = await seed_shop_and_product(session_factory)
        observed_shop_id, observed_product_id, tiktok_product_id = await seed_shop_and_product(
            session_factory
        )

        await seed_card(
            session_factory,
            counted_shop_id,
            status="dismissed",
            surfaced_at=now,
            dismissed_at=now,
        )
        await seed_run(
            session_factory,
            counted_shop_id,
            counted_product_id,
            status=WorkflowRunStatus.COMPLETED,
            stop_reason=StopReason.FINAL_RESPONSE,
            required_steps_completed=False,
        )
        await seed_recommendation_with_observed_outcome(
            session_factory,
            sync_session,
            shop_id=observed_shop_id,
            product_id=observed_product_id,
            tiktok_product_id=tiktok_product_id,
            pre=Decimal("100.00"),
            post=Decimal("80.00"),
        )

        absent_rec, absent_approval, absent_execution = await _all_three(
            session_factory, empty_shop_id
        )
        _, zero_approval, zero_execution = await _all_three(session_factory, counted_shop_id)
        zero_rec, _, _ = await _all_three(session_factory, observed_shop_id)

        pairs = (
            (absent_rec, zero_rec),
            (absent_approval, zero_approval),
            (absent_execution, zero_execution),
        )
        for absent, zero in pairs:
            assert zero.numerator == 0
            assert zero.denominator > 0
            assert zero.ratio == 0.0
            assert absent.ratio != zero.ratio
            assert absent != zero


# --------------------------------------------------------------------------
# AC5 — expiry is counted apart from an explicit negative
# --------------------------------------------------------------------------


class TestExpiryIsNotRejection:
    """A seller who ran out of time did not disagree with Juli (#1656 AC5)."""

    async def test_an_expired_confirmation_is_counted_apart_from_a_dismissal(self, session_factory):
        now = datetime.now(UTC)
        shop_id, product_id, _ = await seed_shop_and_product(session_factory)

        expired_card_id = await seed_card(
            session_factory, shop_id, status="approved", surfaced_at=now, approved_at=now
        )
        await seed_run(
            session_factory,
            shop_id,
            product_id,
            action_card_id=expired_card_id,
            status=WorkflowRunStatus.CANCELLED,
            stop_reason=StopReason.CONFIRMATION_EXPIRED,
            required_steps_completed=False,
        )
        await seed_card(
            session_factory, shop_id, status="dismissed", surfaced_at=now, dismissed_at=now
        )
        await seed_card(
            session_factory, shop_id, status="approved", surfaced_at=now, approved_at=now
        )
        await seed_card(session_factory, shop_id, status="active", surfaced_at=now)

        async with session_factory() as session:
            approval = await approval_rate(session, shop_id)

        assert approval.expired == 1
        assert approval.dismissed == 1
        assert approval.approved == 1
        assert approval.pending == 1
        assert approval.denominator == 4
        assert approval.numerator == approval.approved

    async def test_every_surfaced_card_lands_in_exactly_one_decision_bucket(self, session_factory):
        now = datetime.now(UTC)
        shop_id, _, _ = await seed_shop_and_product(session_factory)
        for status in sorted(CARD_STATUSES):
            await seed_card(session_factory, shop_id, status=status, surfaced_at=now)

        async with session_factory() as session:
            approval = await approval_rate(session, shop_id)

        counted = approval.approved + approval.dismissed + approval.expired + approval.pending
        assert counted == approval.denominator == len(CARD_STATUSES)


class TestSellerDecisionVocabulary:
    """The mapping is stated against the vocabulary that EXISTS: there is no
    ``rejected`` and no ``expired`` ``action_cards.status``, and the only
    expiry signal in the tree is at RUN level."""

    def test_the_card_status_vocabulary_has_no_rejected_and_no_expired(self):
        assert CARD_STATUSES == {"active", "approved", "dismissed", "executing"}
        assert "rejected" not in CARD_STATUSES
        assert "expired" not in CARD_STATUSES

    def test_the_decision_buckets_cover_the_card_vocabulary_exactly(self):
        mapped = (
            quality_metrics.APPROVED_STATUSES
            | quality_metrics.DISMISSED_STATUSES
            | quality_metrics.PENDING_STATUSES
        )

        assert mapped == CARD_STATUSES
        assert not quality_metrics.APPROVED_STATUSES & quality_metrics.DISMISSED_STATUSES
        assert not quality_metrics.APPROVED_STATUSES & quality_metrics.PENDING_STATUSES
        assert not quality_metrics.DISMISSED_STATUSES & quality_metrics.PENDING_STATUSES

    def test_the_expiry_signal_is_the_run_level_stop_reason(self):
        assert quality_metrics.EXPIRY_STOP_REASON is StopReason.CONFIRMATION_EXPIRED
        assert quality_metrics.EXPIRY_STOP_REASON.value not in CARD_STATUSES


# --------------------------------------------------------------------------
# Execution quality reads required_steps_completed as its own fact (#1220)
# --------------------------------------------------------------------------


class TestExecutionQualityReadsRequiredSteps:
    """``required_steps_completed`` is a THIRD outcome fact, never derived
    from ``stop_reason`` and never folded into it (#1220)."""

    async def test_a_final_response_with_unfulfilled_required_steps_did_not_do_the_job(
        self, session_factory, dataset: Dataset
    ):
        """The run the real ``WorkflowRunner`` produced in ``dataset`` stopped
        on ``final_response`` while leaving a required step uncompleted — the
        exact case #1220 preserved."""
        async with session_factory() as session:
            execution = await execution_quality(session, dataset.shop_id)

        by_reason = {row.stop_reason: row.count for row in execution.stop_reasons}
        assert by_reason[StopReason.FINAL_RESPONSE.value] == 2
        assert execution.did_not_complete == 1
        assert execution.completed_with_required_steps == 1

    async def test_a_null_required_steps_completed_is_neither_success_nor_failure(
        self, session_factory
    ):
        shop_id, product_id, _ = await seed_shop_and_product(session_factory)
        await seed_run(
            session_factory,
            shop_id,
            product_id,
            status=WorkflowRunStatus.FAILED,
            stop_reason=StopReason.LLM_ERROR,
            required_steps_completed=None,
        )
        await seed_run(
            session_factory,
            shop_id,
            product_id,
            status=WorkflowRunStatus.COMPLETED,
            stop_reason=StopReason.FINAL_RESPONSE,
            required_steps_completed=True,
        )

        async with session_factory() as session:
            execution = await execution_quality(session, shop_id)

        assert execution.undetermined == 1
        assert execution.completed_with_required_steps == 1
        assert execution.did_not_complete == 0
        assert execution.denominator == 2
        assert execution.numerator == 1

    async def test_the_stop_reason_distribution_names_a_null_stop_reason_as_null(
        self, session_factory
    ):
        shop_id, product_id, _ = await seed_shop_and_product(session_factory)
        await seed_run(
            session_factory,
            shop_id,
            product_id,
            status=WorkflowRunStatus.QUEUED,
            stop_reason=None,
            required_steps_completed=None,
        )

        async with session_factory() as session:
            execution = await execution_quality(session, shop_id)

        assert [(row.stop_reason, row.count) for row in execution.stop_reasons] == [(None, 1)]
        assert execution.denominator == 1


# --------------------------------------------------------------------------
# Recommendation quality — scoring signal against the observed outcome
# --------------------------------------------------------------------------


class TestRecommendationQuality:
    """Was Juli right? The observed KPI window after the change, against the
    value before it — over recommendations that HAVE an observed outcome."""

    async def test_an_improved_observed_outcome_bears_the_recommendation_out(
        self, session_factory, dataset: Dataset
    ):
        async with session_factory() as session:
            rec = await recommendation_quality(session, dataset.shop_id)

        assert rec.borne_out == 1
        assert rec.not_borne_out == 0
        assert rec.not_comparable == 0
        assert rec.denominator == 1

    async def test_a_worsened_observed_outcome_does_not(
        self, session_factory, sync_session: Session
    ):
        shop_id, product_id, tiktok_product_id = await seed_shop_and_product(session_factory)
        await seed_recommendation_with_observed_outcome(
            session_factory,
            sync_session,
            shop_id=shop_id,
            product_id=product_id,
            tiktok_product_id=tiktok_product_id,
            pre=Decimal("100.00"),
            post=Decimal("80.00"),
        )

        async with session_factory() as session:
            rec = await recommendation_quality(session, shop_id)

        assert rec.borne_out == 0
        assert rec.not_borne_out == 1
        assert rec.denominator == 1

    async def test_a_run_with_no_observed_outcome_is_outside_the_denominator(self, session_factory):
        now = datetime.now(UTC)
        shop_id, product_id, _ = await seed_shop_and_product(session_factory)
        card_id = await seed_card(
            session_factory, shop_id, status="approved", surfaced_at=now, approved_at=now
        )
        await seed_run(
            session_factory,
            shop_id,
            product_id,
            action_card_id=card_id,
            status=WorkflowRunStatus.COMPLETED,
            stop_reason=StopReason.FINAL_RESPONSE,
            required_steps_completed=True,
        )

        async with session_factory() as session:
            rec = await recommendation_quality(session, shop_id)

        assert rec.denominator == 0
        assert isinstance(rec.ratio, NoData)


# --------------------------------------------------------------------------
# The window
# --------------------------------------------------------------------------


class TestWindow:
    """``since``/``until`` bound each metric over its own source's own
    timestamp — surfacing time for cards, creation time for runs."""

    async def test_rows_outside_the_window_are_not_counted(self, session_factory):
        now = datetime.now(UTC)
        long_ago = now - timedelta(days=90)
        shop_id, product_id, _ = await seed_shop_and_product(session_factory)

        await seed_card(
            session_factory, shop_id, status="approved", surfaced_at=long_ago, approved_at=long_ago
        )
        await seed_card(
            session_factory, shop_id, status="approved", surfaced_at=now, approved_at=now
        )
        await seed_run(
            session_factory,
            shop_id,
            product_id,
            status=WorkflowRunStatus.COMPLETED,
            stop_reason=StopReason.FINAL_RESPONSE,
            required_steps_completed=True,
            created_at=long_ago,
        )
        await seed_run(
            session_factory,
            shop_id,
            product_id,
            status=WorkflowRunStatus.COMPLETED,
            stop_reason=StopReason.FINAL_RESPONSE,
            required_steps_completed=True,
        )

        since = now - timedelta(days=1)
        async with session_factory() as session:
            approval = await approval_rate(session, shop_id, since=since)
            execution = await execution_quality(session, shop_id, since=since)
            rec = await recommendation_quality(session, shop_id, since=since)

        assert approval.denominator == 1
        assert execution.denominator == 1
        assert rec.denominator == 0


class TestTenantScoping:
    """A metric never counts another shop's rows."""

    async def test_another_shops_rows_are_not_counted(self, session_factory):
        now = datetime.now(UTC)
        mine, my_product, _ = await seed_shop_and_product(session_factory)
        theirs, their_product, _ = await seed_shop_and_product(session_factory)

        await seed_card(
            session_factory, theirs, status="approved", surfaced_at=now, approved_at=now
        )
        await seed_run(
            session_factory,
            theirs,
            their_product,
            status=WorkflowRunStatus.COMPLETED,
            stop_reason=StopReason.FINAL_RESPONSE,
            required_steps_completed=True,
        )
        await seed_card(session_factory, mine, status="active", surfaced_at=now)

        async with session_factory() as session:
            approval = await approval_rate(session, mine)
            execution = await execution_quality(session, mine)

        assert approval.denominator == 1
        assert approval.approved == 0
        assert execution.denominator == 0
        assert my_product is not None
