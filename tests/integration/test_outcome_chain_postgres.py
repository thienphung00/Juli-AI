"""The operator journey for the five-link outcome chain — issue #1655
(W8-C / P10-3), release evidence plan
``outcome-chain-five-links-empty-says-why-2026-09-07``.

``tests/unit/test_outcome_chain_query.py`` proves each reason rule in
isolation. This module proves the journey an operator actually walks on the
candidate: take a completed sandbox run, ask for its chain, and read five
links where every empty one says why — including the honest ``pending`` at
the incremental-impact link, because no real reading exists yet (#1339's gate
is an owner act, not a defect of this query). That honest ``pending`` IS the
deliverable, and the plan says so in as many words, so it is asserted here
rather than papered over.

Same harness as the unit suite (``tests/support/outcome_chain.py``): a
throwaway Postgres database migrated by the real Alembic chain, and a run
driven through the REAL ``WorkflowRunner`` and the REAL
``ToolExecutionLedger``. Never SQLite.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from juli_backend.core.config.runtime import async_database_url
from juli_backend.services.operations.outcome_chain import (
    EmptyLink,
    LinkReason,
    load_outcome_chain,
)
from tests.support.outcome_chain import (
    create_disposable_database_at_head,
    execution_id_for,
    run_a_real_write,
    seed_action_card,
    seed_outcome_record,
    seed_run,
    seed_shop_and_product,
)
from tests.support.postgres import requires_postgres

pytestmark = [pytest.mark.asyncio, requires_postgres]


@pytest.fixture(scope="module")
def disposable_postgres_url() -> Iterator[str]:
    yield from create_disposable_database_at_head("juli_outcome_chain_it")


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


class TestOperatorReadsACompletedRunsChain:
    async def test_a_completed_run_reads_five_links_with_an_honest_pending_impact(
        self, session_factory, sync_session
    ):
        """The candidate journey: four links populated from the run's own
        rows, and the fifth honestly ``pending`` because no reading exists
        yet — never a bare null, and never a fabricated zero."""
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

        async with factory() as session:
            chain = await load_outcome_chain(session, run_id)

        names = [name for name, _ in chain.links]
        assert names == [
            "recommendation",
            "action",
            "state_change",
            "observed_outcome",
            "incremental_impact",
        ]

        assert not isinstance(chain.recommendation, EmptyLink)
        assert not isinstance(chain.action, EmptyLink)
        assert not isinstance(chain.state_change, EmptyLink)

        for name, link in chain.links:
            assert link is not None, f"link {name!r} is a bare null"

        assert isinstance(chain.observed_outcome, EmptyLink)
        assert chain.observed_outcome.reason == LinkReason.PENDING
        assert isinstance(chain.incremental_impact, EmptyLink)
        assert chain.incremental_impact.reason == LinkReason.PENDING
        assert chain.incremental_impact.because.strip()
        # The honest pending is not a zero: nothing on this link claims a value.
        assert chain.countable_readings == ()
        assert chain.incremental_impact.excluded_readings == ()
