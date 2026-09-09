"""Business impact — the fourth unconflated metric, honest when there is no
reading (issue #1657 / W8-E / P10-5, parent PRD #1652, ADR-077).

"Did the action actually improve the metric?" is answered from #1655's outcome
chain over ``impact_readings``. The load-bearing surface is NOT the number: it
is what comes back when nothing has been measured. ``0`` is a claim about the
world; "no readings" is a statement about our knowledge of it, and #1226 is
the named incident where those two were conflated.

So every assertion here is about a distinction:

- "we measured nothing" is NOT EQUAL to "we measured no change";
- the no-readings value does not compare equal to ``0`` in Python;
- a ``suppressed`` row is not a reading, a ``confounded`` row is not a
  reading, and the two are not each other;
- a delta never travels without its ``n``;
- ``preliminary`` and ``final`` never both count for one metric, because
  ``uq_impact_readings_execution_metric_kind`` permits both to exist.

**Real Postgres, never SQLite** — for the same reason ``#1655``'s suite gives:
the honesty rule turns on what an aggregate over zero qualifying rows actually
returns (NULL, not 0) and on the ``Numeric`` scales readings are stored at.
The disposable-database + real-``WorkflowRunner`` harness is
``tests/support/outcome_chain.py``, shared so this suite and #1655's cannot
drift into proving different things.
"""

from __future__ import annotations

import ast
import inspect
import uuid
from collections.abc import Iterator
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from juli_backend.core.config.runtime import async_database_url
from juli_backend.services.impact.confidence import (
    BAND_MULTIPLIER_CAO,
    BAND_MULTIPLIER_TRUNG_BINH,
    FLOOR_MULTIPLIER_CAO,
    VOLUME_FLOORS,
)
from juli_backend.services.impact.control_pool import (
    MIN_ACTIVE_DAYS,
    MIN_CANDIDATES,
    MIN_MEAN_CORRELATION,
    TOP_K,
)
from juli_backend.services.operations import business_impact as business_impact_module
from juli_backend.services.operations.business_impact import (
    BusinessImpact,
    NoReadings,
    business_impact,
)
from juli_backend.services.operations.impact_honesty import (
    COUNTABLE_CONFIDENCES,
    EXCLUDED_CONFIDENCES,
    list_impact_readings_honest,
)
from juli_backend.services.operations.outcome_chain import load_outcome_chain
from tests.support.outcome_chain import (
    create_disposable_database_at_head,
    execution_id_for,
    run_a_real_write,
    seed_action_card,
    seed_reading,
    seed_run,
    seed_shop_and_product,
)
from tests.support.postgres import requires_postgres

# `asyncio_mode = auto` (pytest.ini) runs the async tests; the structural tests
# in this module are deliberately synchronous, so no asyncio marker is applied.
pytestmark = [requires_postgres]


@pytest.fixture(scope="module")
def disposable_postgres_url() -> Iterator[str]:
    yield from create_disposable_database_at_head("juli_business_impact")


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


async def _seed_run_with_a_real_write(factory, sync_session) -> tuple[uuid.UUID, uuid.UUID]:
    """A run driven through the REAL ``WorkflowRunner`` and the REAL
    ``ToolExecutionLedger``, returning ``(run_id, tool_execution_id)``.

    Hand-built rows would prove the SQL and not the wiring, and the wiring is
    what carries the honesty rule from the chain into this metric.
    """
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
    return run_id, execution_id


# --------------------------------------------------------------------------
# "We measured nothing" is not "we measured no change"
# --------------------------------------------------------------------------


class TestNoReadingsIsItsOwnState:
    async def test_zero_rows_is_not_equal_to_a_genuine_zero_delta(
        self, session_factory, sync_session
    ):
        """AC1. The INEQUALITY is the assertion: a shared sentinel between
        "nothing was measured" and "a measurement came back at zero" silently
        passes every other check in this file."""
        factory = session_factory

        empty_run, _ = await _seed_run_with_a_real_write(factory, sync_session)
        async with factory() as session:
            nothing_measured = await business_impact(session, empty_run)

        zero_run, zero_execution = await _seed_run_with_a_real_write(factory, sync_session)
        await seed_reading(
            factory,
            run_id=zero_run,
            execution_id=zero_execution,
            metric="gmv",
            confidence="cao",
            incremental=Decimal("0.00"),
        )
        async with factory() as session:
            measured_no_change = await business_impact(session, zero_run)

        assert isinstance(nothing_measured, NoReadings)
        assert isinstance(measured_no_change, BusinessImpact)
        assert measured_no_change.n == 1
        assert measured_no_change.metrics[0].delta == Decimal("0.00")

        assert nothing_measured != measured_no_change
        assert not nothing_measured == measured_no_change

    async def test_the_no_readings_state_is_not_a_zero_in_any_costume(
        self, session_factory, sync_session
    ):
        """AC1 / doNotInfer #1, asserted on the RETURNED VALUE itself: not
        ``0``, not ``0.0``, not ``Decimal(0)``, not ``None``, not ``'0%'`` and
        not the sentence 'no measurable impact'."""
        factory = session_factory
        run_id, _ = await _seed_run_with_a_real_write(factory, sync_session)

        async with factory() as session:
            state = await business_impact(session, run_id)

        assert isinstance(state, NoReadings)
        assert state is not None
        assert state != 0
        assert not state == 0
        assert state != 0.0
        assert not state == 0.0
        assert state != Decimal("0")
        assert state != Decimal("0.00")
        assert state != "0%"
        assert state != "no measurable impact"
        assert state != ""
        assert state != []
        assert bool(state) is True

    async def test_the_no_readings_state_still_says_why(self, session_factory, sync_session):
        """An honest absence is explained, not merely flagged: the reason
        vocabulary is #1655's ``LinkReason``, carried through unchanged."""
        factory = session_factory
        run_id, _ = await _seed_run_with_a_real_write(factory, sync_session)

        async with factory() as session:
            chain = await load_outcome_chain(session, run_id)
            state = await business_impact(session, run_id)

        assert isinstance(state, NoReadings)
        assert state.workflow_run_id == run_id
        assert state.reason == chain.incremental_impact.reason
        assert state.because.strip()
        assert state.excluded == ()


# --------------------------------------------------------------------------
# A suppressed reading is not a reading; nor is a confounded one; nor are
# they each other (#1226, #1338)
# --------------------------------------------------------------------------


class TestExcludedReadingsAreNotReadings:
    async def test_only_suppressed_rows_still_reports_no_readings(
        self, session_factory, sync_session
    ):
        """AC2. The gate-closing query returning ZERO rows is asserted
        DIRECTLY, because producing a suppressed reading and calling it a
        reading is the exact dishonesty #1226 names."""
        factory = session_factory
        run_id, execution_id = await _seed_run_with_a_real_write(factory, sync_session)
        for metric in ("gmv", "ctr"):
            await seed_reading(
                factory,
                run_id=run_id,
                execution_id=execution_id,
                metric=metric,
                confidence="suppressed",
            )

        async with factory() as session:
            state = await business_impact(session, run_id)
            chain = await load_outcome_chain(session, run_id)
            countable_rows = await list_impact_readings_honest(session, execution_id)

        assert isinstance(state, NoReadings)
        assert state != 0
        assert chain.countable_readings == ()
        assert countable_rows == []
        assert {r.confidence for r in state.excluded} == {"suppressed"}
        assert len(state.excluded) == 2

    async def test_only_confounded_rows_still_reports_no_readings(
        self, session_factory, sync_session
    ):
        """AC3. ``confounded`` is excluded for its own reason — a competing
        change — and is excluded just as hard as ``suppressed``."""
        factory = session_factory
        run_id, execution_id = await _seed_run_with_a_real_write(factory, sync_session)
        await seed_reading(
            factory,
            run_id=run_id,
            execution_id=execution_id,
            metric="gmv",
            confidence="confounded",
        )

        async with factory() as session:
            state = await business_impact(session, run_id)
            countable_rows = await list_impact_readings_honest(session, execution_id)

        assert isinstance(state, NoReadings)
        assert state != 0
        assert countable_rows == []
        assert [r.confidence for r in state.excluded] == ["confounded"]

    async def test_suppressed_and_confounded_surface_as_two_distinct_outcomes(
        self, session_factory, sync_session
    ):
        """AC3. Neither collapsed into the other, neither rendered as zero
        impact: each row keeps its OWN confidence value and its own metric."""
        factory = session_factory
        run_id, execution_id = await _seed_run_with_a_real_write(factory, sync_session)
        await seed_reading(
            factory,
            run_id=run_id,
            execution_id=execution_id,
            metric="gmv",
            confidence="suppressed",
        )
        await seed_reading(
            factory,
            run_id=run_id,
            execution_id=execution_id,
            metric="ctr",
            confidence="confounded",
        )

        async with factory() as session:
            state = await business_impact(session, run_id)

        assert isinstance(state, NoReadings)
        labelled = {r.metric: r.confidence for r in state.excluded}
        assert labelled == {"gmv": "suppressed", "ctr": "confounded"}
        assert len({r.confidence for r in state.excluded}) == 2
        for reading in state.excluded:
            assert reading.confidence in EXCLUDED_CONFIDENCES
            assert reading.confidence not in COUNTABLE_CONFIDENCES
            assert reading.confidence != Decimal("0")


# --------------------------------------------------------------------------
# A delta never travels without its n
# --------------------------------------------------------------------------


class TestDeltaAlwaysCarriesItsN:
    async def test_one_genuine_reading_reports_the_delta_with_n_equal_to_one(
        self, session_factory, sync_session
    ):
        """AC4. Both fields asserted, so one observation cannot read as a
        trend."""
        factory = session_factory
        run_id, execution_id = await _seed_run_with_a_real_write(factory, sync_session)
        await seed_reading(
            factory,
            run_id=run_id,
            execution_id=execution_id,
            metric="gmv",
            confidence="cao",
            incremental=Decimal("20.00"),
        )

        async with factory() as session:
            result = await business_impact(session, run_id)

        assert isinstance(result, BusinessImpact)
        assert result.n == 1
        assert len(result.metrics) == 1
        only = result.metrics[0]
        assert only.metric == "gmv"
        assert only.n == 1
        assert only.delta == Decimal("20.00")
        assert only.pct == Decimal("0.200000")
        assert only.confidences == ("cao",)
        assert result.delta_for("gmv") == Decimal("20.00")

    async def test_every_reported_metric_carries_a_positive_n(self, session_factory, sync_session):
        """doNotInfer #6: there is no shape of this result that holds a delta
        with no denominator."""
        factory = session_factory
        run_id, execution_id = await _seed_run_with_a_real_write(factory, sync_session)
        for metric in ("gmv", "ctr"):
            await seed_reading(
                factory,
                run_id=run_id,
                execution_id=execution_id,
                metric=metric,
                confidence="thap",
                incremental=Decimal("7.00"),
            )

        async with factory() as session:
            result = await business_impact(session, run_id)

        assert isinstance(result, BusinessImpact)
        assert result.n == 2
        assert [m.metric for m in result.metrics] == ["ctr", "gmv"]
        for metric_impact in result.metrics:
            assert metric_impact.n >= 1
            assert metric_impact.delta == Decimal("7.00")
        assert result.n == sum(m.n for m in result.metrics)


class TestMixedPopulationCountsOnlyCountableRows:
    async def test_n_counts_only_countable_rows_and_the_delta_is_over_exactly_those(
        self, session_factory, sync_session
    ):
        """AC5. The seeded set's "all rows" answer (three rows, 60.00) differs
        from its "countable rows" answer (one row, 20.00), so a query that
        forgot the exclusion cannot pass this test."""
        factory = session_factory
        run_id, execution_id = await _seed_run_with_a_real_write(factory, sync_session)
        await seed_reading(
            factory,
            run_id=run_id,
            execution_id=execution_id,
            metric="gmv",
            confidence="cao",
            incremental=Decimal("20.00"),
        )
        await seed_reading(
            factory,
            run_id=run_id,
            execution_id=execution_id,
            metric="ctr",
            confidence="suppressed",
            incremental=Decimal("20.00"),
        )
        await seed_reading(
            factory,
            run_id=run_id,
            execution_id=execution_id,
            metric="conversion_rate",
            confidence="confounded",
            incremental=Decimal("20.00"),
        )

        async with factory() as session:
            result = await business_impact(session, run_id)
            all_rows = await load_outcome_chain(session, run_id)

        assert isinstance(result, BusinessImpact)
        assert result.n == 1
        assert [m.metric for m in result.metrics] == ["gmv"]
        assert result.metrics[0].delta == Decimal("20.00")

        # The "all rows" answer this set was built to differ from.
        every_reading = all_rows.observed_outcome.observations
        assert len(every_reading) == 3
        assert result.n != len(every_reading)
        assert result.metrics[0].delta != Decimal("60.00")

        assert {r.confidence for r in result.excluded} == {"suppressed", "confounded"}
        assert len(result.excluded) == 2


# --------------------------------------------------------------------------
# preliminary vs final — the unique constraint permits both
# --------------------------------------------------------------------------


class TestKindIsChosenExplicitly:
    async def test_final_wins_over_preliminary_for_the_same_metric(
        self, session_factory, sync_session
    ):
        """AC6. ``uq_impact_readings_execution_metric_kind`` is
        ``(tool_execution_id, metric, kind)``, so BOTH kinds can exist for one
        execution and one metric. An unfiltered aggregate would count 20 + 35;
        the rule is final-when-present, and the chosen kind is asserted."""
        factory = session_factory
        run_id, execution_id = await _seed_run_with_a_real_write(factory, sync_session)
        await seed_reading(
            factory,
            run_id=run_id,
            execution_id=execution_id,
            metric="gmv",
            kind="preliminary",
            confidence="cao",
            incremental=Decimal("20.00"),
        )
        await seed_reading(
            factory,
            run_id=run_id,
            execution_id=execution_id,
            metric="gmv",
            kind="final",
            confidence="cao",
            incremental=Decimal("35.00"),
        )

        async with factory() as session:
            result = await business_impact(session, run_id)

        assert isinstance(result, BusinessImpact)
        assert result.n == 1, "both kinds counted — the same measurement twice"
        assert result.metrics[0].kind == "final"
        assert result.metrics[0].delta == Decimal("35.00")
        assert result.metrics[0].delta != Decimal("55.00")

    async def test_preliminary_is_counted_when_no_final_exists(self, session_factory, sync_session):
        """AC6, the other half: preferring ``final`` must not mean discarding
        the preliminary answer while it is the only one there is."""
        factory = session_factory
        run_id, execution_id = await _seed_run_with_a_real_write(factory, sync_session)
        await seed_reading(
            factory,
            run_id=run_id,
            execution_id=execution_id,
            metric="gmv",
            kind="preliminary",
            confidence="trung_binh",
            incremental=Decimal("11.00"),
        )

        async with factory() as session:
            result = await business_impact(session, run_id)

        assert isinstance(result, BusinessImpact)
        assert result.n == 1
        assert result.metrics[0].kind == "preliminary"
        assert result.metrics[0].delta == Decimal("11.00")


class TestACountableReadingWithNoIncrementalIsNotZero:
    async def test_a_null_incremental_is_never_coerced_to_a_zero_delta(
        self, session_factory, sync_session
    ):
        """``impact_readings.incremental`` is nullable and the chain types it
        ``Decimal | None``. A countable tier with no number is not a zero
        delta — that is doNotInfer #1's "``None``-coerced-to-zero" verbatim —
        so it is reported under its own name and never counted in ``n``."""
        factory = session_factory
        run_id, execution_id = await _seed_run_with_a_real_write(factory, sync_session)
        await seed_reading(
            factory,
            run_id=run_id,
            execution_id=execution_id,
            metric="gmv",
            confidence="cao",
            incremental=None,
        )

        async with factory() as session:
            state = await business_impact(session, run_id)

        assert isinstance(state, NoReadings)
        assert state != 0
        assert [r.metric for r in state.unmeasured] == ["gmv"]
        assert state.excluded == ()


# --------------------------------------------------------------------------
# Structure: one chain call, no second join, no copied threshold
# --------------------------------------------------------------------------


def _module_tree() -> ast.Module:
    source_path = inspect.getsourcefile(business_impact_module)
    assert source_path is not None
    with open(source_path, encoding="utf-8") as handle:
        return ast.parse(handle.read())


def _imported_modules(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _imported_names_from(tree: ast.Module, module: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            names.update(alias.name for alias in node.names)
    return names


def _called_names(tree: ast.Module) -> list[str]:
    called: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            called.append(func.id)
        elif isinstance(func, ast.Attribute):
            called.append(func.attr)
    return called


class TestTheChainIsConsumedNotRebuilt:
    def test_the_module_imports_no_sql_toolkit_and_no_model(self):
        """doNotInfer #8. A second client-side join across ``action_cards`` /
        ``tool_executions`` / ``workflow_outcome_records`` / ``impact_readings``
        reintroduces exactly what #1655 removed. Asserted structurally: this
        module cannot build a query, because it imports nothing that can.

        ``sqlalchemy.ext.asyncio`` is the one permitted exception and only for
        ``AsyncSession`` — the session it PASSES to the chain. That name binds
        no table and constructs no statement; ``sqlalchemy`` itself,
        ``sqlalchemy.orm`` and ``sqlalchemy.sql`` do, so they are refused."""
        tree = _module_tree()
        imported = _imported_modules(tree)

        forbidden_roots = ("sqlalchemy.orm", "sqlalchemy.sql", "sqlalchemy.dialects")
        assert "sqlalchemy" not in imported
        for name in sorted(imported):
            assert not name.startswith(forbidden_roots), f"{name} can build a second query"
        assert _imported_names_from(tree, "sqlalchemy.ext.asyncio") <= {"AsyncSession"}

        assert "juli_backend.models.models" not in imported
        assert not any(name.startswith("juli_backend.models") for name in imported)
        assert not any(name.startswith("juli_backend.repositories") for name in imported)
        assert not any(name.startswith("juli_backend.workers") for name in imported)

    def test_the_chain_is_reached_by_exactly_one_call(self):
        """AC7. ``load_outcome_chain`` appears once, and no ``select`` /
        ``execute`` call appears at all."""
        called = _called_names(_module_tree())

        assert called.count("load_outcome_chain") == 1
        assert "select" not in called
        assert "execute" not in called
        assert "scalars" not in called

    async def test_the_metric_costs_exactly_one_database_statement(
        self, session_factory, sync_session
    ):
        """AC7 at runtime, not only in the AST: counted against the session,
        so a helper that quietly re-reads ``impact_readings`` fails here."""
        factory = session_factory
        run_id, execution_id = await _seed_run_with_a_real_write(factory, sync_session)
        await seed_reading(
            factory,
            run_id=run_id,
            execution_id=execution_id,
            metric="gmv",
            confidence="cao",
            incremental=Decimal("20.00"),
        )

        statements: list[str] = []

        async with factory() as session:
            sync_engine = session.get_bind()

            def _record(conn, cursor, statement, parameters, context, executemany):
                statements.append(statement)

            event.listen(sync_engine, "before_cursor_execute", _record)
            try:
                await session.execute(text("SELECT 1"))
                statements.clear()
                result = await business_impact(session, run_id)
            finally:
                event.remove(sync_engine, "before_cursor_execute", _record)

        assert isinstance(result, BusinessImpact)
        assert len(statements) == 1, (
            "business impact must cost ONE database call; observed "
            f"{len(statements)}:\n" + "\n---\n".join(statements)
        )


class TestNoThresholdIsRedeclaredHere:
    def test_no_services_impact_threshold_appears_as_a_literal_in_this_module(self):
        """AC8 / doNotInfer #5. Every floor, tier multiplier and control-set
        minimum has exactly ONE declaration, in ``services/impact``. This walks
        the module's own AST for numeric literals and fails on any value those
        real symbols hold — #1062 is the HIGH-severity defect a duplicated
        floor already produced."""
        forbidden = {Decimal(value) for value in VOLUME_FLOORS.values()}
        forbidden |= {
            FLOOR_MULTIPLIER_CAO,
            BAND_MULTIPLIER_CAO,
            BAND_MULTIPLIER_TRUNG_BINH,
        }
        forbidden |= {
            Decimal(str(MIN_CANDIDATES)),
            Decimal(str(TOP_K)),
            Decimal(str(MIN_MEAN_CORRELATION)),
            Decimal(str(MIN_ACTIVE_DAYS)),
        }

        literals: list[object] = []
        for node in ast.walk(_module_tree()):
            if not isinstance(node, ast.Constant):
                continue
            if isinstance(node.value, bool) or not isinstance(node.value, int | float):
                continue
            literals.append(node.value)

        offenders = [value for value in literals if Decimal(str(value)) in forbidden]
        assert offenders == [], (
            "these numeric literals duplicate a services/impact threshold and must be "
            f"read through the real symbol instead: {sorted(set(map(str, offenders)))}"
        )

    def test_the_exclusion_rule_is_the_one_in_impact_honesty(self):
        """doNotInfer #3/#4: the countable/excluded partition is not
        re-declared here either. The module reads the same two tuples every
        other impact surface reads, and they are complementary over the
        ``ck_impact_readings_confidence`` vocabulary."""
        source_path = inspect.getsourcefile(business_impact_module)
        assert source_path is not None
        with open(source_path, encoding="utf-8") as handle:
            source = handle.read()

        for tier in COUNTABLE_CONFIDENCES + EXCLUDED_CONFIDENCES:
            assert f'"{tier}"' not in source, f"{tier!r} re-declared as a literal here"
        assert set(COUNTABLE_CONFIDENCES).isdisjoint(EXCLUDED_CONFIDENCES)
