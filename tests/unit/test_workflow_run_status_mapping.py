"""`WorkflowRunStatus`/`StopReason` vocabulary and the TOTAL mapping between
them — ADR-073 decision 2, plus the 2026-08-12 `worker_lost` amendment
(ADR-074). Issue #1117 / AGT-W3A.

Pure-Python, no database needed: this slice ships vocabulary and a mapping
dict, not runner logic.
"""

from __future__ import annotations

from pathlib import Path

from juli_backend.services.agent.runner.status import (
    NON_TERMINAL_STATUSES,
    STOP_REASON_TO_STATUS,
    StopReason,
    WorkflowRunStatus,
    status_for,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PACKAGE_DIR = REPO_ROOT / "backend/src/juli_backend/services/agent/runner"


def test_workflow_run_status_has_exactly_seven_members():
    """ADR-073 amends ADR-068's original eight states by dropping `created` —
    a run row is only ever inserted already `queued`. Exactly these seven,
    no more, no fewer."""
    expected = {
        "queued",
        "running",
        "waiting_approval",
        "completed",
        "cancelled",
        "timed_out",
        "failed",
    }
    actual = {member.value for member in WorkflowRunStatus}
    assert actual == expected


def test_stop_reason_has_exactly_twelve_members():
    """The full vocabulary named in ADR-073 decision 2 plus the
    `output_validation_failed` P7 reservation and the `worker_lost`
    ADR-074 amendment."""
    expected = {
        "final_response",
        "confirmation_declined",
        "paused_for_confirmation",
        "cancelled_by_seller",
        "confirmation_expired",
        "iteration_cap_exceeded",
        "wall_clock_timeout",
        "tool_error_unrecoverable",
        "llm_error",
        "concurrency_conflict",
        "output_validation_failed",
        "worker_lost",
    }
    actual = {member.value for member in StopReason}
    assert actual == expected


def test_mapping_is_total_over_every_stop_reason():
    """Every `StopReason` member must be a key in `STOP_REASON_TO_STATUS` —
    an unmapped stop_reason is exactly the "silent exit" ADR-073 decision 2
    forbids. Fails loudly (not a KeyError deep in runner code) if a member
    is ever added to the enum without a matching mapping entry."""
    unmapped = [reason for reason in StopReason if reason not in STOP_REASON_TO_STATUS]
    assert not unmapped, f"StopReason members with no WorkflowRunStatus mapping: {unmapped}"

    # And nothing extra: the mapping's domain is EXACTLY StopReason, not a
    # superset that could hide a stale/renamed key.
    assert set(STOP_REASON_TO_STATUS.keys()) == set(StopReason)


def test_mapping_values_are_all_valid_statuses():
    """Every mapped value really is a `WorkflowRunStatus` member — guards
    against a typo'd/stale status slipping into the mapping table."""
    for status in STOP_REASON_TO_STATUS.values():
        assert isinstance(status, WorkflowRunStatus)
        assert status in WorkflowRunStatus


def test_mapping_reproduces_adr073_decision2_table_exactly():
    """The exact stop_reason -> status table from ADR-073 decision 2, plus
    the worker_lost amendment row. A change to any single row here is a
    change to the ADR-authored contract, not a refactor."""
    expected = {
        StopReason.FINAL_RESPONSE: WorkflowRunStatus.COMPLETED,
        StopReason.CONFIRMATION_DECLINED: WorkflowRunStatus.COMPLETED,
        StopReason.PAUSED_FOR_CONFIRMATION: WorkflowRunStatus.WAITING_APPROVAL,
        StopReason.CANCELLED_BY_SELLER: WorkflowRunStatus.CANCELLED,
        StopReason.CONFIRMATION_EXPIRED: WorkflowRunStatus.CANCELLED,
        StopReason.ITERATION_CAP_EXCEEDED: WorkflowRunStatus.TIMED_OUT,
        StopReason.WALL_CLOCK_TIMEOUT: WorkflowRunStatus.TIMED_OUT,
        StopReason.TOOL_ERROR_UNRECOVERABLE: WorkflowRunStatus.FAILED,
        StopReason.LLM_ERROR: WorkflowRunStatus.FAILED,
        StopReason.CONCURRENCY_CONFLICT: WorkflowRunStatus.FAILED,
        StopReason.OUTPUT_VALIDATION_FAILED: WorkflowRunStatus.FAILED,
        StopReason.WORKER_LOST: WorkflowRunStatus.FAILED,
    }
    assert dict(STOP_REASON_TO_STATUS) == expected


def test_status_for_matches_the_mapping_dict():
    for reason, status in STOP_REASON_TO_STATUS.items():
        assert status_for(reason) == status


def test_mapping_is_total_onto_every_terminal_status_reverse_direction():
    """Reverse totality: every `WorkflowRunStatus` member EXCEPT `queued` and
    `running` must have at least one `StopReason` mapping to it.

    `queued`/`running` are structurally excluded, not overlooked: a
    `stop_reason` records how a loop ENDED, and a run occupies `queued`/
    `running` only *before* any iteration has stopped -- no `stop_reason` can
    ever target them by definition. `NON_TERMINAL_STATUSES` names exactly
    that exception set, and this test pins it to exactly `{queued, running}`
    so a real regression (e.g. `failed` losing every mapped reason) cannot
    hide behind a silently-widened exception set.
    """
    assert NON_TERMINAL_STATUSES == {WorkflowRunStatus.QUEUED, WorkflowRunStatus.RUNNING}

    covered_statuses = set(STOP_REASON_TO_STATUS.values())
    statuses_needing_coverage = set(WorkflowRunStatus) - NON_TERMINAL_STATUSES

    uncovered = statuses_needing_coverage - covered_statuses
    assert not uncovered, (
        f"WorkflowRunStatus members with zero stop_reason mapping to them "
        f"(and not in NON_TERMINAL_STATUSES): {uncovered}"
    )

    # And every non-terminal status genuinely has zero -- if one gained a
    # mapping, NON_TERMINAL_STATUSES would need updating deliberately.
    for status in NON_TERMINAL_STATUSES:
        assert status not in covered_statuses


def test_output_validation_failed_is_present_and_mapped_to_failed():
    """Reserved for P7 (ADR-073 decision 5): present in the enum, mapped now
    so P7 adds no new vocabulary, but unreachable until P7 ships."""
    assert StopReason.OUTPUT_VALIDATION_FAILED in StopReason
    assert STOP_REASON_TO_STATUS[StopReason.OUTPUT_VALIDATION_FAILED] == WorkflowRunStatus.FAILED


def test_output_validation_failed_has_no_producer_in_the_runner_package():
    """P7 deferral discipline: no code in this slice (or any slice landed so
    far) may construct `StopReason.OUTPUT_VALIDATION_FAILED` / the string
    `"output_validation_failed"` outside of `status.py`'s enum definition and
    mapping table. This walks every `.py` file under
    `services/agent/runner/` at test-run time (not a hardcoded file list), so
    it keeps guarding the P7 deferral as later slices add modules to that
    package.
    """
    assert RUNNER_PACKAGE_DIR.is_dir(), f"runner package not found at {RUNNER_PACKAGE_DIR}"

    offending: list[str] = []
    for path in sorted(RUNNER_PACKAGE_DIR.rglob("*.py")):
        if path.name == "status.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "output_validation_failed" in text.lower():
            offending.append(str(path))

    assert not offending, (
        "OUTPUT_VALIDATION_FAILED must stay reserved for P7 -- found a reference "
        f"outside status.py: {offending}"
    )
