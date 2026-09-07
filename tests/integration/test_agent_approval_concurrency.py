"""Concurrency + atomicity proof for `services/agent/approval.py`
(ADR-075 decision 1, ADR-082, #1222) against a REAL Postgres instance.

Two things `tests/unit/test_agent_approval_transaction.py` (SQLite) cannot
prove:

1. **The race.** SQLite in this suite is a single in-process connection per
   test, so two "concurrent" callers sharing it can never genuinely
   interleave -- everything is serialized by the Python GIL and a single
   DB-API connection regardless of `asyncio.gather`. Only two independent
   Postgres connections (`NullPool`, one per caller, mirroring
   `test_credential_refresh_concurrency.py`'s own fixture) exercise real
   cross-connection row-level lock contention.
2. **The rollback.** Proving atomicity by reading the code is not proving
   it (per the issue brief's own instruction: "force a failure ... and
   assert both rolled back -- do not read the code and conclude it"). This
   file forces a real `ROLLBACK` on a real Postgres connection, after a real
   `UPDATE` has already been sent (via SQLAlchemy's autoflush -- see
   `approval.py`'s own docstring), and re-reads from a SEPARATE fresh
   connection to prove the write is genuinely gone, not just "never
   committed from this test's point of view".

Skips loudly (never silently) when `DATABASE_URL` is not a reachable
Postgres instance, matching `tests/integration/test_migrations.py`'s and
`tests/integration/test_credential_refresh_concurrency.py`'s existing
convention -- a skip reported as a pass is exactly the failure mode this
issue's own instructions call out ("a Postgres-gated test that skips
locally reads exactly like a pass").
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from juli_backend.core.config.runtime import async_database_url, sync_database_url
from juli_backend.models.models import ActionCard, ActionCardApproval, Product, Shop, User
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.services.agent import approval as approval_module

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ALEMBIC_INI = os.path.join(REPO_ROOT, "alembic.ini")


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def _postgres_reachable() -> bool:
    url = _database_url()
    if not url.startswith("postgresql"):
        return False
    try:
        engine = create_engine(
            sync_database_url(url),
            pool_pre_ping=True,
            connect_args={"connect_timeout": 3},
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


requires_postgres = pytest.mark.skipif(
    not _postgres_reachable(),
    reason=(
        "agent approval concurrency/atomicity tests require a reachable Postgres "
        "DATABASE_URL (real cross-connection locking and a real ROLLBACK cannot be "
        "exercised on SQLite) -- set DATABASE_URL to a disposable Postgres instance"
    ),
)

pytestmark = [pytest.mark.asyncio, requires_postgres]


def _naive_utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@pytest.fixture(scope="module", autouse=True)
def _migrated_schema():
    """Real Alembic migrations to head, not `Base.metadata.create_all` --
    the partial unique index's `postgresql_where` predicate and the
    `action_cards` / `action_card_approvals` / `workflow_runs.action_card_id`
    columns need to exist exactly as production will see them."""
    cfg = Config(ALEMBIC_INI)
    cfg.set_main_option(
        "script_location",
        os.path.join(REPO_ROOT, "backend/src/juli_backend/database/migrations"),
    )
    command.upgrade(cfg, "head")
    yield


@pytest_asyncio.fixture
async def async_engine_factory():
    """Fresh engine/sessionmaker per call, `NullPool` -- each concurrent
    caller below gets its own physical Postgres backend connection, exactly
    like separate worker/API processes would (mirrors
    `test_credential_refresh_concurrency.py`'s identical fixture)."""
    engines = []

    def _make():
        engine = create_async_engine(async_database_url(_database_url()), poolclass=NullPool)
        engines.append(engine)
        return async_sessionmaker(engine, expire_on_commit=False)

    yield _make

    for engine in engines:
        await engine.dispose()


async def _seed_shop_card_and_one_product(
    factory,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Deliberately exactly ONE product for the shop -- both concurrent
    callers below MUST derive the same `product_id`, so the partial unique
    index (not incidental revenue-tiebreak divergence) is what forces
    "exactly one run". Returns `(shop_id, card_id, product_id, user_id)` --
    Postgres enforces `action_card_approvals.approved_by_user_id`'s FK for
    real (SQLite in the unit suite does not by default), so every caller
    below must approve as this real seeded user, never a bare `uuid.uuid4()`.
    """
    async with factory() as session:
        user = User(id=uuid.uuid4(), phone=f"+8491{uuid.uuid4().int % 10_000_000:07d}")
        session.add(user)
        await session.flush()
        shop = Shop(id=uuid.uuid4(), user_id=user.id, shop_name="AGT-1222 Concurrency Shop")
        session.add(shop)
        await session.flush()
        product = Product(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id=f"agt-1222-concurrency-{uuid.uuid4().hex[:10]}",
            name="Concurrency Test Product",
            status="active",
            revenue=Decimal("500.00"),
            update_time=_naive_utc_now(),
        )
        session.add(product)
        await session.flush()
        card = ActionCard(
            id=uuid.uuid4(),
            shop_id=shop.id,
            workflow_key="optimize_product_2",
            priority=1,
            severity="high",
            title="Concurrency test card",
            description="Real-Postgres approval race/atomicity fixture.",
            recommendation_payload=json.dumps({}),
            status="active",
            computed_at=_naive_utc_now(),
        )
        session.add(card)
        await session.flush()
        await session.commit()
        return shop.id, card.id, product.id, user.id


class TestTwoConcurrentApprovalsOfTheSameCard:
    async def test_exactly_one_run_and_one_approval_row_survive(self, async_engine_factory):
        factory = async_engine_factory()
        shop_id, card_id, product_id, user_id = await _seed_shop_card_and_one_product(factory)

        async def _one_caller():
            async with factory() as session:
                try:
                    result = await approval_module.approve_action_card(
                        session,
                        shop_id=shop_id,
                        action_card_id=card_id,
                        approved_by_user_id=user_id,
                    )
                    await session.commit()
                    return ("ok", result)
                except Exception as exc:  # noqa: BLE001 -- classifying the outcome, not swallowing it
                    await session.rollback()
                    return ("error", exc)

        async def _second_caller_delayed():
            # A small stagger so the two callers reliably overlap (the
            # second arrives while the first is mid-transaction) rather
            # than one finishing before the other even starts -- the same
            # technique `test_credential_refresh_concurrency.py` uses.
            await asyncio.sleep(0.05)
            return await _one_caller()

        outcome_a, outcome_b = await asyncio.gather(_one_caller(), _second_caller_delayed())
        outcomes = [outcome_a, outcome_b]

        oks = [o for o in outcomes if o[0] == "ok"]
        errors = [o for o in outcomes if o[0] == "error"]

        assert len(oks) == 1, f"expected exactly one winner, got: {outcomes}"
        assert len(errors) == 1, f"expected exactly one loser, got: {outcomes}"
        # The loser can legitimately fail either of two ways, and which one
        # depends on real timing this test cannot pin down further (both
        # observed across repeated real-Postgres runs of this exact test):
        #
        # - IntegrityError (uq_workflow_runs_active_shop_product): both
        #   callers' SELECTs for the card land while it still reads
        #   "active" (genuinely simultaneous), both proceed through the
        #   flip and product derivation, and the second caller's run INSERT
        #   is the one the partial unique index rejects.
        # - ActionCardNotActive: the loser's own SELECT for the card lands
        #   AFTER the winner has already committed the flip to "approved"
        #   -- caught at the earliest possible point, before ever reaching
        #   the run insert.
        #
        # ADR-075 decision 1 names both explicitly as correct: "Double-
        # approve hits the non-active status and 409s -- raced or
        # sequential, exactly one run can exist." Asserting only
        # IntegrityError here would make this test flaky against a real,
        # correctly-behaving implementation -- it failed on exactly that
        # over-strict assertion during review before this comment was
        # written.
        assert isinstance(errors[0][1], (IntegrityError, approval_module.ActionCardNotActive)), (
            "the loser must fail on either the partial unique index or the non-active "
            f"status check, not some other error: {errors[0][1]!r}"
        )

        async with factory() as session:
            runs = (
                (
                    await session.execute(
                        select(WorkflowRunRow).where(WorkflowRunRow.action_card_id == card_id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(runs) == 1
            assert runs[0].product_id == product_id
            assert runs[0].shop_id == shop_id

            approvals = (
                (
                    await session.execute(
                        select(ActionCardApproval).where(
                            ActionCardApproval.action_card_id == card_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(approvals) == 1, (
                "the loser's transaction must roll back its OWN approval-audit insert "
                f"too, not just the run: {approvals}"
            )

            card = await session.get(ActionCard, card_id)
            assert card.status == "approved"


class TestAtomicityAcrossARealRollback:
    async def test_a_crash_between_the_flip_and_the_run_insert_rolls_back_both(
        self, async_engine_factory
    ):
        """Forces a real failure between step 2 (flip) and step 4 (run
        insert) by patching the prompt-pin resolver (called strictly after
        the flip and the product derivation, strictly before the
        `WorkflowRun`/`ActionCardApproval` objects are even constructed) to
        raise. By the time it raises, the `card.status = "approved"` UPDATE
        has already been sent to Postgres via autoflush (triggered by the
        product-selection SELECT) -- so this is a genuine ROLLBACK of an
        already-flushed write, not merely "the Python object was never
        persisted"."""
        factory = async_engine_factory()
        shop_id, card_id, product_id, user_id = await _seed_shop_card_and_one_product(factory)

        async with factory() as session:
            with patch.object(
                approval_module,
                # Renamed from _resolve_optimize_product_prompt_pin by #1309:
                # the pin now resolves from the card's own workflow_key via the
                # registry instead of hardwiring Optimize Product. Still the
                # same crash seam — it runs after the card flip and before the
                # run insert.
                "_resolve_prompt_pin",
                side_effect=RuntimeError("simulated crash between flip and run insert"),
            ):
                with pytest.raises(RuntimeError):
                    await approval_module.approve_action_card(
                        session,
                        shop_id=shop_id,
                        action_card_id=card_id,
                        approved_by_user_id=user_id,
                    )
            await session.rollback()

        # Fresh connection -- proves the rollback is visible to an entirely
        # separate reader, not an artifact of the same session's own cache.
        async with factory() as reader:
            card = await reader.get(ActionCard, card_id)
            assert card.status == "active", (
                "the card must not be left approved with no run -- ROLLBACK must have "
                f"undone the already-flushed UPDATE, but status is {card.status!r}"
            )
            assert card.approved_at is None

            runs = (
                (
                    await reader.execute(
                        select(WorkflowRunRow).where(WorkflowRunRow.action_card_id == card_id)
                    )
                )
                .scalars()
                .all()
            )
            assert runs == []

            approvals = (
                (
                    await reader.execute(
                        select(ActionCardApproval).where(
                            ActionCardApproval.action_card_id == card_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert approvals == []

    async def test_a_successful_approval_still_commits_normally_after_the_same_seam(
        self, async_engine_factory
    ):
        """Sanity control for the test above: the SAME seam, unpatched, on
        a fresh card/product pair, must still commit successfully -- proves
        the induced-failure test isn't passing because the transaction is
        broken in general."""
        factory = async_engine_factory()
        shop_id, card_id, product_id, user_id = await _seed_shop_card_and_one_product(factory)

        async with factory() as session:
            result = await approval_module.approve_action_card(
                session,
                shop_id=shop_id,
                action_card_id=card_id,
                approved_by_user_id=user_id,
            )
            await session.commit()

        async with factory() as reader:
            card = await reader.get(ActionCard, card_id)
            assert card.status == "approved"

            run = await reader.get(WorkflowRunRow, result.run_id)
            assert run is not None
            assert run.product_id == product_id
            assert run.action_card_id == card_id
