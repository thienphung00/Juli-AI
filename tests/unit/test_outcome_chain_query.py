"""The five-link outcome chain — one query, and an empty link says why
(issue #1655 / W8-C / P10-3, parent PRD #1652).

Given a ``workflow_run_id``, ``services.operations.outcome_chain`` answers the
whole post-hoc question in ONE database call:

    Recommendation (``action_cards`` via ``workflow_runs.action_card_id``)
    -> Action (``tool_executions.workflow_run_id``)
    -> TikTok state change (``workflow_outcome_records.execution_id``)
    -> Observed outcome (the KPI window after the change)
    -> Incremental impact (``impact_readings.run_id`` / ``tool_execution_id``)

and an empty link never reads as a bare ``null``: it carries ``pending`` (the
fact has not happened yet), ``unavailable`` (the fact cannot happen for this
run) or ``missing`` (it should exist and does not).

**Real Postgres, never SQLite.** The reason-vs-null distinction rides on
outer-join and nullable-FK semantics that only Postgres actually evaluates,
so this module spins up its own throwaway database from ``DATABASE_URL``'s
connection parameters and migrates it to head with the real Alembic chain —
the same convention ``tests/unit/test_agent_runner_ledger.py`` established
for exactly this reason (never DDL against ``DATABASE_URL``'s own database,
which the migration suites own outright). It skips loudly, never silently,
when ``DATABASE_URL`` is not a reachable Postgres instance. The harness that
does all of this lives in ``tests/support/outcome_chain.py``, shared with
``tests/integration/test_outcome_chain_postgres.py`` so the two suites can
never drift into proving different things.

**The run is seeded through the REAL ``WorkflowRunner``.** A hand-built row
set would prove the SQL and not the wiring, and the wiring is this slice's
actual risk. The write leg additionally routes through the REAL
``ToolExecutionLedger``, so the ``tool_executions`` row the chain joins on is
the row the production write path itself INSERTs — the vendor call is the
only thing replaced, by a closure bound to ``ToolExecutor.execute``'s real
signature.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from juli_backend.core.config.runtime import async_database_url
from juli_backend.services.agent.status import StopReason
from juli_backend.services.impact.windows import post_window
from juli_backend.services.operations.impact_honesty import COUNTABLE_CONFIDENCES
from juli_backend.services.operations.outcome_chain import (
    EmptyLink,
    LinkReason,
    OutcomeChain,
    RunNotFoundError,
    load_outcome_chain,
)
from tests.support.outcome_chain import (
    backdate_execution,
    create_disposable_database_at_head,
    execution_id_for,
    run_a_real_decline,
    run_a_real_write,
    seed_action_card,
    seed_outcome_record,
    seed_reading,
    seed_run,
    seed_shop_and_product,
)
from tests.support.postgres import requires_postgres

pytestmark = [pytest.mark.asyncio, requires_postgres]


@pytest.fixture(scope="module")
def disposable_postgres_url() -> Iterator[str]:
    yield from create_disposable_database_at_head("juli_outcome_chain")


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


# --------------------------------------------------------------------------
# The vocabulary itself
# --------------------------------------------------------------------------


class TestLinkReasonVocabulary:
    async def test_pending_unavailable_and_missing_are_three_distinct_non_null_values(self):
        """AC3: the acceptance criterion is about the vocabulary, so it is
        asserted on the vocabulary — pairwise unequal, none of them ``None``."""
        pending = LinkReason.PENDING
        unavailable = LinkReason.UNAVAILABLE
        missing = LinkReason.MISSING

        assert pending is not None
        assert unavailable is not None
        assert missing is not None
        assert pending != unavailable
        assert unavailable != missing
        assert pending != missing
        assert {pending.value, unavailable.value, missing.value} == {
            "pending",
            "unavailable",
            "missing",
        }

    async def test_the_vocabulary_has_exactly_three_members(self):
        """No fourth reason, and no alias for an existing one."""
        assert len(list(LinkReason)) == 3


# --------------------------------------------------------------------------
# The chain itself, from a real run
# --------------------------------------------------------------------------


class TestFiveLinksFromARealRun:
    async def test_a_run_seeded_through_the_real_runner_returns_exactly_five_links(
        self, session_factory, sync_session
    ):
        """AC1: exactly five links, each populated or carrying an explicit
        reason — never a bare ``null``."""
        factory = session_factory
        shop_id, product_id, tiktok_product_id = await seed_shop_and_product(factory)
        card_id = await seed_action_card(factory, shop_id)
        run_id = await seed_run(factory, shop_id, product_id, action_card_id=card_id)
        await run_a_real_write(
            factory,
            sync_session,
            run_id=run_id,
            shop_id=shop_id,
            tiktok_product_id=tiktok_product_id,
        )

        async with factory() as session:
            chain = await load_outcome_chain(session, run_id)

        assert isinstance(chain, OutcomeChain)
        assert len(chain.links) == 5
        for name, link in chain.links:
            assert link is not None, f"link {name!r} is a bare null"
            if isinstance(link, EmptyLink):
                assert link.reason in tuple(LinkReason)
                assert link.because.strip(), f"link {name!r} is empty with no explanation"

    async def test_a_completed_write_with_every_downstream_fact_populates_all_five(
        self, session_factory, sync_session
    ):
        """AC2: proves the joins actually traverse ``workflow_runs.action_card_id``,
        ``tool_executions.workflow_run_id``, ``workflow_outcome_records.execution_id``
        and ``impact_readings.run_id``/``tool_execution_id``."""
        factory = session_factory
        shop_id, product_id, tiktok_product_id = await seed_shop_and_product(factory)
        card_id = await seed_action_card(factory, shop_id)
        run_id = await seed_run(factory, shop_id, product_id, action_card_id=card_id)
        await run_a_real_write(
            factory,
            sync_session,
            run_id=run_id,
            shop_id=shop_id,
            tiktok_product_id=tiktok_product_id,
        )
        execution_id = await execution_id_for(factory, run_id)
        await seed_outcome_record(factory, shop_id=shop_id, execution_id=execution_id)
        await seed_reading(factory, run_id=run_id, execution_id=execution_id)

        async with factory() as session:
            chain = await load_outcome_chain(session, run_id)

        for name, link in chain.links:
            assert not isinstance(link, EmptyLink), f"link {name!r} is empty: {link}"

        assert chain.recommendation.action_card_id == card_id
        assert chain.recommendation.title == "Giảm giá sản phẩm"
        assert [e.tool_execution_id for e in chain.action.executions] == [execution_id]
        assert chain.action.executions[0].operation == "update_product_listing"
        assert [r.execution_id for r in chain.state_change.records] == [execution_id]
        assert chain.observed_outcome.observations[0].post == Decimal("120.00")
        assert chain.incremental_impact.readings[0].incremental == Decimal("20.00")
        assert chain.incremental_impact.readings[0].confidence in COUNTABLE_CONFIDENCES

    async def test_the_chain_is_one_database_call(self, session_factory, sync_session):
        """AC5: asserted by counting statements against the session, not by
        reading the source. Four fetches joined in Python fails this."""
        factory = session_factory
        shop_id, product_id, tiktok_product_id = await seed_shop_and_product(factory)
        card_id = await seed_action_card(factory, shop_id)
        run_id = await seed_run(factory, shop_id, product_id, action_card_id=card_id)
        await run_a_real_write(
            factory,
            sync_session,
            run_id=run_id,
            shop_id=shop_id,
            tiktok_product_id=tiktok_product_id,
        )
        execution_id = await execution_id_for(factory, run_id)
        await seed_outcome_record(factory, shop_id=shop_id, execution_id=execution_id)
        await seed_reading(factory, run_id=run_id, execution_id=execution_id)

        statements: list[str] = []

        async with factory() as session:
            # `AsyncSession.get_bind()` already hands back the underlying
            # SYNC `Engine`, which is where SQLAlchemy's cursor events fire.
            sync_engine = session.get_bind()

            def _record(conn, cursor, statement, parameters, context, executemany):
                statements.append(statement)

            event.listen(sync_engine, "before_cursor_execute", _record)
            try:
                # Warm the connection so pool/dialect setup is not counted.
                await session.execute(text("SELECT 1"))
                statements.clear()
                chain = await load_outcome_chain(session, run_id)
            finally:
                event.remove(sync_engine, "before_cursor_execute", _record)

        assert len(statements) == 1, (
            "the chain must be ONE database call; observed "
            f"{len(statements)}:\n" + "\n---\n".join(statements)
        )
        for _, link in chain.links:
            assert not isinstance(link, EmptyLink)


class TestDeclinedRunIsUnavailableNotPending:
    async def test_a_declined_run_reports_unavailable_for_state_change_and_impact(
        self, session_factory
    ):
        """AC (declined): declining is a choice, not a delay — the exact value
        is asserted, not merely 'not populated'."""
        factory = session_factory
        shop_id, product_id, tiktok_product_id = await seed_shop_and_product(factory)
        card_id = await seed_action_card(factory, shop_id)
        run_id = await seed_run(factory, shop_id, product_id, action_card_id=card_id)
        await run_a_real_decline(factory, run_id=run_id, tiktok_product_id=tiktok_product_id)

        async with factory() as session:
            chain = await load_outcome_chain(session, run_id)

        assert isinstance(chain.state_change, EmptyLink)
        assert chain.state_change.reason == LinkReason.UNAVAILABLE
        assert chain.state_change.reason != LinkReason.PENDING
        assert isinstance(chain.incremental_impact, EmptyLink)
        assert chain.incremental_impact.reason == LinkReason.UNAVAILABLE
        assert chain.incremental_impact.reason != LinkReason.PENDING
        assert StopReason.CONFIRMATION_DECLINED.value in chain.incremental_impact.because


class TestPendingIsDerivedFromTheClock:
    async def test_a_run_whose_t_plus_seven_window_has_not_elapsed_is_pending(
        self, session_factory, sync_session
    ):
        """AC4: derived from the clock (the seeded window boundary), not from
        row absence alone."""
        factory = session_factory
        shop_id, product_id, tiktok_product_id = await seed_shop_and_product(factory)
        card_id = await seed_action_card(factory, shop_id)
        run_id = await seed_run(factory, shop_id, product_id, action_card_id=card_id)
        await run_a_real_write(
            factory,
            sync_session,
            run_id=run_id,
            shop_id=shop_id,
            tiktok_product_id=tiktok_product_id,
        )
        execution_id = await execution_id_for(factory, run_id)
        await seed_outcome_record(factory, shop_id=shop_id, execution_id=execution_id)
        await backdate_execution(factory, execution_id, days_ago=2)

        async with factory() as session:
            chain = await load_outcome_chain(session, run_id)

        assert isinstance(chain.incremental_impact, EmptyLink)
        assert chain.incremental_impact.reason == LinkReason.PENDING

    async def test_the_same_row_absence_reads_missing_once_the_window_has_elapsed(
        self, session_factory, sync_session
    ):
        """The companion half of AC4: identical row absence, a different
        answer — so the value provably comes from the clock."""
        factory = session_factory
        shop_id, product_id, tiktok_product_id = await seed_shop_and_product(factory)
        card_id = await seed_action_card(factory, shop_id)
        run_id = await seed_run(factory, shop_id, product_id, action_card_id=card_id)
        await run_a_real_write(
            factory,
            sync_session,
            run_id=run_id,
            shop_id=shop_id,
            tiktok_product_id=tiktok_product_id,
        )
        execution_id = await execution_id_for(factory, run_id)
        await seed_outcome_record(factory, shop_id=shop_id, execution_id=execution_id)
        await backdate_execution(factory, execution_id, days_ago=30)

        async with factory() as session:
            chain = await load_outcome_chain(session, run_id)

        assert isinstance(chain.incremental_impact, EmptyLink)
        assert chain.incremental_impact.reason == LinkReason.MISSING

    async def test_the_boundary_is_the_post_window_end_the_impact_package_defines(
        self, session_factory, sync_session
    ):
        """The T+7 boundary is ``services/impact/windows.post_window``'s own,
        never a threshold re-declared here."""
        factory = session_factory
        shop_id, product_id, tiktok_product_id = await seed_shop_and_product(factory)
        card_id = await seed_action_card(factory, shop_id)
        run_id = await seed_run(factory, shop_id, product_id, action_card_id=card_id)
        await run_a_real_write(
            factory,
            sync_session,
            run_id=run_id,
            shop_id=shop_id,
            tiktok_product_id=tiktok_product_id,
        )
        execution_id = await execution_id_for(factory, run_id)
        await seed_outcome_record(factory, shop_id=shop_id, execution_id=execution_id)

        t = (datetime.now(UTC) - timedelta(days=9)).date()
        await backdate_execution(factory, execution_id, days_ago=9)
        _, window_end = post_window(t, "preliminary")

        async with factory() as session:
            on_the_last_pending_day = await load_outcome_chain(
                session,
                run_id,
                now=datetime.combine(window_end, datetime.min.time(), tzinfo=UTC),
            )
            one_day_later = await load_outcome_chain(
                session,
                run_id,
                now=datetime.combine(
                    window_end + timedelta(days=1), datetime.min.time(), tzinfo=UTC
                ),
            )

        assert isinstance(on_the_last_pending_day.incremental_impact, EmptyLink)
        assert on_the_last_pending_day.incremental_impact.reason == LinkReason.PENDING
        assert isinstance(one_day_later.incremental_impact, EmptyLink)
        assert one_day_later.incremental_impact.reason == LinkReason.MISSING


class TestMissingMeansShouldExistAndDoesNot:
    async def test_a_completed_write_with_no_outcome_record_reports_missing(
        self, session_factory, sync_session
    ):
        """AC6: distinguishes 'nobody wrote the join' from 'the fact has not
        happened yet'."""
        factory = session_factory
        shop_id, product_id, tiktok_product_id = await seed_shop_and_product(factory)
        card_id = await seed_action_card(factory, shop_id)
        run_id = await seed_run(factory, shop_id, product_id, action_card_id=card_id)
        await run_a_real_write(
            factory,
            sync_session,
            run_id=run_id,
            shop_id=shop_id,
            tiktok_product_id=tiktok_product_id,
        )

        async with factory() as session:
            chain = await load_outcome_chain(session, run_id)

        assert not isinstance(chain.action, EmptyLink)
        assert isinstance(chain.state_change, EmptyLink)
        assert chain.state_change.reason == LinkReason.MISSING
        assert chain.state_change.reason != LinkReason.PENDING
        assert chain.state_change.reason != LinkReason.UNAVAILABLE


class TestSuppressedAndConfoundedAreNeverIncrementalImpact:
    async def test_only_suppressed_rows_yield_zero_countable_readings(
        self, session_factory, sync_session
    ):
        """#1226 / #1338: with ONLY suppressed rows present the countable
        result is zero rows, and the link reports its own labelled outcome."""
        factory = session_factory
        shop_id, product_id, tiktok_product_id = await seed_shop_and_product(factory)
        card_id = await seed_action_card(factory, shop_id)
        run_id = await seed_run(factory, shop_id, product_id, action_card_id=card_id)
        await run_a_real_write(
            factory,
            sync_session,
            run_id=run_id,
            shop_id=shop_id,
            tiktok_product_id=tiktok_product_id,
        )
        execution_id = await execution_id_for(factory, run_id)
        await seed_outcome_record(factory, shop_id=shop_id, execution_id=execution_id)
        await seed_reading(
            factory,
            run_id=run_id,
            execution_id=execution_id,
            confidence="suppressed",
            incremental=None,
        )

        async with factory() as session:
            chain = await load_outcome_chain(session, run_id)

        assert isinstance(chain.incremental_impact, EmptyLink)
        assert chain.countable_readings == ()
        labels = [r.confidence for r in chain.incremental_impact.excluded_readings]
        assert labels == ["suppressed"]
        assert "suppressed" in chain.incremental_impact.because
        # never rendered as zero impact
        assert "0" not in {r.confidence for r in chain.incremental_impact.excluded_readings}

    async def test_confounded_is_excluded_and_stays_distinguishable_from_suppressed(
        self, session_factory, sync_session
    ):
        """Two seeded rows, two distinct labels, neither collapsed into the
        other and neither rendered as zero impact."""
        factory = session_factory
        shop_id, product_id, tiktok_product_id = await seed_shop_and_product(factory)
        card_id = await seed_action_card(factory, shop_id)
        run_id = await seed_run(factory, shop_id, product_id, action_card_id=card_id)
        await run_a_real_write(
            factory,
            sync_session,
            run_id=run_id,
            shop_id=shop_id,
            tiktok_product_id=tiktok_product_id,
        )
        execution_id = await execution_id_for(factory, run_id)
        await seed_outcome_record(factory, shop_id=shop_id, execution_id=execution_id)
        await seed_reading(
            factory,
            run_id=run_id,
            execution_id=execution_id,
            metric="gmv",
            confidence="suppressed",
            incremental=None,
        )
        await seed_reading(
            factory,
            run_id=run_id,
            execution_id=execution_id,
            metric="sku_orders",
            confidence="confounded",
            incremental=None,
        )

        async with factory() as session:
            chain = await load_outcome_chain(session, run_id)

        assert isinstance(chain.incremental_impact, EmptyLink)
        assert chain.countable_readings == ()
        by_metric = {r.metric: r.confidence for r in chain.incremental_impact.excluded_readings}
        assert by_metric == {"gmv": "suppressed", "sku_orders": "confounded"}
        assert "suppressed" in chain.incremental_impact.because
        assert "confounded" in chain.incremental_impact.because


class TestLegacyRunWithNoActionCard:
    async def test_action_card_id_null_reports_unavailable_never_missing(
        self, session_factory, sync_session
    ):
        """A row created before migration 040, deliberately never backfilled:
        honest data the chain reports as ``unavailable``, never ``missing``,
        and never a crash on the outer join."""
        factory = session_factory
        shop_id, product_id, tiktok_product_id = await seed_shop_and_product(factory)
        run_id = await seed_run(factory, shop_id, product_id, action_card_id=None)
        await run_a_real_write(
            factory,
            sync_session,
            run_id=run_id,
            shop_id=shop_id,
            tiktok_product_id=tiktok_product_id,
        )

        async with factory() as session:
            chain = await load_outcome_chain(session, run_id)

        assert isinstance(chain.recommendation, EmptyLink)
        assert chain.recommendation.reason == LinkReason.UNAVAILABLE
        assert chain.recommendation.reason != LinkReason.MISSING
        assert "action_card_id" in chain.recommendation.because
        # the outer join still yields the rest of the chain
        assert not isinstance(chain.action, EmptyLink)


class TestUnknownRun:
    async def test_an_unknown_run_id_raises_a_typed_error(self, session_factory):
        async with session_factory() as session:
            with pytest.raises(RunNotFoundError):
                await load_outcome_chain(session, uuid.uuid4())
