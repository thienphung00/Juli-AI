"""Medallion one-writer ownership — static map + call-site enforcement (#608)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(CI_DIR))

from medallion_one_writer import (  # noqa: E402
    DATABASE_MODULE_MD,
    ETL_MODULE_MD,
    MEDALLION_WRITE_RULES,
    scan_medallion_write_violations,
    validate_medallion_one_writer,
    validate_module_docs,
)


def test_canonical_map_covers_post_cutover_tables() -> None:
    tables = {rule.table for rule in MEDALLION_WRITE_RULES}
    assert "silver.orders" in tables
    assert "silver.returns" in tables
    assert "gold.kpi_envelopes" in tables
    assert "ops.analytics_backfill_partitions" in tables
    bronze_tables = {rule.table for rule in MEDALLION_WRITE_RULES if rule.layer == "bronze"}
    assert any("bronze.order_raw_payloads" in t for t in bronze_tables)
    assert "bronze.return_raw_payloads" in bronze_tables


def test_module_docs_contain_one_writer_map() -> None:
    assert validate_module_docs() == []


def test_q4_orchestrator_stages_documented_for_a1_handoff() -> None:
    """AC3: Q4 stages documented for A1; no material webhook path required in A0."""
    assert validate_module_docs() == []
    db_text = DATABASE_MODULE_MD.read_text(encoding="utf-8").lower()
    assert "orchestrator" in db_text
    assert "bronze" in db_text and "silver" in db_text and "gold" in db_text
    assert "webhook" in db_text or "material" in db_text or "a1" in db_text


def test_database_module_md_lists_owning_modules() -> None:
    text = DATABASE_MODULE_MD.read_text(encoding="utf-8")
    for label in (
        "Ingest / ETL bronze writer",
        "Domain silver upsert service",
        "Shared Compute",
        "Backfill / batch partition repo",
    ):
        assert label in text


def test_etl_module_md_cross_links_database_map() -> None:
    text = ETL_MODULE_MD.read_text(encoding="utf-8")
    assert "database/MODULE.md" in text
    assert "bronze" in text.lower()
    assert "silver" in text.lower()
    assert "gold" in text.lower()


def test_a0_exit_satisfied_after_silver_and_gold_cutovers() -> None:
    """Post-cutover production tree must have exactly the allowed writers."""
    violations = scan_medallion_write_violations()
    assert violations == [], "unexpected dual-write call sites:\n" + "\n".join(violations)


def test_ownership_fails_when_second_module_writes_owned_table() -> None:
    synthetic = """
from juli_backend.repositories.repos import OrdersRepo

async def rogue_write(session):
    repo = OrdersRepo(session)
    await repo.upsert(shop_id=shop_id, tiktok_order_id="x", status="OPEN")
"""
    violations = scan_medallion_write_violations(
        extra_sources={"juli_backend.services.aggregates.rogue": synthetic},
    )
    assert any("OrdersRepo.upsert" in v for v in violations)
    assert any("juli_backend.services.aggregates.rogue" in v for v in violations)


def test_synthetic_allowed_etl_silver_writer_passes() -> None:
    synthetic = """
from juli_backend.repositories.repos import OrdersRepo

class Promoter:
    def __init__(self, session):
        self._orders = OrdersRepo(session)

    async def promote(self, shop_id, kwargs):
        await self._orders.upsert(shop_id=shop_id, **kwargs)
"""
    violations = scan_medallion_write_violations(
        extra_sources={"juli_backend.services.etl.synthetic_promoter": synthetic},
    )
    assert violations == []


def test_validate_cli_prefix() -> None:
    import subprocess

    result = subprocess.run(
        [sys.executable, str(CI_DIR / "medallion_one_writer.py")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "medallion_one_writer: PASS" in result.stdout


def test_map_invariant_fails_when_second_gold_writer_added() -> None:
    """Negative-path: extra allowed prefix must be explicit — not silently widened."""
    gold_rules = [r for r in MEDALLION_WRITE_RULES if r.layer == "gold"]
    assert gold_rules
    for rule in gold_rules:
        assert "juli_backend.services.analytics_kpi_cache" not in rule.allowed_module_prefixes


def test_full_validator_passes() -> None:
    assert validate_medallion_one_writer() == []
