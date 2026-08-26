"""`WorkflowRunStatus`/`StopReason` vocabulary and the TOTAL mapping between
them — ADR-073 decision 2, plus the 2026-08-12 `worker_lost` amendment
(ADR-074). Issue #1117 / AGT-W3A.

Pure-Python, no database needed: this slice ships vocabulary and a mapping
dict, not runner logic.

The vocabulary itself relocated from `services/agent/runner/status.py` to
`services/agent/status.py` in #1139 (AGT-W3A) -- a neutral leaf module both
`runner` and `events` import directly, eliminating the import-cycle hazard
that used to require a lazy `__getattr__` workaround in
`runner/__init__.py`. This test file's assertions about the vocabulary and
mapping are unchanged; only the import path moved.
"""

from __future__ import annotations

from pathlib import Path

from juli_backend.services.agent.status import (
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


def test_stop_reason_has_exactly_sixteen_members():
    """The full vocabulary named in ADR-073 decision 2 plus the
    `output_validation_failed` P7 reservation, the `worker_lost` ADR-074
    amendment, the `confirmation_diverged` ADR-075 decision 2 / #1224
    review round 3 amendment, the `prompt_version_unrecoverable`
    #1359 amendment (fail-closed resume when stored prompt version is
    missing or unparseable), and the `concluded_without_changes` and
    `required_steps_unfulfilled` #1373 amendments (ADR-088 consent pause
    guarantee)."""
    expected = {
        "final_response",
        "confirmation_declined",
        "paused_for_confirmation",
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
        "concluded_without_changes",
        "required_steps_unfulfilled",
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
    the worker_lost and confirmation_diverged amendment rows, plus the
    prompt_version_unrecoverable amendment row (#1359), plus the
    concluded_without_changes and required_steps_unfulfilled amendment rows
    (#1373, ADR-088). A change to any single row here is a change to the
    ADR-authored contract, not a refactor."""
    expected = {
        StopReason.FINAL_RESPONSE: WorkflowRunStatus.COMPLETED,
        StopReason.CONFIRMATION_DECLINED: WorkflowRunStatus.COMPLETED,
        StopReason.CONCLUDED_WITHOUT_CHANGES: WorkflowRunStatus.COMPLETED,
        StopReason.PAUSED_FOR_CONFIRMATION: WorkflowRunStatus.WAITING_APPROVAL,
        StopReason.CANCELLED_BY_SELLER: WorkflowRunStatus.CANCELLED,
        StopReason.CONFIRMATION_EXPIRED: WorkflowRunStatus.CANCELLED,
        StopReason.CONFIRMATION_DIVERGED: WorkflowRunStatus.FAILED,
        StopReason.ITERATION_CAP_EXCEEDED: WorkflowRunStatus.TIMED_OUT,
        StopReason.WALL_CLOCK_TIMEOUT: WorkflowRunStatus.TIMED_OUT,
        StopReason.TOOL_ERROR_UNRECOVERABLE: WorkflowRunStatus.FAILED,
        StopReason.LLM_ERROR: WorkflowRunStatus.FAILED,
        StopReason.CONCURRENCY_CONFLICT: WorkflowRunStatus.FAILED,
        StopReason.OUTPUT_VALIDATION_FAILED: WorkflowRunStatus.FAILED,
        StopReason.WORKER_LOST: WorkflowRunStatus.FAILED,
        StopReason.PROMPT_VERSION_UNRECOVERABLE: WorkflowRunStatus.FAILED,
        StopReason.REQUIRED_STEPS_UNFULFILLED: WorkflowRunStatus.FAILED,
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


def test_confirmation_diverged_is_present_and_mapped_to_failed():
    """ADR-073 amendment (ADR-075 decision 2, #1224 review round 3): a
    dedicated member for consent-binding refusal, distinct in kind from
    `CONCURRENCY_CONFLICT` even though both are compare-before-write guards
    -- the execution-quality metric this vocabulary feeds must be able to
    tell "a seller edited concurrently" apart from "consent binding refused
    an unconsented write"."""
    assert StopReason.CONFIRMATION_DIVERGED in StopReason
    assert StopReason.CONFIRMATION_DIVERGED.value == "confirmation_diverged"
    assert len(StopReason.CONFIRMATION_DIVERGED.value) <= 32, (
        "workflow_runs.stop_reason is String(32) -- a longer value fails at "
        "write time against a real database and passes every SQLite test"
    )
    assert STOP_REASON_TO_STATUS[StopReason.CONFIRMATION_DIVERGED] == WorkflowRunStatus.FAILED


def test_confirmation_diverged_is_produced_only_by_the_resume_consent_check():
    """Exactly ONE producer, same discipline as
    `test_output_validation_failed_is_produced_only_by_the_outbound_guard`:
    `WorkflowRunner.resume`'s approve branch, immediately before
    `ToolExecutor.execute` (#1224 review round 3). Walks every `.py` file
    under `services/agent/runner/` at test-run time, so it keeps guarding
    as later slices add modules to that package."""
    assert RUNNER_PACKAGE_DIR.is_dir(), f"runner package not found at {RUNNER_PACKAGE_DIR}"

    offending: list[str] = []
    for path in sorted(RUNNER_PACKAGE_DIR.rglob("*.py")):
        if path.name == "core.py":
            occurrences = path.read_text(encoding="utf-8").count("CONFIRMATION_DIVERGED")
            assert occurrences == 1, (
                f"core.py references CONFIRMATION_DIVERGED {occurrences} times; "
                "exactly one producer (resume()'s consent-binding check) is sanctioned"
            )
            continue
        text = path.read_text(encoding="utf-8")
        if "confirmation_diverged" in text.lower():
            offending.append(str(path))

    assert not offending, (
        "CONFIRMATION_DIVERGED must be produced only by WorkflowRunner.resume -- found a "
        f"reference outside core.py: {offending}"
    )


def test_output_validation_failed_is_produced_only_by_the_outbound_guard():
    """#1210 gave this stop_reason its first legitimate producer.

    It was reserved for P7 and deliberately unreachable. The outbound
    banned-pattern guard now terminates with it, because a guard hit is a known
    outcome: letting it escape left the row non-terminal and the reaper stamped
    `worker_lost`, which was false.

    Issue #1225 (AGT-W5A) review round 2 added the SECOND, identical
    producer, in the same file: `WorkflowRunner.resume`'s decline branch
    now gives the model one closing turn (`_closing_turn_after_decline`),
    which reaches the exact same `guard_outbound_agent_output` chokepoint
    `_finalize` already wraps -- and must translate a hit through this same
    terminal member for the identical reason #1210 exists at all (an
    uncaught hit here would strand the row `RUNNING`, #1181's
    entry-transition persist, for the reaper to mislabel `worker_lost`).
    Both call sites are literally "the outbound guard translation", never a
    producer unrelated to the guard -- the discipline is unchanged in
    substance: a NAMED, FIXED count of sanctioned producers. A third one
    appearing without a decision is still a failure.

    This walks every `.py` file under `services/agent/runner/` at test-run
    time (not a hardcoded file list), so it keeps guarding as later slices
    add modules to that package. The vocabulary module itself (`status.py`,
    which legitimately references `OUTPUT_VALIDATION_FAILED` in its mapping
    table) moved to `services/agent/status.py` in #1139 -- outside this
    walked directory -- so no exemption for it is needed here anymore.
    """
    assert RUNNER_PACKAGE_DIR.is_dir(), f"runner package not found at {RUNNER_PACKAGE_DIR}"

    # The exact code pattern a producer call site uses -- `StopReason
    # .OUTPUT_VALIDATION_FAILED` as a positional argument to `_terminate(...)`
    # -- not a blanket substring search, so prose/docstring mentions (this
    # test's own module included, and core.py's own explanatory comments)
    # never inflate the count.
    producer_pattern = "StopReason.OUTPUT_VALIDATION_FAILED,"

    offending: list[str] = []
    for path in sorted(RUNNER_PACKAGE_DIR.rglob("*.py")):
        # #1210 + #1225: core.py's `_finalize` and `resume()`'s decline
        # branch are the TWO sanctioned producers, both translating the same
        # guard hit. Counted rather than skipped -- a blanket exemption
        # would let an unrelated third producer appear in the same file
        # unnoticed, which is the discipline this test exists to keep.
        if path.name == "core.py":
            occurrences = path.read_text(encoding="utf-8").count(producer_pattern)
            assert occurrences == 2, (
                f"core.py has {occurrences} OUTPUT_VALIDATION_FAILED producer call sites; "
                "exactly two are sanctioned (_finalize and resume()'s decline branch, "
                "both translating the same outbound guard hit)"
            )
            continue
        text = path.read_text(encoding="utf-8")
        if "output_validation_failed" in text.lower():
            offending.append(str(path))

    assert not offending, (
        "OUTPUT_VALIDATION_FAILED must stay reserved for P7 -- found a reference "
        f"outside status.py: {offending}"
    )
