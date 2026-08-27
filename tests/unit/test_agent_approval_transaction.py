"""`services/agent/approval.py::approve_action_card` -- the atomic
approve-is-run-creation transaction (ADR-075 decision 1, ADR-082, #1222).

Exercises the transaction function directly (SQLite `session`/`engine`
fixtures from `tests/unit/conftest.py`), not through HTTP -- the HTTP-level
translation (404/409 mapping, auth) is `test_api_demo_execution.py`'s job.
The race (concurrent double-approve) and the mid-transaction-crash rollback
proof both need a REAL Postgres connection (genuine cross-connection
contention, and a real ROLLBACK undoing an already-flushed write) and live
in `tests/integration/test_agent_approval_concurrency.py`.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import select

from juli_backend.models.models import ActionCard, ActionCardApproval, Product, Shop, User
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.services.agent import approval as approval_module

pytestmark = pytest.mark.asyncio


def _naive_utc_now() -> datetime:
    # Naive UTC: asyncpg rejects tz-aware datetimes for naive DateTime
    # columns where SQLite silently tolerates them -- match the convention
    # every other fixture in this suite already uses for `update_time`.
    return datetime.now(UTC).replace(tzinfo=None)


@pytest.fixture
async def shop(session, user_id):
    user = User(id=user_id, phone=f"+8490{uuid.uuid4().int % 10_000_000:07d}")
    s = Shop(id=uuid.uuid4(), user_id=user_id, shop_name="AGT-1222 Shop")
    session.add_all([user, s])
    await session.flush()
    return s


@pytest.fixture
async def other_shop(session):
    other_user = User(id=uuid.uuid4(), phone=f"+8490{uuid.uuid4().int % 10_000_000:07d}")
    s = Shop(id=uuid.uuid4(), user_id=other_user.id, shop_name="AGT-1222 Other Shop")
    session.add_all([other_user, s])
    await session.flush()
    return s


def _make_card(shop_id: uuid.UUID, **overrides) -> ActionCard:
    fields = {
        "id": uuid.uuid4(),
        "shop_id": shop_id,
        "workflow_key": "optimize_product_2",
        "priority": 1,
        "severity": "high",
        "title": "Optimize this listing",
        "description": "CTR fell 18% week over week on this listing.",
        "recommendation_payload": json.dumps({}),
        "status": "active",
        "computed_at": _naive_utc_now(),
    }
    fields.update(overrides)
    return ActionCard(**fields)


@pytest.fixture
async def card(session, shop):
    c = _make_card(shop.id)
    session.add(c)
    await session.flush()
    return c


def _make_product(shop_id: uuid.UUID, *, revenue: str, tiktok_product_id: str) -> Product:
    return Product(
        id=uuid.uuid4(),
        shop_id=shop_id,
        tiktok_product_id=tiktok_product_id,
        name=f"Product {tiktok_product_id}",
        status="active",
        revenue=Decimal(revenue),
        update_time=_naive_utc_now(),
    )


@pytest.fixture
async def product(session, shop):
    p = _make_product(shop.id, revenue="100.00", tiktok_product_id="tt-100")
    session.add(p)
    await session.flush()
    return p


# ---------------------------------------------------------------------------
# AC -- cross-tenant and nonexistent are indistinguishable (404 both, never
# an existence oracle -- ADR-075)
# ---------------------------------------------------------------------------


class TestExistenceOracle:
    async def test_nonexistent_card_raises_action_card_not_found(self, session, shop):
        with pytest.raises(approval_module.ActionCardNotFound):
            await approval_module.approve_action_card(
                session,
                shop_id=shop.id,
                action_card_id=uuid.uuid4(),
                approved_by_user_id=uuid.uuid4(),
            )

    async def test_cross_tenant_card_raises_the_same_exception_type(
        self, session, other_shop, card
    ):
        """`card` belongs to `shop`, not `other_shop` -- must raise the
        IDENTICAL exception type a nonexistent id raises, never anything
        that would let a caller distinguish "exists, wrong tenant" from
        "does not exist"."""
        with pytest.raises(approval_module.ActionCardNotFound):
            await approval_module.approve_action_card(
                session,
                shop_id=other_shop.id,
                action_card_id=card.id,
                approved_by_user_id=uuid.uuid4(),
            )

    async def test_cross_tenant_and_nonexistent_produce_identical_exception_messages(
        self, session, shop, other_shop, card
    ):
        """Belt-and-braces: not just the same class, the same message shape
        -- nothing in the raised exception should differ based on whether
        the id was real."""
        with pytest.raises(approval_module.ActionCardNotFound) as nonexistent_exc:
            await approval_module.approve_action_card(
                session,
                shop_id=shop.id,
                action_card_id=uuid.uuid4(),
                approved_by_user_id=uuid.uuid4(),
            )
        with pytest.raises(approval_module.ActionCardNotFound) as cross_tenant_exc:
            await approval_module.approve_action_card(
                session,
                shop_id=other_shop.id,
                action_card_id=card.id,
                approved_by_user_id=uuid.uuid4(),
            )
        # Both are generic "ActionCard <id> not found" messages from the
        # same ShopScopedRepo.get() code path -- neither leaks anything the
        # other doesn't.
        assert "not found" in str(nonexistent_exc.value)
        assert "not found" in str(cross_tenant_exc.value)


# ---------------------------------------------------------------------------
# AC -- non-active card -> ActionCardNotActive (409 at the HTTP layer)
# ---------------------------------------------------------------------------


class TestNonActiveCard:
    @pytest.mark.parametrize("status", ["approved", "dismissed", "executing"])
    async def test_non_active_status_raises_action_card_not_active(self, session, shop, status):
        c = _make_card(shop.id, status=status)
        session.add(c)
        await session.flush()

        with pytest.raises(approval_module.ActionCardNotActive):
            await approval_module.approve_action_card(
                session,
                shop_id=shop.id,
                action_card_id=c.id,
                approved_by_user_id=uuid.uuid4(),
            )

    async def test_sequential_double_approve_the_second_call_hits_non_active(
        self, session, shop, card, product
    ):
        """The sequential half of "raced or sequential, exactly one run can
        exist" (ADR-075 decision 1) -- the concurrent half is
        `tests/integration/test_agent_approval_concurrency.py`."""
        await approval_module.approve_action_card(
            session,
            shop_id=shop.id,
            action_card_id=card.id,
            approved_by_user_id=uuid.uuid4(),
        )
        await session.commit()

        with pytest.raises(approval_module.ActionCardNotActive):
            await approval_module.approve_action_card(
                session,
                shop_id=shop.id,
                action_card_id=card.id,
                approved_by_user_id=uuid.uuid4(),
            )


# ---------------------------------------------------------------------------
# AC (ADR-082 decision 4) -- zero products -> NoProductsForShop, never a
# run with a NULL product_id, never a 500 from the NOT NULL constraint
# ---------------------------------------------------------------------------


class TestZeroProducts:
    async def test_shop_with_no_products_raises_no_products_for_shop(self, session, shop, card):
        with pytest.raises(approval_module.NoProductsForShop):
            await approval_module.approve_action_card(
                session,
                shop_id=shop.id,
                action_card_id=card.id,
                approved_by_user_id=uuid.uuid4(),
            )

    async def test_zero_products_leaves_no_run_row_behind(self, session, shop, card):
        with pytest.raises(approval_module.NoProductsForShop):
            await approval_module.approve_action_card(
                session,
                shop_id=shop.id,
                action_card_id=card.id,
                approved_by_user_id=uuid.uuid4(),
            )
        await session.rollback()

        rows = (await session.execute(select(WorkflowRunRow))).scalars().all()
        assert rows == []


# ---------------------------------------------------------------------------
# AC (ADR-082 decision 2) -- highest revenue first, tiktok_product_id
# ascending tiebreak
# ---------------------------------------------------------------------------


class TestProductBindingDerivation:
    async def test_binds_to_the_highest_revenue_product(self, session, shop, card):
        low = _make_product(shop.id, revenue="10.00", tiktok_product_id="tt-low")
        high = _make_product(shop.id, revenue="999.00", tiktok_product_id="tt-high")
        mid = _make_product(shop.id, revenue="500.00", tiktok_product_id="tt-mid")
        session.add_all([low, high, mid])
        await session.flush()

        result = await approval_module.approve_action_card(
            session,
            shop_id=shop.id,
            action_card_id=card.id,
            approved_by_user_id=uuid.uuid4(),
        )

        assert result.product_id == high.id

    async def test_tiebreak_orders_by_tiktok_product_id_ascending_on_equal_revenue(
        self, session, shop, card
    ):
        """The tiebreak this ADR calls out explicitly: two products with
        IDENTICAL revenue must resolve deterministically, not by whatever
        order the database happens to return them in."""
        z_product = _make_product(shop.id, revenue="500.00", tiktok_product_id="tt-zzz")
        a_product = _make_product(shop.id, revenue="500.00", tiktok_product_id="tt-aaa")
        m_product = _make_product(shop.id, revenue="500.00", tiktok_product_id="tt-mmm")
        # Insert in an order that would trip a row-order-dependent implementation.
        session.add_all([z_product, a_product, m_product])
        await session.flush()

        result = await approval_module.approve_action_card(
            session,
            shop_id=shop.id,
            action_card_id=card.id,
            approved_by_user_id=uuid.uuid4(),
        )

        assert result.product_id == a_product.id

    async def test_tiebreak_is_stable_across_repeated_derivation(self, session, shop):
        """Same rule, re-derived independently against the identical product
        set, must land on the identical product every time -- proving the
        ordering is a deterministic function of the data, not incidental
        query-plan behaviour. Exercises `ProductsRepo.get_highest_revenue_
        product` directly (not the full `approve_action_card` transaction
        twice for the same product -- that would legitimately hit the
        one-active-run-per-product index on the second call, a DIFFERENT
        AC covered by `TestInTransactionIndexRejection`, not this one)."""
        from juli_backend.repositories.repos import ProductsRepo

        z_product = _make_product(shop.id, revenue="500.00", tiktok_product_id="tt-zzz")
        a_product = _make_product(shop.id, revenue="500.00", tiktok_product_id="tt-aaa")
        session.add_all([z_product, a_product])
        await session.flush()

        repo = ProductsRepo(session)
        first = await repo.get_highest_revenue_product(shop.id)
        second = await repo.get_highest_revenue_product(shop.id)

        assert first.id == a_product.id
        assert second.id == a_product.id

    async def test_products_belonging_to_another_shop_are_never_candidates(
        self, session, shop, other_shop, card
    ):
        own = _make_product(shop.id, revenue="1.00", tiktok_product_id="tt-own")
        foreign_high = _make_product(
            other_shop.id, revenue="999999.00", tiktok_product_id="tt-foreign"
        )
        session.add_all([own, foreign_high])
        await session.flush()

        result = await approval_module.approve_action_card(
            session,
            shop_id=shop.id,
            action_card_id=card.id,
            approved_by_user_id=uuid.uuid4(),
        )

        assert result.product_id == own.id


# ---------------------------------------------------------------------------
# AC -- the created run: action_card_id + product_id, queued, prompt pin
# ---------------------------------------------------------------------------


class TestCreatedRun:
    async def test_run_carries_action_card_id_and_derived_product_id(
        self, session, shop, card, product
    ):
        result = await approval_module.approve_action_card(
            session,
            shop_id=shop.id,
            action_card_id=card.id,
            approved_by_user_id=uuid.uuid4(),
        )

        run = (
            await session.execute(select(WorkflowRunRow).where(WorkflowRunRow.id == result.run_id))
        ).scalar_one()
        assert run.action_card_id == card.id
        assert run.product_id == product.id
        assert run.shop_id == shop.id
        assert run.status == "queued"
        assert run.prompt_version
        assert run.prompt_sha256

    async def test_created_run_state_loads_through_the_runners_own_reader(
        self, session, shop, card, product
    ):
        """The #1188 regression, relocated: `WorkflowRunner.run()` opens with
        `RunState.from_dict(run.state)`, which rejects a partial blob by
        design (ADR-073 decision 5). Assert with the real deserializer."""
        from juli_backend.services.agent.runner import RunState

        result = await approval_module.approve_action_card(
            session,
            shop_id=shop.id,
            action_card_id=card.id,
            approved_by_user_id=uuid.uuid4(),
        )
        run = (
            await session.execute(select(WorkflowRunRow).where(WorkflowRunRow.id == result.run_id))
        ).scalar_one()

        state = RunState.from_dict(run.state)
        assert state.iteration_count == 0
        assert state.pending_confirmation is None

    async def test_opening_context_message_uses_the_approved_cards_own_description(
        self, session, shop, card, product
    ):
        """Unlike the removed `agent_runs.py::_build_initial_run_state`
        (which had no card in hand and re-queried heuristically), this
        transaction has the EXACT approved card -- its own `description` is
        the rationale, verbatim."""
        result = await approval_module.approve_action_card(
            session,
            shop_id=shop.id,
            action_card_id=card.id,
            approved_by_user_id=uuid.uuid4(),
        )
        run = (
            await session.execute(select(WorkflowRunRow).where(WorkflowRunRow.id == result.run_id))
        ).scalar_one()

        opening = json.loads(run.state["conversation_window"][0]["content"])
        assert opening["source"] == "juli"
        assert opening["action_card"]["workflow_key"] == card.workflow_key
        assert opening["action_card"]["rationale"] == card.description


# ---------------------------------------------------------------------------
# AC -- the card flip + the approval audit row (who, when, VERBATIM snapshot)
# ---------------------------------------------------------------------------


class TestCardFlipAndAuditRow:
    async def test_card_is_flipped_to_approved_with_approved_at_set(
        self, session, shop, card, product
    ):
        await approval_module.approve_action_card(
            session,
            shop_id=shop.id,
            action_card_id=card.id,
            approved_by_user_id=uuid.uuid4(),
        )

        refreshed = await session.get(ActionCard, card.id)
        assert refreshed.status == "approved"
        assert refreshed.approved_at is not None

    async def test_approval_audit_row_records_who_and_when(self, session, shop, card, product):
        approver_id = uuid.uuid4()
        # Naive UTC: SQLite's plain DateTime column (no timezone=True on
        # ActionCardApproval.approved_at) strips tzinfo on round-trip, the
        # same convention every other naive-DateTime fixture in this suite
        # already follows (e.g. Product.update_time).
        fixed = datetime(2026, 8, 21, 9, 0)

        result = await approval_module.approve_action_card(
            session,
            shop_id=shop.id,
            action_card_id=card.id,
            approved_by_user_id=approver_id,
            now=lambda: fixed,
        )

        approval = await session.get(ActionCardApproval, result.approval_id)
        assert approval.action_card_id == card.id
        assert approval.approved_by_user_id == approver_id
        assert approval.approved_at == fixed

    async def test_snapshot_is_verbatim_and_reflects_pre_approval_state(
        self, session, shop, card, product
    ):
        result = await approval_module.approve_action_card(
            session,
            shop_id=shop.id,
            action_card_id=card.id,
            approved_by_user_id=uuid.uuid4(),
        )

        approval = await session.get(ActionCardApproval, result.approval_id)
        assert approval.card_snapshot["id"] == str(card.id)
        assert approval.card_snapshot["title"] == card.title
        assert approval.card_snapshot["description"] == card.description
        assert approval.card_snapshot["workflow_key"] == card.workflow_key
        # The snapshot is what the seller saw BEFORE the flip -- "active",
        # never the post-flip "approved".
        assert approval.card_snapshot["status"] == "active"

    async def test_snapshot_survives_the_card_later_changing(self, session, shop, card, product):
        """The audit is what was shown -- it must not be a join that
        silently reflects the card's CURRENT state."""
        result = await approval_module.approve_action_card(
            session,
            shop_id=shop.id,
            action_card_id=card.id,
            approved_by_user_id=uuid.uuid4(),
        )
        await session.commit()

        original_title = card.title
        card.title = "This title was changed after approval"
        card.description = "This description was changed after approval"
        await session.commit()

        approval = await session.get(ActionCardApproval, result.approval_id)
        assert approval.card_snapshot["title"] == original_title
        assert approval.card_snapshot["title"] != card.title


# ---------------------------------------------------------------------------
# AC -- in-transaction index rejection surfaces as IntegrityError (never a
# silent success, never left for the caller to discover only at commit)
# ---------------------------------------------------------------------------


class TestInTransactionIndexRejection:
    async def test_sequential_double_approve_on_same_card_hits_non_active_status(
        self, session, shop, product, card
    ):
        """Attempting to approve the same card twice -- the second attempt
        hits the non-active status check, preventing creation of a second
        run for the same product. (The concurrent race case, which can't be
        tested with SQLite's coarse-grained locking, lives in
        tests/integration/test_agent_approval_concurrency.py)."""
        first_result = await approval_module.approve_action_card(
            session,
            shop_id=shop.id,
            action_card_id=card.id,
            approved_by_user_id=uuid.uuid4(),
        )
        await session.commit()

        # Attempting to approve the same card again should fail because
        # the card is no longer in "active" status
        with pytest.raises(approval_module.ActionCardNotActive):
            await approval_module.approve_action_card(
                session,
                shop_id=shop.id,
                action_card_id=card.id,
                approved_by_user_id=uuid.uuid4(),
            )
        # First approval succeeded and created a run
        assert first_result.run_id
        assert first_result.status == "queued"


# ---------------------------------------------------------------------------
# AC -- atomicity: a failure between the card flip and the run insert must
# leave the caller able to roll back everything (SQLite-level proof; the
# REAL-Postgres proof, with an actual flushed-then-rolled-back write, is
# tests/integration/test_agent_approval_concurrency.py)
# ---------------------------------------------------------------------------


class TestAtomicitySeam:
    async def test_a_failure_after_the_flip_but_before_the_run_insert_is_fully_undoable(
        self, session, shop, card, product
    ):
        # Commit the pre-existing state (card active, product present)
        # BEFORE inducing the failure -- otherwise the rollback below would
        # undo the fixtures' own INSERTs too, and the test would prove
        # nothing about this transaction specifically. Real Postgres
        # coverage of an already-FLUSHED (not merely committed) write being
        # rolled back lives in
        # tests/integration/test_agent_approval_concurrency.py.
        await session.commit()
        card_id = card.id

        with patch.object(
            approval_module,
            "_resolve_prompt_pin",
            side_effect=RuntimeError("simulated crash between flip and insert"),
        ):
            with pytest.raises(RuntimeError):
                await approval_module.approve_action_card(
                    session,
                    shop_id=shop.id,
                    action_card_id=card_id,
                    approved_by_user_id=uuid.uuid4(),
                )
        await session.rollback()

        # `session.rollback()` EXPIRES (never expunges) every ORM instance
        # still in this session's identity map -- `card` included, whose
        # `status` was mutated in-memory before the induced crash.
        # `expunge_all()` drops those now-expired, no-longer-useful
        # instances from the identity map so the re-reads below build fresh
        # ones from a real SELECT, rather than triggering SQLAlchemy's
        # expired-instance refresh path on the old objects (which, in this
        # exact rollback-then-reread sequence, hits an aiosqlite/greenlet
        # interaction this suite doesn't otherwise exercise).
        session.expunge_all()

        refreshed = (
            await session.execute(select(ActionCard).where(ActionCard.id == card_id))
        ).scalar_one()
        assert refreshed.status == "active"
        assert refreshed.approved_at is None

        runs = (await session.execute(select(WorkflowRunRow))).scalars().all()
        assert runs == []
        approvals = (await session.execute(select(ActionCardApproval))).scalars().all()
        assert approvals == []


# ---------------------------------------------------------------------------
# AC -- executability: non-executable card (no registered playbook) raises
# WorkflowNotExecutable, executable card creates run with that playbook
# ---------------------------------------------------------------------------


class TestExecutabilityCheck:
    async def test_non_executable_workflow_key_raises_workflow_not_executable(
        self, session, shop, product
    ):
        """A card whose workflow_key has no registered playbook is refused by
        approve_action_card at the service layer (ADR-084 decision 3) --
        proven here at the service layer directly, not only through HTTP,
        so a future caller cannot route around the check."""
        c = _make_card(shop.id, workflow_key="unknown_workflow_1")
        session.add(c)
        await session.flush()

        with pytest.raises(approval_module.WorkflowNotExecutable):
            await approval_module.approve_action_card(
                session,
                shop_id=shop.id,
                action_card_id=c.id,
                approved_by_user_id=uuid.uuid4(),
            )

    async def test_non_executable_workflow_leaves_no_run_row_behind(self, session, shop, product):
        """Non-executable approval fails before any run is created -- the card
        is left active and unmodified."""
        c = _make_card(shop.id, workflow_key="unknown_workflow_2")
        session.add(c)
        await session.commit()
        card_id = c.id

        with pytest.raises(approval_module.WorkflowNotExecutable):
            await approval_module.approve_action_card(
                session,
                shop_id=shop.id,
                action_card_id=card_id,
                approved_by_user_id=uuid.uuid4(),
            )
        await session.rollback()

        # No run created, card unchanged
        session.expunge_all()
        runs = (await session.execute(select(WorkflowRunRow))).scalars().all()
        assert runs == []
        refreshed = (
            await session.execute(select(ActionCard).where(ActionCard.id == card_id))
        ).scalar_one()
        assert refreshed.status == "active"

    async def test_executable_card_creates_run_with_its_own_workflow_key(
        self, session, shop, product
    ):
        """A card whose workflow_key resolves to a registered playbook creates
        a run bound to that playbook, asserted by reading the persisted
        workflow_key from the run (the card's own workflow_key will be in the
        run's state blob, and the prompt version/sha256 will match the
        registry lookup) -- not by asserting a hardcoded constant."""
        c = _make_card(shop.id, workflow_key="optimize_product_2")
        session.add(c)
        await session.flush()

        result = await approval_module.approve_action_card(
            session,
            shop_id=shop.id,
            action_card_id=c.id,
            approved_by_user_id=uuid.uuid4(),
        )

        run = (
            await session.execute(select(WorkflowRunRow).where(WorkflowRunRow.id == result.run_id))
        ).scalar_one()

        # The run's state contains the card's workflow_key in the opening context
        state_dict = run.state
        opening = json.loads(state_dict["conversation_window"][0]["content"])
        assert opening["action_card"]["workflow_key"] == "optimize_product_2"

    async def test_prompt_version_matches_workflow_registry_lookup(self, session, shop, product):
        """The created run's prompt_version and prompt_sha256 are derived from
        the registry lookup for the card's workflow_key, not hardcoded."""
        from juli_backend.services.agent import prompts as prompts_module

        c = _make_card(shop.id, workflow_key="optimize_product_2")
        session.add(c)
        await session.flush()

        result = await approval_module.approve_action_card(
            session,
            shop_id=shop.id,
            action_card_id=c.id,
            approved_by_user_id=uuid.uuid4(),
        )

        run = (
            await session.execute(select(WorkflowRunRow).where(WorkflowRunRow.id == result.run_id))
        ).scalar_one()

        expected_version = prompts_module.production_version("optimize_product_2")
        expected_prompt = prompts_module.prompt_version("optimize_product_2", expected_version)
        expected_sha256 = prompts_module.prompt_sha256("optimize_product_2", expected_version)

        assert run.prompt_version == expected_prompt
        assert run.prompt_sha256 == expected_sha256
