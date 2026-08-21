"""`ConversationStore` protocol and its JSONB-blob implementation —
ADR-073 decision 5, issue #1118 / AGT-W3A.

The protocol-shape tests need no database. The `JsonbConversationStore`
round-trip tests use the shared in-memory `session` fixture from
`tests/unit/conftest.py` (sqlite+aiosqlite, `Base.metadata.create_all`) —
the same fixture `test_repos.py` uses for its repository tests — so the
`workflow_runs.state` column really is exercised, without needing a real
Postgres instance.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.exceptions import NotFound
from juli_backend.models.models import Product, RunConfirmation, Shop, User, WorkflowRun
from juli_backend.services.agent.events.payloads import ConfirmationOptionPayload
from juli_backend.services.agent.runner.conversation_store import (
    ConversationStore,
    JsonbConversationStore,
    PendingConfirmationWrite,
)
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.status import WorkflowRunStatus

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PACKAGE_DIR = REPO_ROOT / "backend/src/juli_backend/services/agent/runner"


async def _seed_workflow_run(session: AsyncSession, *, state: dict | None = None) -> uuid.UUID:
    user = User(id=uuid.uuid4(), phone=f"+8490{uuid.uuid4().int % 10_000_000:07d}")
    shop = Shop(id=uuid.uuid4(), user_id=user.id, shop_name="Test Shop")
    product = Product(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_product_id="tt-1",
        name="Test Product",
        status="active",
        update_time=datetime.now(UTC),
    )
    run = WorkflowRun(
        id=uuid.uuid4(),
        shop_id=shop.id,
        product_id=product.id,
        state=state if state is not None else RunState().to_dict(),
        status="running",
        prompt_version="v1",
        prompt_sha256="0" * 64,
    )
    session.add_all([user, shop, product, run])
    await session.flush()
    return run.id


class TestConversationStoreIsAStructuralProtocol:
    """AC4: ConversationStore is a Protocol (or ABC) with load/persist
    methods — a minimal in-memory stub implementing just those methods
    satisfies the protocol via isinstance/structural check, proving no
    hidden extra requirement leaked in."""

    def test_minimal_stub_satisfies_isinstance_check(self):
        class InMemoryStub:
            def __init__(self):
                self._store: dict[uuid.UUID, RunState] = {}

            async def load(self, workflow_run_id: uuid.UUID) -> RunState:
                return self._store[workflow_run_id]

            async def persist(self, workflow_run_id: uuid.UUID, state: RunState) -> None:
                self._store[workflow_run_id] = state

        stub = InMemoryStub()

        assert isinstance(stub, ConversationStore)

    def test_object_missing_persist_does_not_satisfy_the_protocol(self):
        class LoadOnly:
            async def load(self, workflow_run_id: uuid.UUID) -> RunState:
                raise NotImplementedError

        assert not isinstance(LoadOnly(), ConversationStore)

    def test_jsonb_implementation_satisfies_the_protocol_structurally(self):
        # No real session needed just to prove the structural shape matches.
        assert isinstance(JsonbConversationStore(session=None), ConversationStore)  # type: ignore[arg-type]


class TestJsonbConversationStoreRoundTrip:
    """AC5 exercised end-to-end against the real `workflow_runs.state`
    column (not just the pure `RunState.to_dict`/`from_dict` functions
    covered in `test_run_state.py`)."""

    async def test_persist_then_load_round_trips_every_field(self, session: AsyncSession):
        run_id = await _seed_workflow_run(session)
        store = JsonbConversationStore(session)
        original = RunState(
            conversation_window=[{"role": "user", "content": "optimize this listing"}],
            iteration_count=2,
            extensions_granted=1,
            next_sequence=9,
            pending_confirmation={"tool_call_id": "call_1", "tool_name": "update_price"},
            basis_snapshots={"price": "sha256:deadbeef"},
            running_seconds_elapsed=17.5,
        )

        await store.persist(run_id, original)
        loaded = await store.load(run_id)

        assert loaded.conversation_window == original.conversation_window
        assert loaded.iteration_count == original.iteration_count
        assert loaded.extensions_granted == original.extensions_granted
        assert loaded.next_sequence == original.next_sequence
        assert loaded.pending_confirmation == original.pending_confirmation
        assert loaded.basis_snapshots == original.basis_snapshots
        assert loaded.running_seconds_elapsed == original.running_seconds_elapsed

    async def test_next_sequence_survives_pause_and_resume_in_a_fresh_store(
        self, session: AsyncSession
    ):
        """Load-bearing: if next_sequence resets across a resume, a
        resumed run re-emits colliding event sequence numbers."""
        run_id = await _seed_workflow_run(session)
        first_worker_store = JsonbConversationStore(session)
        state = RunState()
        minted = [state.allocate_sequence() for _ in range(3)]
        # #1195: a run's first event is sequence 1, never 0 -- 0 is the
        # "nothing seen yet" sentinel the SSE replay cursor uses.
        assert minted == [1, 2, 3]
        await first_worker_store.persist(run_id, state)

        # Simulate a CONFIRM pause resuming in a different worker process:
        # a brand new store instance loading fresh from the DB row.
        second_worker_store = JsonbConversationStore(session)
        resumed_state = await second_worker_store.load(run_id)

        assert resumed_state.next_sequence == minted[-1] + 1
        next_minted = resumed_state.allocate_sequence()
        assert next_minted not in minted  # no reuse across the resume
        assert next_minted == minted[-1] + 1

    async def test_load_raises_not_found_for_unknown_run(self, session: AsyncSession):
        store = JsonbConversationStore(session)

        with pytest.raises(NotFound):
            await store.load(uuid.uuid4())

    async def test_persist_raises_not_found_for_unknown_run(self, session: AsyncSession):
        store = JsonbConversationStore(session)

        with pytest.raises(NotFound):
            await store.persist(uuid.uuid4(), RunState())


class TestPendingConfirmationWrite:
    """`persist`'s `pending_confirmation` kwarg (issue #1221 / AGT-W5A,
    ADR-075 decision 2) -- a true no-op by default (`None`), exactly like
    `status`/`stop_reason`/`required_steps_completed`/
    `running_seconds_elapsed` before it; when passed, writes exactly one
    `run_confirmations` row with `status='pending'`."""

    def _option(self, *, params_sha: str = "a" * 64) -> ConfirmationOptionPayload:
        return ConfirmationOptionPayload(
            option_id="1",
            proposed_change={"skus": [{"sku_ref": "S1", "amount": "179000"}]},
            rationale="Apply new SKU prices to the bound product.",
            params_sha=params_sha,
        )

    async def test_persist_with_no_pending_confirmation_writes_no_row(self, session: AsyncSession):
        run_id = await _seed_workflow_run(session)
        store = JsonbConversationStore(session)

        await store.persist(run_id, RunState())

        rows = (
            (
                await session.execute(
                    select(RunConfirmation).where(RunConfirmation.workflow_run_id == run_id)
                )
            )
            .scalars()
            .all()
        )
        assert rows == []

    async def test_persist_with_pending_confirmation_writes_exactly_one_pending_row(
        self, session: AsyncSession
    ):
        run_id = await _seed_workflow_run(session)
        store = JsonbConversationStore(session)
        expires_at = datetime.now(UTC) + timedelta(hours=4)
        option = self._option()

        await store.persist(
            run_id,
            RunState(),
            status=WorkflowRunStatus.WAITING_APPROVAL,
            pending_confirmation=PendingConfirmationWrite(
                tool_call_id="call_1",
                options=[option],
                expires_at=expires_at,
            ),
        )

        rows = (
            (
                await session.execute(
                    select(RunConfirmation).where(RunConfirmation.workflow_run_id == run_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        row = rows[0]
        assert row.tool_call_id == "call_1"
        assert row.status == "pending"
        assert row.selected_option_id is None
        assert row.decided_at is None
        # sqlite (this test's backend, per this module's own docstring)
        # round-trips `DateTime(timezone=True)` as a naive datetime --
        # compare on naive UTC wall-clock value, matching this file's
        # sqlite-vs-Postgres discipline elsewhere.
        assert row.expires_at.replace(tzinfo=UTC) == expires_at
        # AC: storage round-trips proposed_change byte-identically -- the
        # exact same dict that was passed in, not a re-derivation.
        assert row.options == [option.model_dump(mode="json")]
        assert row.options[0]["proposed_change"] == option.proposed_change

    async def test_persist_with_pending_confirmation_leaves_status_columns_alone(
        self, session: AsyncSession
    ):
        """`pending_confirmation` and `status` are independent kwargs --
        writing the confirmation row must not implicitly stamp
        `waiting_approval_since` on its own; that stays `status`'s job,
        exactly as before this issue."""
        run_id = await _seed_workflow_run(session)
        store = JsonbConversationStore(session)

        await store.persist(
            run_id,
            RunState(),
            pending_confirmation=PendingConfirmationWrite(
                tool_call_id="call_1",
                options=[self._option()],
                expires_at=datetime.now(UTC) + timedelta(hours=4),
            ),
        )

        row = await session.get(WorkflowRun, run_id)
        assert row is not None
        assert row.waiting_approval_since is None


class TestNoWorkflowRunnerInThisSlice:
    """AC8: no WorkflowRunner class exists or is imported by this slice's
    production code — this slice is provably runner-independent.

    Docstring prose *documenting* the deferral is expected and fine — what
    must not appear is an actual class definition or import."""

    def test_conversation_store_module_defines_no_workflow_runner_class(self):
        source = (RUNNER_PACKAGE_DIR / "conversation_store.py").read_text()
        assert "class WorkflowRunner" not in source

    def test_conversation_store_module_imports_no_workflow_runner(self):
        source = (RUNNER_PACKAGE_DIR / "conversation_store.py").read_text()
        assert "import WorkflowRunner" not in source

    def test_init_module_never_defines_workflow_runner(self):
        source = (RUNNER_PACKAGE_DIR / "__init__.py").read_text()
        assert "class WorkflowRunner" not in source
        assert "import WorkflowRunner" not in source
