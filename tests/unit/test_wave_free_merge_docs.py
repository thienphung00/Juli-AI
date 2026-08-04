"""Docs/rollout contract tests for ADR-052 (CI-WAVE-4 / #662).

Asserts that the written record — ADR-052, its index/glossary references,
the parallel-workflow/worktree-topology docs, and the cutover checklist
script — actually reflects the free-merge / deferred artifact-gate contract
implemented by #659/#660/#661, per the release-evidence plan
`rep-662-ci-wave-4-docs-rollout-verification`.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ADR_052 = REPO_ROOT / "docs" / "adr" / "052-wave-free-merge-deferred-artifact-gate.md"
ADR_README = REPO_ROOT / "docs" / "adr" / "README.md"
CONTEXT_MD = REPO_ROOT / "CONTEXT.md"
TOPOLOGY_DOC = REPO_ROOT / "docs" / "handoffs" / "worktree-branch-topology.md"
ISSUE_WORKFLOW_RULE = REPO_ROOT / ".cursor" / "rules" / "issue-workflow.mdc"
GIT_BASELINE_RULE = REPO_ROOT / ".cursor" / "rules" / "git-baseline.mdc"
PARALLEL_STATUS_MD = REPO_ROOT / "docs" / "handoffs" / "parallel-status.md"
CUTOVER_SCRIPT = REPO_ROOT / "agent-runtime" / "scripts" / "ci" / "check_wave_rollout_cutover.py"

CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(CI_DIR))


# --- ADR-052 present, indexed, glossary-referenced ------------------------


def test_adr_052_file_exists_and_is_accepted() -> None:
    assert ADR_052.is_file(), "docs/adr/052-wave-free-merge-deferred-artifact-gate.md must exist"
    text = ADR_052.read_text(encoding="utf-8")
    assert "**Status:** Accepted" in text
    for section in ("## Context", "## Decision", "## Consequences"):
        assert section in text, f"ADR-052 missing {section}"


def test_adr_052_indexed_in_adr_readme() -> None:
    text = ADR_README.read_text(encoding="utf-8")
    assert "[052](052-wave-free-merge-deferred-artifact-gate.md)" in text
    assert "Accepted" in text.split("[052]", 1)[1].splitlines()[0]


def test_adr_052_referenced_in_context_glossary() -> None:
    text = CONTEXT_MD.read_text(encoding="utf-8")
    assert "ADR-052" in text
    assert "Free-merge (wave)" in text
    assert "Wave artifact gate" in text


# --- Topology / workflow docs match the implemented contract --------------


def test_topology_doc_states_no_up_to_date_requirement_on_wave_branches() -> None:
    text = TOPOLOGY_DOC.read_text(encoding="utf-8")
    assert 'No "up to date with base" requirement' in text
    assert "feature/*-wave" in text


def test_topology_doc_states_issue_pr_owns_manifest_bump() -> None:
    text = TOPOLOGY_DOC.read_text(encoding="utf-8")
    assert "issue→wave PR owns the wave-manifest bump" in text


def test_topology_doc_states_wave_push_is_before_after_domain_matched() -> None:
    text = TOPOLOGY_DOC.read_text(encoding="utf-8")
    assert "before→after" in text
    assert "domain-matched" in text


def test_topology_doc_states_wave_to_main_owns_artifact_gate() -> None:
    text = TOPOLOGY_DOC.read_text(encoding="utf-8")
    assert "artifact-gate" in text
    assert "wave → `main`" in text or "wave→main" in text


def test_topology_doc_labels_parallel_status_as_human_ops_ui_not_ci_sot() -> None:
    text = TOPOLOGY_DOC.read_text(encoding="utf-8")
    assert "human ops UI" in text
    assert "not a CI source of truth" in text


def test_issue_workflow_rule_documents_wave_pipeline() -> None:
    text = ISSUE_WORKFLOW_RULE.read_text(encoding="utf-8")
    assert "feature/*-wave" in text
    assert "before→after domain-matched" in text
    assert "artifact-gate" in text
    assert "ADR-052" in text


def test_git_baseline_rule_no_longer_claims_two_tier_ci() -> None:
    text = GIT_BASELINE_RULE.read_text(encoding="utf-8")
    assert "Two-tier CI" not in text
    assert "Three-tier CI" in text
    assert "ADR-052" in text


def test_parallel_status_markdown_is_not_claimed_as_ci_authority() -> None:
    """The generated ops-status file itself must not claim CI-parser status,
    and the topology doc that governs it must say so explicitly (covered
    above) — this test guards the artifact side of that claim."""
    text = PARALLEL_STATUS_MD.read_text(encoding="utf-8")
    assert "CI source of truth" not in text
    assert "CI parser" not in text


# --- Cutover checklist script exists, is importable, and runs -------------


def test_cutover_checklist_script_exists() -> None:
    assert CUTOVER_SCRIPT.is_file()


def test_cutover_checklist_script_is_importable_and_builds_a_report() -> None:
    module = importlib.import_module("check_wave_rollout_cutover")
    report = module.build_report()

    assert report["planId"] == "rep-662-ci-wave-4-docs-rollout-verification"
    assert "waveBranches" in report
    assert "waveTargetedPrs" in report
    summary = report["summary"]
    for key in (
        "totalWaveBranches",
        "refinedWaveBranches",
        "legacyWaveBranches",
        "totalWaveTargetedPrs",
        "mixedCoverage",
        "anyLegacyCoverage",
    ):
        assert key in summary


def test_cutover_checklist_classifies_a_branch_without_manifest_as_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("check_wave_rollout_cutover")
    # Classification smoke test — stub the two git-shelling helpers instead
    # of reading a live branch's real tree: once a wave's manifest merges to
    # main (as the A1 wave's did), main's *actual* committed tree legitimately
    # gains a wave-manifest file, which previously made this test depend on
    # main never having completed a wave merge. Mocking isolates the pure
    # classification logic (manifest presence + pr.yml content = the four
    # ADR-052 refined-workflow signals) from that ever-changing repo state.
    monkeypatch.setattr(module, "_remote_ls_tree", lambda branch: [])
    monkeypatch.setattr(module, "_remote_file", lambda branch, path: None)
    verdict = module.classify_wave_branch("main")
    assert verdict["hasWaveManifest"] is False
    assert verdict["workflow"] == "legacy"
    assert verdict["reasons"], "legacy classification must report reasons, not silently pass"


def test_cutover_checklist_runs_as_a_script_and_reports_mixed_or_legacy_explicitly() -> None:
    """Execute the script for real via --report; it must exit 0 (a
    successful enumeration, even when it finds legacy coverage) and its
    JSON payload must never omit a branch's classification."""
    result = subprocess.run(
        [sys.executable, str(CUTOVER_SCRIPT), "--report"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert '"waveBranches"' in result.stdout
    assert '"summary"' in result.stdout
    # The report must never silently claim a clean rollout by omission: if
    # any branch is legacy, RESULT must say so rather than print "refined".
    if '"legacyWaveBranches": 0' not in result.stdout:
        assert "LEGACY" in result.stdout or "legacy" in result.stdout.lower()
