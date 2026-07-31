"""Issue #624 — CDP-A2-6 read-replica isolation documentation contract tests.

AC1 → replica isolation deferred to 3.5-C; A2 batch exit does not require replica infra
AC2 → batch stages document replica reads vs primary writes when implemented
AC3 → cross-links #602 US #14 and ADR-047 Batch layer boundary
AC4 → no infrastructure provisioning — documentation only
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "backend/src/juli_backend/services/cdp_batch/MODULE.md"
ADR_050_PATH = REPO_ROOT / "docs/adr/050-cdp-slice-3-5-c-two-gated-exits.md"
ADR_047_PATH = REPO_ROOT / "docs/adr/047-cdp-lambda-layers-prd-split.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_replica_isolation_deferred_to_3_5_c_not_a2_exit_gate() -> None:
    """AC1: MODULE and ADR state replica isolation is 3.5-C deferred — not A2 exit gate."""
    module = _read(MODULE_PATH)
    adr = _read(ADR_050_PATH)
    adr_plain = adr.replace("**", "")

    assert "Read-replica isolation (3.5-C deferred)" in module
    assert "Not an A2 exit gate" in module
    assert "3.5-C C2" in module
    assert "primary postgres" in module.lower()

    assert "Read-replica isolation (C2 infrastructure — deferred from A2)" in adr
    assert "not an A2 Batch exit gate" in adr_plain
    assert "documentation only" in adr.lower()


def test_batch_stages_document_replica_reads_vs_primary_writes() -> None:
    """AC2: Docs map batch stages to replica reads vs primary writes when implemented."""
    module = _read(MODULE_PATH)
    adr = _read(ADR_050_PATH)

    for text in (module, adr):
        assert "Replica read" in text
        assert "Primary write" in text
        assert "BatchFetchPlanner" in text
        assert "gold.kpi_envelopes" in text
        assert "ops.*" in text or "`ops.*`" in text


def test_cross_links_issue_602_us_14_and_adr_047_batch_layer() -> None:
    """AC3: Cross-links parent #602 US #14 and ADR-047 Batch layer boundary."""
    module = _read(MODULE_PATH)
    adr_050 = _read(ADR_050_PATH)
    adr_047 = _read(ADR_047_PATH)

    assert "issues/602" in module
    assert "US #14" in module
    assert "047-cdp-lambda-layers-prd-split.md" in module

    assert "issues/602" in adr_050
    assert "US #14" in adr_050
    assert "047-cdp-lambda-layers-prd-split.md" in adr_050

    assert "Read-replica isolation" in adr_047
    assert "not an A2 exit" in adr_047


def test_no_infrastructure_provisioning_documentation_only() -> None:
    """AC4: Slice documents routing only — no infra provisioning or pool wiring."""
    module = _read(MODULE_PATH)
    adr = _read(ADR_050_PATH)

    assert "documentation only" in module.lower()
    assert "No connection-pool or Supabase replica wiring in A2" in module
    assert "documentation only" in adr.lower()
    assert "no replica provisioning" in adr.lower()
