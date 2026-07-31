"""Unit tests for CDP batch PartnerApiBudgetGovernor (#616 / CDP-A2-2).

PR-safe: no live Partner HTTP, Postgres I/O governor, or credentials.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from juli_backend.services.cdp_batch.partner_budget import (
    DEFER_REASON,
    PartnerBudgetStopReason,
    begin_partner_budget_run,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_MD = REPO_ROOT / "backend/src/juli_backend/services/cdp_batch/MODULE.md"
PARTNER_BUDGET_PATH = REPO_ROOT / "backend/src/juli_backend/services/cdp_batch/partner_budget.py"


def test_respects_soft_hard_caps_under_limit() -> None:
    gov = begin_partner_budget_run(max_attempts=5, hard_limit=8)

    for _ in range(4):
        assert gov.try_consume() is True

    assert gov.attempts == 4
    assert gov.should_defer() is False


def test_try_consume_defers_at_hard_cap() -> None:
    gov = begin_partner_budget_run(max_attempts=3, hard_limit=5)

    for _ in range(5):
        assert gov.try_consume() is True

    assert gov.try_consume() is False
    assert gov.attempts == 5


def test_should_defer_at_soft_cap() -> None:
    gov = begin_partner_budget_run(max_attempts=3, hard_limit=10)

    for _ in range(3):
        gov.try_consume()

    assert gov.should_defer() is True
    assert gov.try_consume() is True  # still under hard cap


def test_finish_partner_budget_exhausted_defers_partition() -> None:
    gov = begin_partner_budget_run(max_attempts=2, hard_limit=4)

    while gov.try_consume():
        pass

    fields = gov.finish(DEFER_REASON)

    assert gov.implies_partition_complete is False
    assert fields["stopped_reason"] == DEFER_REASON
    assert fields["defer_reason"] == DEFER_REASON
    assert fields["attempts"] == gov.attempts
    assert fields["successes"] == 0


def test_finish_complete_allows_partition_complete() -> None:
    gov = begin_partner_budget_run(max_attempts=5, hard_limit=8)
    gov.try_consume()
    gov.record_success()

    fields = gov.finish("complete")

    assert gov.implies_partition_complete is True
    assert fields["stopped_reason"] == "complete"
    assert fields["defer_reason"] is None
    assert fields["successes"] == 1


def test_structured_log_fields_never_include_secrets() -> None:
    gov = begin_partner_budget_run(max_attempts=2, hard_limit=3)
    gov.try_consume()
    gov.record_success()
    fields = gov.finish("complete")

    allowed_keys = {
        "attempts",
        "successes",
        "failures",
        "rate_limited",
        "stopped_reason",
        "defer_reason",
    }
    assert set(fields.keys()) == allowed_keys
    for value in fields.values():
        if isinstance(value, str):
            assert "token" not in value.lower()
            assert "secret" not in value.lower()


def test_begin_partner_budget_run_rejects_invalid_limits() -> None:
    with pytest.raises(ValueError, match="max_attempts must be positive"):
        begin_partner_budget_run(max_attempts=0)

    with pytest.raises(ValueError, match="hard_limit must be positive"):
        begin_partner_budget_run(hard_limit=0)

    with pytest.raises(ValueError, match="max_attempts must not exceed hard_limit"):
        begin_partner_budget_run(max_attempts=10, hard_limit=5)


def test_module_documents_dual_budget_separate_from_postgres_io() -> None:
    content = MODULE_MD.read_text(encoding="utf-8")
    assert "PartnerApiBudgetGovernor" in content
    assert "partner_budget_exhausted" in content
    assert "PostgresIoBudgetGovernor" in content


def test_partner_budget_module_exists() -> None:
    assert PARTNER_BUDGET_PATH.is_file()


def test_export_from_cdp_batch_package() -> None:
    from juli_backend.services import cdp_batch

    assert hasattr(cdp_batch, "PartnerApiBudgetGovernor")
    assert hasattr(cdp_batch, "begin_partner_budget_run")
    assert cdp_batch.DEFER_REASON == DEFER_REASON


def test_partner_budget_stop_reason_type() -> None:
    reason: PartnerBudgetStopReason = DEFER_REASON
    assert reason == "partner_budget_exhausted"
