"""Unit tests for CDP batch PostgresIoBudgetGovernor (#617 / CDP-A2-3).

PR-safe: no live Supabase, Partner HTTP, or credentials.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from juli_backend.services.cdp_batch.postgres_io_budget import (
    DEFER_REASON,
    PostgresIoBudgetStopReason,
    begin_postgres_io_budget_run,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_MD = REPO_ROOT / "backend/src/juli_backend/services/cdp_batch/MODULE.md"
POSTGRES_IO_BUDGET_PATH = (
    REPO_ROOT / "backend/src/juli_backend/services/cdp_batch/postgres_io_budget.py"
)
PARTNER_BUDGET_PATH = REPO_ROOT / "backend/src/juli_backend/services/cdp_batch/partner_budget.py"


def test_bronze_flush_under_cap_proceeds() -> None:
    gov = begin_postgres_io_budget_run(
        bronze_rows_per_flush=100,
        silver_upsert_batch_size=50,
        max_concurrent_shops=5,
    )

    assert gov.try_bronze_flush(100) is True
    assert gov.should_defer() is False
    assert gov.last_bronze_flush_size == 100


def test_bronze_flush_over_cap_defers() -> None:
    gov = begin_postgres_io_budget_run(bronze_rows_per_flush=100)

    assert gov.try_bronze_flush(101) is False
    assert gov.should_defer() is True


def test_silver_upsert_under_cap_proceeds() -> None:
    gov = begin_postgres_io_budget_run(silver_upsert_batch_size=50)

    assert gov.try_silver_upsert(50) is True
    assert gov.should_defer() is False
    assert gov.last_silver_batch_size == 50


def test_silver_upsert_over_cap_defers() -> None:
    gov = begin_postgres_io_budget_run(silver_upsert_batch_size=50)

    assert gov.try_silver_upsert(51) is False
    assert gov.should_defer() is True


def test_concurrent_shop_acquire_and_release() -> None:
    gov = begin_postgres_io_budget_run(max_concurrent_shops=2)

    assert gov.try_acquire_shop() is True
    assert gov.try_acquire_shop() is True
    assert gov.concurrent_shop_count == 2
    assert gov.try_acquire_shop() is False
    assert gov.should_defer() is True

    gov.release_shop()
    assert gov.concurrent_shop_count == 1
    assert gov.try_acquire_shop() is True


def test_finish_postgres_io_throttled_defers_partition() -> None:
    gov = begin_postgres_io_budget_run(bronze_rows_per_flush=10)
    gov.try_bronze_flush(20)

    fields = gov.finish(DEFER_REASON)

    assert gov.implies_partition_complete is False
    assert fields["stopped_reason"] == DEFER_REASON
    assert fields["defer_reason"] == DEFER_REASON
    assert fields["batch_postgres_io_deferred_total"] >= 1


def test_finish_complete_allows_partition_complete() -> None:
    gov = begin_postgres_io_budget_run(bronze_rows_per_flush=100)
    gov.try_bronze_flush(50)
    gov.try_silver_upsert(10)
    gov.try_acquire_shop()

    fields = gov.finish("complete")

    assert gov.implies_partition_complete is True
    assert fields["stopped_reason"] == "complete"
    assert fields["defer_reason"] is None
    assert fields["bronze_flush_size"] == 50
    assert fields["silver_batch_size"] == 10
    assert fields["concurrent_shop_count"] == 1


def test_structured_log_metrics_bronze_silver_concurrent_no_tokens() -> None:
    gov = begin_postgres_io_budget_run()
    gov.try_bronze_flush(10)
    fields = gov.finish("complete")

    allowed_keys = {
        "bronze_flush_size",
        "silver_batch_size",
        "concurrent_shop_count",
        "batch_postgres_io_deferred_total",
        "stopped_reason",
        "defer_reason",
    }
    assert set(fields.keys()) == allowed_keys
    for value in fields.values():
        if isinstance(value, str):
            assert "token" not in value.lower()
            assert "secret" not in value.lower()


def test_begin_postgres_io_budget_run_rejects_invalid_limits() -> None:
    with pytest.raises(ValueError, match="bronze_rows_per_flush must be positive"):
        begin_postgres_io_budget_run(bronze_rows_per_flush=0)

    with pytest.raises(ValueError, match="silver_upsert_batch_size must be positive"):
        begin_postgres_io_budget_run(silver_upsert_batch_size=0)

    with pytest.raises(ValueError, match="max_concurrent_shops must be positive"):
        begin_postgres_io_budget_run(max_concurrent_shops=0)


def test_try_bronze_flush_rejects_non_positive_row_count() -> None:
    gov = begin_postgres_io_budget_run()
    with pytest.raises(ValueError, match="row_count must be positive"):
        gov.try_bronze_flush(0)


def test_try_silver_upsert_rejects_non_positive_row_count() -> None:
    gov = begin_postgres_io_budget_run()
    with pytest.raises(ValueError, match="row_count must be positive"):
        gov.try_silver_upsert(0)


def test_independent_from_partner_budget() -> None:
    """Partner and Postgres I/O governors are separate modules — dual budget."""
    from juli_backend.services.cdp_batch import partner_budget

    assert partner_budget.DEFER_REASON == "partner_budget_exhausted"
    assert DEFER_REASON == "postgres_io_throttled"
    assert partner_budget.DEFER_REASON != DEFER_REASON


def test_module_documents_dual_budget_partner_alone_insufficient() -> None:
    content = MODULE_MD.read_text(encoding="utf-8")
    assert "PostgresIoBudgetGovernor" in content
    assert "postgres_io_throttled" in content
    assert "PartnerApiBudgetGovernor" in content
    assert "partner_budget_exhausted" in content
    assert "dual budget" in content.lower() or "orthogonal" in content.lower()
    assert "insufficient" in content.lower() or "not sufficient" in content.lower()


def test_postgres_io_budget_module_exists() -> None:
    assert POSTGRES_IO_BUDGET_PATH.is_file()


def test_export_from_cdp_batch_package() -> None:
    from juli_backend.services import cdp_batch

    assert hasattr(cdp_batch, "PostgresIoBudgetGovernor")
    assert hasattr(cdp_batch, "begin_postgres_io_budget_run")
    assert cdp_batch.POSTGRES_IO_DEFER_REASON == DEFER_REASON


def test_postgres_io_budget_stop_reason_type() -> None:
    reason: PostgresIoBudgetStopReason = DEFER_REASON
    assert reason == "postgres_io_throttled"


def test_partner_only_budget_without_io_governor_insufficient_for_a2_exit() -> None:
    """Negative AC: Partner-only budget does not satisfy A2 dual-budget exit."""
    partner_content = PARTNER_BUDGET_PATH.read_text(encoding="utf-8")
    module_content = MODULE_MD.read_text(encoding="utf-8")

    assert "PostgresIoBudgetGovernor" in partner_content
    assert POSTGRES_IO_BUDGET_PATH.is_file()
    assert "Partner-only" in module_content or "partner-only" in module_content.lower()
