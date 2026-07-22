"""Unit tests for analytics backfill Partner call-budget governor (#465)."""

from __future__ import annotations

import pytest

from juli_backend.services.analytics_backfill.budget import (
    BudgetExhaustedError,
    begin_run,
)


def test_should_stop_after_soft_cap_attempts():
    budget = begin_run(max_attempts=5, hard_limit=9)

    for _ in range(5):
        assert budget.should_stop() is False
        budget.record_attempt()

    assert budget.should_stop() is True
    assert budget.remaining() == 0


def test_record_attempt_refuses_at_hard_limit():
    budget = begin_run(max_attempts=3, hard_limit=4)

    for _ in range(4):
        budget.record_attempt()

    with pytest.raises(BudgetExhaustedError):
        budget.record_attempt()

    assert budget.attempts == 4


def test_hard_stop_prevents_reaching_five_hundred_attempts():
    budget = begin_run(max_attempts=400, hard_limit=499)

    for _ in range(499):
        budget.record_attempt()

    with pytest.raises(BudgetExhaustedError):
        budget.record_attempt()

    assert budget.attempts == 499


def test_budget_exhaust_does_not_imply_partition_complete():
    budget = begin_run(max_attempts=2, hard_limit=3)

    for _ in range(3):
        budget.record_attempt()

    fields = budget.finish("budget")

    assert budget.implies_partition_complete is False
    assert fields["stopped_reason"] == "budget"


def test_transient_failure_retry_increments_attempt_counter():
    budget = begin_run(max_attempts=10, hard_limit=10)

    budget.record_attempt()
    budget.record_failure()
    budget.record_attempt()
    budget.record_failure()

    assert budget.attempts == 2
    assert budget.failures == 2
    assert budget.successes == 0


def test_structured_log_fields_include_outcome_counters():
    budget = begin_run(max_attempts=5, hard_limit=8)

    budget.record_attempt()
    budget.record_success()
    budget.record_attempt()
    budget.record_rate_limited()
    budget.record_attempt()
    budget.record_failure()

    fields = budget.finish("complete")

    assert fields == {
        "attempts": 3,
        "successes": 1,
        "failures": 1,
        "rate_limited": 1,
        "stopped_reason": "complete",
    }


def test_begin_run_uses_adr_defaults():
    budget = begin_run()

    assert budget.max_attempts == 400
    assert budget.hard_limit == 499
