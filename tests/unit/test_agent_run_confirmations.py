"""Pure ladder logic for ``decide_confirmation`` (ADR-075 decision 2, #1224).

No HTTP here: the route's mapping of a raised ``ConfirmationRejected`` onto an
HTTP status and ``{"detail": {"error_code", ...}}`` body is
``test_agent_confirmation_decision_route.py``'s job. This module calls
``decide_confirmation`` directly against a real session and asserts on its
return value, its raised exception, and the rows it leaves behind -- the
ladder documented in ``services/agent_runs/confirmations.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from juli_backend.models.models import RunConfirmation
from juli_backend.services.agent.runner import compute_params_sha
from juli_backend.services.agent_runs import (
    ERROR_CONFIRMATION_ALREADY_DECIDED,
    ERROR_CONFIRMATION_EXPIRED,
    ERROR_CONFIRMATION_NOT_FOUND,
    ERROR_INVALID_DECISION,
    ERROR_OPTION_ID_REQUIRED,
    ERROR_PARAMS_SHA_MISMATCH,
    ERROR_RUN_NOT_AWAITING_CONFIRMATION,
    ERROR_RUN_STATE_NOT_RECONSTRUCTABLE,
    ERROR_UNKNOWN_OPTION_ID,
    ConfirmationDecision,
    ConfirmationRejected,
    decide_confirmation,
)
from juli_backend.services.agent_runs import confirmations as confirmations_module
from tests.support.builders import make_workflow_run

TOOL_CALL_ID = "call-listing-1"
PROPOSED_CHANGE = {"title": "New improved title"}


async def make_confirmation(
    session,
    run,
    *,
    tool_call_id: str = TOOL_CALL_ID,
    status: str = "pending",
    proposed_change: dict | None = None,
    params_sha: str | None = None,
    expires_at: datetime | None = None,
    selected_option_id: str | None = None,
) -> RunConfirmation:
    """A ``run_confirmations`` row. Candidate for ``tests/support/builders.py``."""
    change = proposed_change if proposed_change is not None else PROPOSED_CHANGE
    sha = params_sha if params_sha is not None else compute_params_sha(change)
    confirmation = RunConfirmation(
        workflow_run_id=run.id,
        tool_call_id=tool_call_id,
        options=[
            {"option_id": "1", "proposed_change": change, "rationale": "why", "params_sha": sha}
        ],
        status=status,
        selected_option_id=selected_option_id,
        expires_at=expires_at or (datetime.now(UTC) + timedelta(hours=4)),
    )
    session.add(confirmation)
    await session.flush()
    return confirmation


async def seed_pending(session, shop, *, tool_call_id: str = TOOL_CALL_ID, arguments=None):
    """A run paused mid-CONFIRM with a matching pending row: ``arguments`` and
    ``proposed_change`` agree, so ``params_sha`` matches by construction."""
    run = await make_workflow_run(
        session,
        shop,
        status="waiting_approval",
        state={
            "pending_confirmation": {
                "call_id": tool_call_id,
                "tool_name": "update_product_listing",
                "arguments": arguments if arguments is not None else PROPOSED_CHANGE,
            }
        },
    )
    confirmation = await make_confirmation(session, run, tool_call_id=tool_call_id)
    return run, confirmation


async def decide(session, run, *, decision: str, option_id: str | None = None, **overrides):
    return await decide_confirmation(
        session,
        run,
        tool_call_id=overrides.pop("tool_call_id", TOOL_CALL_ID),
        decision=decision,
        option_id=option_id,
        **overrides,
    )


class TestRunStatusRung:
    """Rung 1: a run that is not ``waiting_approval`` is refused outright."""

    @pytest.mark.parametrize(
        "run_status",
        ["queued", "running", "completed", "cancelled", "timed_out", "failed"],
    )
    async def test_non_waiting_approval_run_is_refused(self, session, shop, run_status):
        run = await make_workflow_run(session, shop, status=run_status)

        with pytest.raises(ConfirmationRejected, match="not awaiting") as exc_info:
            await decide(session, run, decision="decline")

        assert exc_info.value.error_code == ERROR_RUN_NOT_AWAITING_CONFIRMATION


class TestConfirmationMatchRung:
    """Rung 2: the ``tool_call_id`` must name a pending row for this run."""

    async def test_unknown_tool_call_id_is_not_found(self, session, shop):
        run = await make_workflow_run(session, shop, status="waiting_approval")

        with pytest.raises(ConfirmationRejected, match="No confirmation") as exc_info:
            await decide(session, run, decision="decline", tool_call_id="never-paused-here")

        assert exc_info.value.error_code == ERROR_CONFIRMATION_NOT_FOUND

    @pytest.mark.parametrize("prior_status", ["approved", "declined"])
    async def test_a_resolved_confirmation_is_single_use(self, session, shop, prior_status):
        run = await make_workflow_run(session, shop, status="waiting_approval")
        await make_confirmation(session, run, status=prior_status)

        with pytest.raises(ConfirmationRejected, match="already decided") as exc_info:
            await decide(session, run, decision="decline")

        assert exc_info.value.error_code == ERROR_CONFIRMATION_ALREADY_DECIDED

    async def test_a_row_already_flipped_expired_is_reported_as_expired_not_already_decided(
        self, session, shop
    ):
        """Defensive: nothing writes ``status='expired'`` onto a row today (the
        reaper only ever transitions ``workflow_runs.status``), but the ladder
        must still answer correctly if a future writer ever does."""
        run = await make_workflow_run(session, shop, status="waiting_approval")
        await make_confirmation(session, run, status="expired")

        with pytest.raises(ConfirmationRejected, match="expired") as exc_info:
            await decide(session, run, decision="decline")

        assert exc_info.value.error_code == ERROR_CONFIRMATION_EXPIRED


class TestWallClockExpiryRung:
    """Rung 3: expiry is checked directly against ``expires_at``, not the reaper."""

    async def test_past_the_deadline_is_refused_and_the_row_is_left_pending(self, session, shop):
        run, confirmation = await seed_pending(session, shop)
        past_deadline = confirmation.expires_at + timedelta(seconds=1)

        with pytest.raises(ConfirmationRejected, match="expired") as exc_info:
            await decide(session, run, decision="decline", now=past_deadline)

        assert exc_info.value.error_code == ERROR_CONFIRMATION_EXPIRED
        await session.refresh(confirmation)
        assert confirmation.status == "pending", "left for the reaper, not mutated here"

    async def test_a_moment_before_the_deadline_still_succeeds(self, session, shop):
        run, confirmation = await seed_pending(session, shop)
        just_before_deadline = confirmation.expires_at - timedelta(seconds=1)

        outcome = await decide(session, run, decision="decline", now=just_before_deadline)

        assert outcome.approved is False


class TestDecisionValidationRung:
    """Rung 4: the decision vocabulary, and option_id's presence/membership."""

    async def test_a_decision_outside_approve_or_decline_is_invalid(self, session, shop):
        run, _ = await seed_pending(session, shop)

        with pytest.raises(ConfirmationRejected, match="approve.*decline") as exc_info:
            await decide(session, run, decision="maybe")

        assert exc_info.value.error_code == ERROR_INVALID_DECISION

    async def test_approve_without_an_option_id_is_rejected(self, session, shop):
        run, _ = await seed_pending(session, shop)

        with pytest.raises(ConfirmationRejected, match="option_id") as exc_info:
            await decide(session, run, decision="approve", option_id=None)

        assert exc_info.value.error_code == ERROR_OPTION_ID_REQUIRED

    async def test_approve_with_an_option_id_not_among_the_options_is_rejected(self, session, shop):
        run, _ = await seed_pending(session, shop)

        with pytest.raises(ConfirmationRejected, match="not one of") as exc_info:
            await decide(session, run, decision="approve", option_id="not-a-real-option")

        assert exc_info.value.error_code == ERROR_UNKNOWN_OPTION_ID


class TestConsentBindingRung:
    """Rung 5: the chosen option must match what the run would actually execute."""

    async def test_params_sha_mismatch_is_refused_and_the_row_stays_pending(self, session, shop):
        """The option's ``params_sha`` was computed over ``PROPOSED_CHANGE``, but
        the run's reconstructed ``arguments`` now names a different change --
        simulating drift between what was shown and what would execute."""
        run, confirmation = await seed_pending(
            session, shop, arguments={"title": "a different title than what was shown"}
        )

        with pytest.raises(ConfirmationRejected, match="no longer matches") as exc_info:
            await decide(session, run, decision="approve", option_id="1")

        assert exc_info.value.error_code == ERROR_PARAMS_SHA_MISMATCH
        await session.refresh(confirmation)
        assert confirmation.status == "pending", (
            "a mismatch must not consume the single-use decision"
        )

    async def test_a_run_with_no_reconstructable_pending_state_is_refused(self, session, shop):
        run = await make_workflow_run(session, shop, status="waiting_approval")  # state == {}
        await make_confirmation(session, run)

        with pytest.raises(ConfirmationRejected, match="reconstructable") as exc_info:
            await decide(session, run, decision="approve", option_id="1")

        assert exc_info.value.error_code == ERROR_RUN_STATE_NOT_RECONSTRUCTABLE


class TestWinningTheTransition:
    """A won decision returns the outcome and persists it; option_id stamping too."""

    async def test_decline_returns_the_outcome_and_transitions_the_row(self, session, shop):
        run, confirmation = await seed_pending(session, shop)

        outcome = await decide(session, run, decision="decline")

        assert outcome == ConfirmationDecision(
            decision="decline", approved=False, new_status="declined"
        )
        await session.refresh(confirmation)
        assert confirmation.status == "declined"
        assert confirmation.selected_option_id is None
        assert confirmation.decided_at is not None

    async def test_approve_returns_the_outcome_transitions_the_row_and_stamps_params_sha(
        self, session, shop
    ):
        """``WorkflowRunner.resume()`` has no database access beyond its own
        state -- the validated hash is stamped onto
        ``run.state["pending_confirmation"]`` so ``resume()`` can
        independently re-derive and compare with no query of its own."""
        run, confirmation = await seed_pending(session, shop)
        expected_sha = compute_params_sha(PROPOSED_CHANGE)

        outcome = await decide(session, run, decision="approve", option_id="1")

        assert outcome == ConfirmationDecision(
            decision="approve", approved=True, new_status="approved"
        )
        await session.refresh(confirmation)
        assert confirmation.status == "approved"
        assert confirmation.selected_option_id == "1"
        assert run.state["pending_confirmation"]["params_sha"] == expected_sha
        # The rest of the pending_confirmation blob is untouched by the stamp.
        assert run.state["pending_confirmation"]["arguments"] == PROPOSED_CHANGE
        assert run.state["pending_confirmation"]["call_id"] == TOOL_CALL_ID

    async def test_a_second_decision_on_the_same_confirmation_loses_sequentially(
        self, session, shop
    ):
        run, confirmation = await seed_pending(session, shop)
        await decide(session, run, decision="approve", option_id="1")

        with pytest.raises(ConfirmationRejected) as exc_info:
            await decide(session, run, decision="decline")

        assert exc_info.value.error_code == ERROR_CONFIRMATION_ALREADY_DECIDED
        await session.refresh(confirmation)
        assert confirmation.status == "approved", "the losing decision must not overwrite it"

    async def test_a_concurrent_winner_is_reported_with_the_same_code_as_a_sequential_one(
        self, session, shop, monkeypatch
    ):
        """``transition_confirmation_or_none`` losing a race (its ``UPDATE``'s
        rowcount comes back 0 because a concurrent request already won) is a
        different code path than the sequential "already decided" read above,
        but the identical client-observable fact -- this pins that both carry
        ``ERROR_CONFIRMATION_ALREADY_DECIDED``, not two different codes. Real
        concurrency needs a real Postgres connection and lives in
        ``tests/integration/test_agent_confirmation_decision_postgres.py``;
        this session cannot construct it, so the loss is forced directly.
        """
        run, confirmation = await seed_pending(session, shop)

        async def _always_lose(*args, **kwargs) -> bool:
            return False

        monkeypatch.setattr(confirmations_module, "transition_confirmation_or_none", _always_lose)

        with pytest.raises(ConfirmationRejected) as exc_info:
            await decide(session, run, decision="approve", option_id="1")

        assert exc_info.value.error_code == ERROR_CONFIRMATION_ALREADY_DECIDED
        await session.refresh(confirmation)
        assert confirmation.status == "pending", (
            "the monkeypatched loss must not itself mutate the row"
        )
