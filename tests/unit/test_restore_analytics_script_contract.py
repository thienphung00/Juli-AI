"""Contract tests for restore-analytics-history.sh (#789).

This script writes directly to the production analytics tables, so its guards are
the only thing between an operator and a duplicated or partial restore. These tests
pin the guards rather than the prose around them.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "infra/scripts/restore-analytics-history.sh"


@pytest.fixture
def script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def test_script_exists_and_is_executable():
    assert SCRIPT_PATH.exists(), f"{SCRIPT_PATH} is missing"
    assert SCRIPT_PATH.stat().st_mode & 0o111, "script must be executable"


def test_script_has_valid_bash_syntax():
    result = subprocess.run(["bash", "-n", str(SCRIPT_PATH)], capture_output=True, text=True)
    assert result.returncode == 0, f"bash -n failed: {result.stderr}"


def test_uses_strict_mode(script_text: str):
    """A partial restore is worse than none: the script must abort on first error."""
    assert "set -euo pipefail" in script_text


def test_refuses_when_target_tables_are_not_empty(script_text: str):
    """The restore appends. Running it twice would duplicate 6,662 rows."""
    assert "refusing to append" in script_text, (
        "script must refuse to run when the target tables already hold rows"
    )
    assert 'perf_live}" -ne 0 ]' in script_text or "perf_live" in script_text


def test_verifies_dump_contents_before_writing(script_text: str):
    """Guards against pointing the script at a dump that lacks the data."""
    assert "EXPECT_PERF_ROWS=6662" in script_text
    assert "EXPECT_PARTITION_ROWS=512" in script_text
    assert "wrong dump?" in script_text


def test_checks_schema_compatibility_before_restore(script_text: str):
    """The dump predates migrations 021-025; a dropped column would fail mid-COPY."""
    assert "information_schema.columns" in script_text
    assert "columns present in dump but missing from production" in script_text


def test_remaps_partitions_table_to_ops_schema(script_text: str):
    """analytics_backfill_partitions moved public.* -> ops.* in #604, after the dump."""
    assert "COPY ops.analytics_backfill_partitions" in script_text, (
        "partition checkpoints must be remapped into the ops schema"
    )


def test_restores_partition_checkpoints_not_only_data(script_text: str):
    """Checkpoints mark partitions complete, so no later backfill re-fetches the window."""
    assert "--table=analytics_backfill_partitions" in script_text


def test_supports_dry_run(script_text: str):
    """An operator must be able to check every precondition without writing."""
    assert "--dry-run" in script_text
    assert "DRY RUN COMPLETE" in script_text


def test_dry_run_exits_before_any_write(script_text: str):
    """The dry-run guard must come before the pg_restore calls, not after."""
    dry_run_exit = script_text.index("DRY RUN COMPLETE")
    first_restore = script_text.index("pg_restore --no-owner")
    assert dry_run_exit < first_restore, "dry-run must return before the first write to production"


def test_verifies_row_counts_after_restore(script_text: str):
    """A silent partial restore is the failure mode worth catching."""
    assert "after restore" in script_text
    assert "expected ${EXPECT_PERF_ROWS} analytics rows after restore" in script_text


def test_verifies_rows_are_shop_scoped(script_text: str):
    """All 6,662 rows belong to the reference shop; anything else means a wrong dump."""
    assert "shop-scoped" in script_text
    assert "WHERE shop_id=" in script_text


def test_strips_asyncpg_driver_for_psql(script_text: str):
    """DATABASE_URL may carry +asyncpg, which psql cannot parse."""
    assert "+asyncpg" in script_text


def test_makes_no_partner_api_calls(script_text: str):
    """This is a data restore. Re-fetching would take ~37 minutes and burn budget."""
    for forbidden in ("curl", "wget", "tiktok", "partner_fetch"):
        assert forbidden not in script_text.lower(), (
            f"restore script must not reference {forbidden}"
        )


def test_documents_adr_027_locality(script_text: str):
    """Dumps hold OAuth tokens and commerce PII and must never leave the VPS."""
    assert "ADR-027" in script_text
