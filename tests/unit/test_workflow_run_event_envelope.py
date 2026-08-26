"""Pydantic envelope + typed 8-event union contract tests for #1125 / AGT-W3B
(ADR-074 decision 2, ADR-071's `assistant.text.delta` reservation, ADR-073's
total `stop_reason` -> `WorkflowRunStatus` mapping).

No database, no network -- pure model construction/validation. Mirrors the
issue's acceptance-criteria language directly: each of the eight event
types round-trips with its exact payload fields, `v` is pinned to the
literal `1`, `assistant.text.delta` is not constructible, and
`workflow.failed`'s `stop_reason` is restricted to ADR-073's failure-class
members with `status` matching the mapped value.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from juli_backend.services.agent.events.envelope import (
    EVENT_TYPES,
    AssistantTextEvent,
    ToolCompletedEvent,
    ToolStartedEvent,
    WorkflowApprovalRequiredEvent,
    WorkflowCompletedEvent,
    WorkflowFailedEvent,
    WorkflowRunEvent,
    WorkflowRunEventAdapter,
    WorkflowStartedEvent,
    WorkflowStatusEvent,
)
from juli_backend.services.agent.events.payloads import (
    FAILURE_STOP_REASONS,
    AssistantTextPayload,
    ConfirmationOptionPayload,
    ToolCompletedPayload,
    ToolStartedPayload,
    WorkflowApprovalRequiredPayload,
    WorkflowCompletedPayload,
    WorkflowFailedPayload,
    WorkflowStartedPayload,
    WorkflowStatusPayload,
)
from juli_backend.services.agent.status import StopReason, WorkflowRunStatus

RUN_ID = uuid.uuid4()
NOW = datetime.now(UTC)


def _envelope_kwargs(event_type: str, payload) -> dict:
    return {
        "workflow_run_id": RUN_ID,
        "sequence_number": 0,
        "event_type": event_type,
        "timestamp": NOW,
        "payload": payload,
        "v": 1,
    }


# ---------------------------------------------------------------------------
# Eight event types round-trip with their exact payload fields.
# ---------------------------------------------------------------------------


def test_workflow_started_event_round_trips_exact_fields():
    payload = WorkflowStartedPayload(
        workflow_key="optimize_product",
        product_ref="prod-1",
        prompt_version="optimize_product.v1",
    )
    assert set(payload.model_dump()) == {"workflow_key", "product_ref", "prompt_version"}

    event = WorkflowStartedEvent(**_envelope_kwargs("workflow.started", payload))
    assert event.event_type == "workflow.started"
    assert event.payload.workflow_key == "optimize_product"
    assert event.v == 1

    with pytest.raises(ValidationError):
        WorkflowStartedPayload(
            workflow_key="k", product_ref="r", prompt_version="v", extra_field="nope"
        )
    with pytest.raises(ValidationError):
        WorkflowStartedPayload(workflow_key="k", product_ref="r")  # missing prompt_version


def test_workflow_status_event_round_trips_exact_fields():
    payload = WorkflowStatusPayload(phase_narration="Reviewing listing copy...")
    assert set(payload.model_dump()) == {"phase_narration"}

    event = WorkflowStatusEvent(**_envelope_kwargs("workflow.status", payload))
    assert event.payload.phase_narration == "Reviewing listing copy..."

    with pytest.raises(ValidationError):
        WorkflowStatusPayload(phase_narration="x", unexpected=True)
    with pytest.raises(ValidationError):
        WorkflowStatusPayload()


def test_assistant_text_event_round_trips_exact_fields():
    payload = AssistantTextPayload(text="Here is my plan.")
    assert set(payload.model_dump()) == {"text"}

    event = AssistantTextEvent(**_envelope_kwargs("assistant.text", payload))
    assert event.payload.text == "Here is my plan."

    with pytest.raises(ValidationError):
        AssistantTextPayload(text="x", delta=True)
    with pytest.raises(ValidationError):
        AssistantTextPayload()


def test_tool_started_event_round_trips_exact_fields():
    payload = ToolStartedPayload(tool_call_id="call-1", tool_name="update_price")
    assert set(payload.model_dump()) == {"tool_call_id", "tool_name"}

    event = ToolStartedEvent(**_envelope_kwargs("tool.started", payload))
    assert event.payload.tool_name == "update_price"

    with pytest.raises(ValidationError):
        ToolStartedPayload(tool_call_id="call-1", tool_name="x", extra="nope")
    with pytest.raises(ValidationError):
        ToolStartedPayload(tool_call_id="call-1")


def test_tool_completed_event_round_trips_exact_fields():
    payload = ToolCompletedPayload(
        tool_call_id="call-1", tool_name="update_price", ok=True, summary="Price updated."
    )
    assert set(payload.model_dump()) == {"tool_call_id", "tool_name", "ok", "summary"}

    event = ToolCompletedEvent(**_envelope_kwargs("tool.completed", payload))
    assert event.payload.ok is True

    with pytest.raises(ValidationError):
        ToolCompletedPayload(tool_call_id="c", tool_name="t", ok=True, summary="s", extra="nope")
    with pytest.raises(ValidationError):
        ToolCompletedPayload(tool_call_id="c", tool_name="t", ok=True)  # missing summary


def test_workflow_approval_required_event_round_trips_exact_fields():
    """No `options=` is passed here on purpose (issue #1221 / AGT-W5A):
    `options` defaults to `[]`, so this is also the regression guard for
    "a payload built the pre-#1221 way still constructs" -- see the
    dedicated `TestOptionsIsOptionalForBackwardCompatibility` class below
    for the full historical-row round-trip through the envelope/adapter."""
    payload = WorkflowApprovalRequiredPayload(
        tool_call_id="call-1",
        tool_name="update_price",
        proposed_change={"price": {"from": "19.99", "to": "17.99"}},
        expires_at=NOW,
    )
    assert payload.options == []
    assert set(payload.model_dump()) == {
        "tool_call_id",
        "tool_name",
        "proposed_change",
        "expires_at",
        "options",
    }

    event = WorkflowApprovalRequiredEvent(**_envelope_kwargs("workflow.approval_required", payload))
    assert event.payload.proposed_change["price"]["to"] == "17.99"

    with pytest.raises(ValidationError):
        WorkflowApprovalRequiredPayload(
            tool_call_id="c",
            tool_name="t",
            proposed_change={},
            expires_at=NOW,
            extra="nope",
        )
    with pytest.raises(ValidationError):
        WorkflowApprovalRequiredPayload(tool_call_id="c", tool_name="t")


class TestOptionsIsOptionalForBackwardCompatibility:
    """`options` defaults to `[]` (issue #1221 / AGT-W5A) specifically so a
    `workflow_run_events` row written *before* this issue -- which has no
    `options` key in its `payload` JSON at all -- still constructs through
    this same Pydantic model via `WorkflowRunEventAdapter.validate_python`,
    the adapter `envelope.py`'s own docstring names as "the Postgres replay
    authority" (ADR-074 decision 1). A required field would raise
    `ValidationError` on data that was valid when it was written; this
    class is the regression guard for that specific property, not merely a
    relaxed-type sanity check."""

    def test_a_pre_1221_four_field_payload_dict_still_validates_through_the_full_envelope(self):
        legacy_payload = {
            "tool_call_id": "call-legacy-1",
            "tool_name": "update_price",
            "proposed_change": {"price": {"from": "19.99", "to": "17.99"}},
            "expires_at": NOW.isoformat(),
            # deliberately no "options" key -- the exact shape a row
            # persisted before this issue shipped has in Postgres today.
        }
        raw_event = _envelope_kwargs("workflow.approval_required", legacy_payload)
        raw_event["workflow_run_id"] = str(RUN_ID)

        event = WorkflowRunEventAdapter.validate_python(raw_event)

        assert event.payload.options == []
        assert event.payload.proposed_change["price"]["to"] == "17.99"

    def test_a_new_payload_with_a_real_option_still_round_trips_alongside_the_default(self):
        """The default doesn't come at the cost of the new shape -- a
        freshly-built option list still constructs and round-trips
        normally; this class is about the *old* shape surviving, not about
        weakening the *new* one."""
        option = ConfirmationOptionPayload(
            option_id="1",
            proposed_change={"price": {"from": "19.99", "to": "17.99"}},
            rationale="Apply the new price.",
            params_sha="a" * 64,
        )
        payload = WorkflowApprovalRequiredPayload(
            tool_call_id="call-1",
            tool_name="update_price",
            proposed_change={"price": {"from": "19.99", "to": "17.99"}},
            expires_at=NOW,
            options=[option],
        )
        assert payload.options == [option]
        assert payload.model_dump()["options"][0]["option_id"] == "1"


def test_workflow_completed_event_round_trips_exact_fields():
    payload = WorkflowCompletedPayload(stop_reason=StopReason.FINAL_RESPONSE)
    assert set(payload.model_dump()) == {"stop_reason"}

    event = WorkflowCompletedEvent(**_envelope_kwargs("workflow.completed", payload))
    assert event.payload.stop_reason == StopReason.FINAL_RESPONSE

    with pytest.raises(ValidationError):
        WorkflowCompletedPayload(stop_reason=StopReason.FINAL_RESPONSE, extra="nope")
    with pytest.raises(ValidationError):
        WorkflowCompletedPayload()
    with pytest.raises(ValidationError):
        WorkflowCompletedPayload(stop_reason="not_a_real_stop_reason")


def test_workflow_failed_event_round_trips_exact_fields():
    payload = WorkflowFailedPayload(
        status=WorkflowRunStatus.FAILED, stop_reason=StopReason.LLM_ERROR
    )
    assert set(payload.model_dump()) == {"status", "stop_reason"}

    event = WorkflowFailedEvent(**_envelope_kwargs("workflow.failed", payload))
    assert event.payload.status == WorkflowRunStatus.FAILED

    with pytest.raises(ValidationError):
        WorkflowFailedPayload(
            status=WorkflowRunStatus.FAILED, stop_reason=StopReason.LLM_ERROR, extra="nope"
        )
    with pytest.raises(ValidationError):
        WorkflowFailedPayload(status=WorkflowRunStatus.FAILED)


def test_all_eight_event_types_named_and_no_more():
    assert set(EVENT_TYPES) == {
        "workflow.started",
        "workflow.status",
        "assistant.text",
        "tool.started",
        "tool.completed",
        "workflow.approval_required",
        "workflow.completed",
        "workflow.failed",
    }
    assert len(EVENT_TYPES) == 8


# ---------------------------------------------------------------------------
# `v` is pinned to the literal 1.
# ---------------------------------------------------------------------------


def test_v_missing_fails_validation():
    kwargs = _envelope_kwargs("assistant.text", AssistantTextPayload(text="hi"))
    del kwargs["v"]
    with pytest.raises(ValidationError):
        AssistantTextEvent(**kwargs)


def test_v_mismatched_fails_validation():
    kwargs = _envelope_kwargs("assistant.text", AssistantTextPayload(text="hi"))
    kwargs["v"] = 2
    with pytest.raises(ValidationError):
        AssistantTextEvent(**kwargs)


def test_v_correct_passes():
    kwargs = _envelope_kwargs("assistant.text", AssistantTextPayload(text="hi"))
    event = AssistantTextEvent(**kwargs)
    assert event.v == 1


# ---------------------------------------------------------------------------
# `sequence_number` is minted by the runner (ADR-074 d.1) -- this layer must
# never assign or default one. A future change quietly adding a default
# (e.g. `= 0`) would let two events for the same run construct successfully
# with no sequence number supplied, and a defaulted `0` would collide on the
# unique (workflow_run_id, sequence_number) index the moment two such events
# existed. Reviewed via mutation: temporarily adding `sequence_number: int =
# 0` to `_EventEnvelope` in envelope.py made this exact test fail (an event
# built with `sequence_number` omitted from kwargs constructed successfully
# instead of raising), then the default was removed and the suite re-ran
# green -- proving the test is not vacuous.
# ---------------------------------------------------------------------------


def test_sequence_number_missing_fails_validation():
    kwargs = _envelope_kwargs("assistant.text", AssistantTextPayload(text="hi"))
    del kwargs["sequence_number"]
    with pytest.raises(ValidationError):
        AssistantTextEvent(**kwargs)


# ---------------------------------------------------------------------------
# `WorkflowRunEvent` is a genuinely *discriminated* union (`Field(
# discriminator="event_type")`), not merely a union Pydantic's smart-mode
# Literal fallback happens to route correctly. Removing the discriminator
# entirely would still pass every parsing-outcome test above, so this
# inspects the union's actual field metadata / compiled core schema rather
# than only asserting that parsing routes to the right class.
# ---------------------------------------------------------------------------


def test_workflow_run_event_union_declares_discriminator_field_metadata():
    import typing

    union_type, field_info = typing.get_args(WorkflowRunEvent)
    assert getattr(field_info, "discriminator", None) == "event_type"


def test_workflow_run_event_adapter_compiles_to_a_tagged_union_on_event_type():
    core_schema = WorkflowRunEventAdapter.core_schema
    assert core_schema["type"] == "tagged-union", (
        "expected a discriminator-compiled tagged-union core schema, got "
        f"{core_schema['type']!r} -- did Field(discriminator=...) get removed?"
    )
    assert core_schema["discriminator"] == "event_type"


# ---------------------------------------------------------------------------
# `assistant.text.delta` stays reserved / unimplemented.
# ---------------------------------------------------------------------------


def test_assistant_text_delta_has_no_event_class():
    import juli_backend.services.agent.events.envelope as envelope_module

    for name in dir(envelope_module):
        assert "delta" not in name.lower(), f"unexpected delta-named symbol: {name}"


def test_assistant_text_delta_rejected_by_union_discriminant():
    raw = {
        "workflow_run_id": str(RUN_ID),
        "sequence_number": 0,
        "event_type": "assistant.text.delta",
        "timestamp": NOW.isoformat(),
        "payload": {"text": "partial"},
        "v": 1,
    }
    with pytest.raises(ValidationError):
        WorkflowRunEventAdapter.validate_python(raw)


def test_discriminated_union_validates_each_of_the_eight_types():
    samples = [
        WorkflowStartedEvent(
            **_envelope_kwargs(
                "workflow.started",
                WorkflowStartedPayload(workflow_key="k", product_ref="r", prompt_version="v1"),
            )
        ),
        WorkflowStatusEvent(
            **_envelope_kwargs("workflow.status", WorkflowStatusPayload(phase_narration="p"))
        ),
        AssistantTextEvent(**_envelope_kwargs("assistant.text", AssistantTextPayload(text="t"))),
        ToolStartedEvent(
            **_envelope_kwargs("tool.started", ToolStartedPayload(tool_call_id="c", tool_name="n"))
        ),
        ToolCompletedEvent(
            **_envelope_kwargs(
                "tool.completed",
                ToolCompletedPayload(tool_call_id="c", tool_name="n", ok=True, summary="s"),
            )
        ),
        WorkflowApprovalRequiredEvent(
            **_envelope_kwargs(
                "workflow.approval_required",
                # No `options=` here either -- proves the discriminated
                # union's own construction path tolerates the default too.
                WorkflowApprovalRequiredPayload(
                    tool_call_id="c",
                    tool_name="n",
                    proposed_change={"a": 1},
                    expires_at=NOW,
                ),
            )
        ),
        WorkflowCompletedEvent(
            **_envelope_kwargs(
                "workflow.completed",
                WorkflowCompletedPayload(stop_reason=StopReason.FINAL_RESPONSE),
            )
        ),
        WorkflowFailedEvent(
            **_envelope_kwargs(
                "workflow.failed",
                WorkflowFailedPayload(
                    status=WorkflowRunStatus.FAILED, stop_reason=StopReason.LLM_ERROR
                ),
            )
        ),
    ]
    assert len(samples) == 8
    for instance in samples:
        round_tripped: WorkflowRunEvent = WorkflowRunEventAdapter.validate_python(
            instance.model_dump(mode="json")
        )
        assert round_tripped.event_type == instance.event_type


# ---------------------------------------------------------------------------
# `workflow.failed` -- stop_reason restricted to the failure class, status
# must match ADR-073's mapping.
# ---------------------------------------------------------------------------


def test_workflow_failed_documents_exact_failure_class_members():
    assert {r.value for r in FAILURE_STOP_REASONS} == {
        "cancelled_by_seller",
        "confirmation_expired",
        "confirmation_diverged",
        "iteration_cap_exceeded",
        "wall_clock_timeout",
        "tool_error_unrecoverable",
        "llm_error",
        "concurrency_conflict",
        "output_validation_failed",
        "worker_lost",
        "prompt_version_unrecoverable",
    }


@pytest.mark.parametrize(
    "stop_reason,status",
    [
        (StopReason.CANCELLED_BY_SELLER, WorkflowRunStatus.CANCELLED),
        (StopReason.CONFIRMATION_EXPIRED, WorkflowRunStatus.CANCELLED),
        (StopReason.CONFIRMATION_DIVERGED, WorkflowRunStatus.FAILED),
        (StopReason.ITERATION_CAP_EXCEEDED, WorkflowRunStatus.TIMED_OUT),
        (StopReason.WALL_CLOCK_TIMEOUT, WorkflowRunStatus.TIMED_OUT),
        (StopReason.TOOL_ERROR_UNRECOVERABLE, WorkflowRunStatus.FAILED),
        (StopReason.LLM_ERROR, WorkflowRunStatus.FAILED),
        (StopReason.CONCURRENCY_CONFLICT, WorkflowRunStatus.FAILED),
        (StopReason.OUTPUT_VALIDATION_FAILED, WorkflowRunStatus.FAILED),
        (StopReason.WORKER_LOST, WorkflowRunStatus.FAILED),
        (StopReason.PROMPT_VERSION_UNRECOVERABLE, WorkflowRunStatus.FAILED),
    ],
)
def test_workflow_failed_accepts_every_failure_class_member_with_matching_status(
    stop_reason, status
):
    payload = WorkflowFailedPayload(status=status, stop_reason=stop_reason)
    assert payload.stop_reason == stop_reason
    assert payload.status == status


@pytest.mark.parametrize(
    "stop_reason",
    [StopReason.FINAL_RESPONSE, StopReason.CONFIRMATION_DECLINED],
)
def test_workflow_failed_rejects_completed_class_stop_reasons(stop_reason):
    with pytest.raises(ValidationError):
        WorkflowFailedPayload(status=WorkflowRunStatus.FAILED, stop_reason=stop_reason)


def test_workflow_failed_rejects_paused_for_confirmation():
    with pytest.raises(ValidationError):
        WorkflowFailedPayload(
            status=WorkflowRunStatus.FAILED, stop_reason=StopReason.PAUSED_FOR_CONFIRMATION
        )


def test_workflow_failed_rejects_status_mismatched_with_stop_reason():
    with pytest.raises(ValidationError):
        WorkflowFailedPayload(status=WorkflowRunStatus.CANCELLED, stop_reason=StopReason.LLM_ERROR)


# ---------------------------------------------------------------------------
# Module import: no side effects, no network access.
# ---------------------------------------------------------------------------


def test_events_package_importable_with_no_side_effects():
    import importlib

    import juli_backend.services.agent.events as events_pkg

    importlib.reload(events_pkg)
    assert hasattr(events_pkg, "EventSink")
    assert hasattr(events_pkg, "WorkflowRunEvent")
