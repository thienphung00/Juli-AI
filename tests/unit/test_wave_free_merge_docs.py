"""Docs/rollout contract tests for ADR-052 (CI-WAVE-4 / #662).

Asserts that the written record — ADR-052, its index/glossary references,
the parallel-workflow/worktree-topology docs, and the cutover checklist
script — actually reflects the free-merge / deferred artifact-gate contract
implemented by #659/#660/#661, per the release-evidence plan
`rep-662-ci-wave-4-docs-rollout-verification`.
"""

from __future__ import annotations

import importlib
import re
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


def test_cutover_checklist_script_is_importable_and_builds_a_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A unit test must not touch the network. build_report() fans out through
    # list_active_wave_branches() (a live `git fetch origin` + `git branch
    # -r`), list_wave_targeted_prs() (a live `gh pr list`), and
    # classify_wave_branch() per branch (`git ls-tree` / `git show` against
    # origin/*). A degraded network can let one of those subprocess calls
    # consume pytest-timeout's whole per-test budget before `_run`'s own
    # inner timeout gets a chance to fire, which is exactly what made this
    # test intermittently fail. Stub every subprocess-shelling entry point —
    # following the same pattern the classification test below already uses
    # for `_remote_ls_tree` / `_remote_file` — and assert the real report
    # shape against the stubbed data.
    module = importlib.import_module("check_wave_rollout_cutover")

    refined_pr_yml = "classify-tier:\nartifact-gate:\nfilter-wave\ngithub.event.before\n"

    def fake_remote_ls_tree(branch: str) -> list[str]:
        if branch == "feature/stub-refined-wave":
            return ["agent-runtime/artifacts/waves/wave-stub.json"]
        return []

    def fake_remote_file(branch: str, path: str) -> str | None:
        if path != ".github/workflows/pr.yml":
            return None
        return refined_pr_yml if branch == "feature/stub-refined-wave" else ""

    monkeypatch.setattr(
        module,
        "list_active_wave_branches",
        lambda: (["feature/stub-refined-wave", "feature/stub-legacy-wave"], True),
    )
    monkeypatch.setattr(
        module,
        "list_wave_targeted_prs",
        lambda: (
            [
                {
                    "number": 1,
                    "title": "stub issue-to-wave PR",
                    "baseRefName": "feature/stub-refined-wave",
                    "headRefName": "issue-1-stub",
                    "url": "https://example.invalid/pr/1",
                    "updatedAt": "2026-01-01T00:00:00Z",
                }
            ],
            True,
        ),
    )
    monkeypatch.setattr(module, "_remote_ls_tree", fake_remote_ls_tree)
    monkeypatch.setattr(module, "_remote_file", fake_remote_file)

    report = module.build_report()

    assert report["planId"] == "rep-662-ci-wave-4-docs-rollout-verification"
    assert "waveBranches" in report
    assert "waveTargetedPrs" in report
    assert report["waveBranches"], "stubbed wave branches must appear in the report"
    assert report["waveTargetedPrs"], "stubbed PRs must appear in the report"
    summary = report["summary"]
    for key in (
        "totalWaveBranches",
        "refinedWaveBranches",
        "legacyWaveBranches",
        "totalWaveTargetedPrs",
        "refinedPrs",
        "legacyOrUnknownPrs",
        "mixedCoverage",
        "anyLegacyCoverage",
    ):
        assert key in summary
    # The stubbed data is deliberately mixed (one refined branch, one legacy
    # branch, one PR targeting the refined branch) so the report exercises
    # real classification logic, not just key presence.
    assert summary["totalWaveBranches"] == 2
    assert summary["refinedWaveBranches"] == 1
    assert summary["legacyWaveBranches"] == 1
    assert summary["totalWaveTargetedPrs"] == 1
    assert summary["refinedPrs"] == 1
    assert summary["mixedCoverage"] is True


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
        # Must stay below pytest.ini's global `timeout = 30`: this was
        # previously 60, which meant a slow script invocation was always
        # killed by pytest-timeout's opaque SIGALRM well before this
        # subprocess.run timeout could ever fire its own, more diagnostic
        # subprocess.TimeoutExpired. 20s leaves headroom under the 30s outer
        # budget (a clean --report run of the script takes ~2s locally).
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert '"waveBranches"' in result.stdout
    assert '"summary"' in result.stdout
    # The report must never silently claim a clean rollout by omission: if
    # any branch is legacy, RESULT must say so rather than print "refined".
    if '"legacyWaveBranches": 0' not in result.stdout:
        assert "LEGACY" in result.stdout or "legacy" in result.stdout.lower()


# --- #1436: bypass privileges are bounded, and the bound is a property -----

CLAUDE_MD = REPO_ROOT / "CLAUDE.md"

#: Any of these, in the same paragraph as the bypass, satisfies "the reason is
#: recorded". A set rather than one phrase: the requirement is that an
#: obligation is stated, not that it is stated in the words the author happened
#: to choose. Written after #1436's own test was found to assert its author's
#: prose rather than the requirement.
_RECORDING_OBLIGATION = ("record", "recorded", "reason", "logged", "state why")

#: Likewise for prohibition.
_PROHIBITION = ("never", "not sanctioned", "forbidden", "prohibited", "must not", "do not use")

#: The documents that instruct either privilege. Both, because CLAUDE.md
#: inlines its own lane summary rather than pointing at the rule, so a policy
#: recorded in one is invisible to readers of the other.
_POLICY_DOCS = (GIT_BASELINE_RULE, CLAUDE_MD)


def _paragraphs_mentioning(text: str, token: str) -> list[str]:
    """Paragraphs (blank-line separated) containing `token`, list items split out.

    Splitting on list items matters: the two lanes live as adjacent bullets, and
    a paragraph-level check would let the fast-track bullet borrow the standard
    lane's language.
    """
    chunks: list[str] = []
    for para in text.split("\n\n"):
        if token not in para:
            continue
        items = re.split(r"\n(?=[-*] )", para)
        chunks.extend(item for item in items if token in item)
    return chunks


def test_every_admin_bypass_instruction_carries_a_recording_obligation() -> None:
    """#1436 AC1, asserted as a property rather than as a phrase.

    `--admin` skips `status-check`, the single required check on both rulesets
    and the roll-up every gate in this epic reports through. The requirement is
    not that some paragraph somewhere mentions recording — it is that *no*
    instruction to bypass stands without one. Quantifying over every occurrence
    is what makes this catch an instruction added later, which an assertion on
    fixed strings cannot.
    """
    found_any = False
    for doc in _POLICY_DOCS:
        text = doc.read_text(encoding="utf-8")
        for chunk in _paragraphs_mentioning(text, "--admin"):
            found_any = True
            lowered = chunk.lower()
            assert any(word in lowered for word in _RECORDING_OBLIGATION), (
                f"{doc.name} instructs `--admin` with no recording obligation in the "
                f"same instruction, so a sanctioned bypass is indistinguishable from "
                f"an unsanctioned one:\n\n{chunk.strip()[:400]}"
            )
    assert found_any, (
        "no document instructs `--admin`; if the lane genuinely dropped it, delete "
        "this test rather than leaving it vacuously green"
    )


def test_no_verify_is_prohibited_and_never_permitted() -> None:
    """#1436: `--no-verify` is the larger number in the corpus — 35 uses against
    `--admin`'s 10, every one from a parent orchestrator session, not an executor.

    The first version of this test required *every* mention to prohibit, and it
    failed — on the rule's own rationale paragraph, which cites those counts
    without repeating the prohibition. That was the test being wrong, not the
    rule: prose that explains why a thing is banned is not prose that permits it.

    The requirement is two-sided and this is its honest shape: something must
    prohibit it, and nothing may grant it. The second half is what catches a
    future paragraph reintroducing it permissively — which neither "some
    sentence prohibits it" nor "every mention prohibits it" would.
    """
    grants = ("may use", "can use", "is allowed", "acceptable", "is fine", "permitted")
    prohibited_somewhere = False
    mentioned = False

    for doc in _POLICY_DOCS:
        text = doc.read_text(encoding="utf-8")
        for chunk in _paragraphs_mentioning(text, "--no-verify"):
            mentioned = True
            lowered = chunk.lower()
            if any(word in lowered for word in _PROHIBITION):
                prohibited_somewhere = True
            granted = [g for g in grants if g in lowered]
            assert not granted, (
                f"{doc.name} contains language permitting `--no-verify` ({granted}):\n\n"
                f"{chunk.strip()[:400]}"
            )

    assert mentioned, "neither policy document addresses `--no-verify` at all"
    assert prohibited_somewhere, (
        "`--no-verify` is mentioned but never prohibited in either document; the "
        "corpus shows 35 uses and no sanctioned one"
    )


def test_the_two_harnesses_agree_on_what_is_sanctioned() -> None:
    """A policy in `.cursor/` alone is invisible to a Claude Code session, and a
    policy in CLAUDE.md alone is invisible to Cursor. Either privilege named in
    one document must be addressed in the other, or the harnesses disagree.
    """
    rule = GIT_BASELINE_RULE.read_text(encoding="utf-8")
    claude = CLAUDE_MD.read_text(encoding="utf-8")
    for token in ("--admin", "--no-verify"):
        assert (token in rule) == (token in claude), (
            f"`{token}` is addressed in only one of git-baseline.mdc / CLAUDE.md; "
            f"the two harnesses would carry different policies"
        )


def test_the_harness_path_bypass_documents_its_recording_form_and_the_repin() -> None:
    """#1641/#1647: the second sanctioned `--admin` case needs its own assertion.

    `test_every_admin_bypass_instruction_carries_a_recording_obligation` quantifies
    over paragraphs containing `--admin`, and the harness case is a sub-item under
    a parent bullet that carries the obligation — so the sub-item could lose its
    own recording form, or the re-pin requirement, without that test noticing.

    The re-pin half is the part that decays silently: skipping it leaves every
    later PR on the branch inheriting the same red, which reads as "CI is flaky"
    rather than "someone owes a re-pin".
    """
    rule = GIT_BASELINE_RULE.read_text(encoding="utf-8")
    if "sourcePath" not in rule:
        return  # the second case was withdrawn; nothing to assert

    assert "bypass: harness sourcePath change" in rule, (
        "the harness-path bypass is sanctioned without prescribing how it is recorded"
    )
    lowered = rule.lower()
    assert "re-pin" in lowered or "repin" in lowered, (
        "the harness-path bypass does not state that the pin must be refreshed afterwards; "
        "without it every later PR on the branch inherits the same red"
    )
