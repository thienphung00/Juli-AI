"""Unit tests for public_release Meta gates (#513 / META-1)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATE_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "validate"
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(VALIDATE_DIR))
sys.path.insert(0, str(CI_DIR))

from check_public_release_classification import run_check as run_classification  # noqa: E402
from check_public_release_evidence_plan import run_check as run_evidence_plan  # noqa: E402
from check_workflow_cache import GATE_SEQUENCE  # noqa: E402
from release_evidence_plan import (  # noqa: E402
    REQUIRED_TOP_LEVEL_FIELDS,
    resolve_release_evidence_plan,
)


def _valid_plan() -> dict[str, Any]:
    return {
        "planId": "rep-999-test",
        "affectedPublicSurfaces": ["demo.app-juli.com"],
        "candidateVerificationJourney": {
            "mode": "candidate_verification",
            "stableTrafficPercent": 100,
            "candidatePublicTrafficPercent": 0,
            "restrictedRoute": "test listener",
            "syntheticShopRequired": True,
            "workersDisabledOnCandidate": True,
            "journeys": [{"name": "home", "entryUrl": "/", "assertions": ["html_200"]}],
        },
        "staticAssetChecks": {
            "required": True,
            "htmlRoutes": ["/"],
            "discoverFromHtml": True,
            "assetTypes": ["css"],
            "failOnMissing": True,
            "failOnNon200": True,
        },
        "migrationCompatibility": {
            "schemaChangeInScope": False,
            "expandContractOnly": True,
            "stableAndCandidateCompatible": True,
            "destructiveMigrationAllowed": False,
            "notes": "none",
        },
        "rollbackAssertion": {
            "preCutoverFailureBehavior": "discard_candidate_keep_stable",
            "postCutoverFailureBehavior": "restore_stable_listener",
            "retainedStableRequired": True,
            "automatic": True,
        },
        "requiredArtifacts": {
            "implementation": True,
            "intentReview": True,
            "review": True,
            "validation": True,
            "releaseMetadataHonest": True,
        },
        "acceptanceCommands": ["pytest -q"],
        "doNotInfer": ["release evidence fields"],
    }


def _write_caches(
    repo: Path,
    *,
    issue_id: int = 999,
    parent_id: int = 900,
    public_release: bool,
    reasons: list[str],
    profile_paths: list[str],
    plan: dict[str, Any] | None = None,
    omit_classification: bool = False,
) -> None:
    cache_dir = repo / "agent-runtime" / "artifacts" / "workflow-cache"
    cache_dir.mkdir(parents=True)
    parent = {
        "schemaVersion": "1.0.0",
        "artifactType": "parent_cache",
        "parentIssueId": parent_id,
        "cacheBlockVersion": 1,
        "parentScopeBlock": "# parent",
        "sliceId": "META-1",
        "handoffPath": "docs/adr/035-public-release-evidence-and-automatic-rollback.md",
        "childIssueIds": [issue_id],
        "doNotLoad": ["web/"],
        "upstreamFingerprints": [],
        "bootstrapRef": {
            "branch": "HEAD",
            "commitSha": "abc",
            "copiedAt": "2026-01-01T00:00:00Z",
        },
        "lastValidatedAt": "2026-01-01T00:00:00Z",
    }
    profile: dict[str, Any] = {
        "executorDomain": "backend",
        "requiredDocs": profile_paths,
        "requiredModules": [],
        "acceptanceCriteria": ["x"],
        "loadWhenNeeded": [],
    }
    if plan is not None:
        profile["releaseEvidencePlan"] = plan
    child: dict[str, Any] = {
        "schemaVersion": "1.2.0",
        "artifactType": "issue_context_cache",
        "issueId": issue_id,
        "parentIssueId": parent_id,
        "parentCachePath": (
            f"agent-runtime/artifacts/workflow-cache/parent-cache-issue-{parent_id}.json"
        ),
        "phaseRunId": f"{issue_id}-test",
        "workflowPhase": "meta",
        "cacheStatus": "valid",
        "cacheBlockVersion": 1,
        "parentLinkage": {
            "sliceId": "META-1",
            "handoffPath": "docs/adr/035-public-release-evidence-and-automatic-rollback.md",
        },
        "issueLoadProfile": profile,
        "authorityChain": [{"rank": 1, "source": "EXECUTION.md", "reason": "law"}],
        "resolvedDecisions": [],
        "inScope": ["META-1"],
        "outOfScope": ["web/"],
        "doNotLoad": ["web/"],
        "promptCacheBlock": "# issue",
        "phaseCacheBlocks": {
            "scope": "",
            "meta": "",
            "executor": "",
            "review": "",
            "validate": "",
        },
        "harnessUtility": {
            "skills": [{"path": ".cursor/skills/domain/backend/SKILL.md", "purpose": "x"}],
            "rulesTier2": [],
            "mcps": [],
            "tools": ["Read"],
        },
        "upstreamFingerprints": [],
        "lastValidatedAt": "2026-01-01T00:00:00Z",
    }
    if not omit_classification:
        child["publicRelease"] = public_release
        child["publicReleaseReasons"] = reasons
    (cache_dir / f"parent-cache-issue-{parent_id}.json").write_text(
        json.dumps(parent), encoding="utf-8"
    )
    (cache_dir / f"issue-context-cache-{issue_id}.json").write_text(
        json.dumps(child), encoding="utf-8"
    )


def _write_committed_plan(repo: Path, issue_id: int, plan: dict[str, Any]) -> Path:
    artifacts = repo / "agent-runtime" / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    path = artifacts / f"release-evidence-plan-issue-{issue_id}.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    return path


def test_gate_sequence_includes_public_release_gates_after_load_profile() -> None:
    names = [name for name, _ in GATE_SEQUENCE]
    assert names.index("issue_load_profile") < names.index("public_release_classification")
    assert names.index("public_release_classification") < names.index(
        "public_release_evidence_plan"
    )


def test_non_public_passes_evidence_plan_without_plan(tmp_path: Path) -> None:
    _write_caches(
        tmp_path,
        public_release=False,
        reasons=[],
        profile_paths=["agent-runtime/scripts/ci/ensure_workflow_cache.py"],
        plan=None,
    )
    passed, description, details = run_evidence_plan(999, repo_root=tmp_path)
    assert passed is True
    assert details.get("skipped") is True
    assert "not required" in description


def test_public_missing_plan_fails_with_missing_fields(tmp_path: Path) -> None:
    _write_caches(
        tmp_path,
        public_release=True,
        reasons=["path:apps/demo"],
        profile_paths=["apps/demo/src/app/page.tsx"],
        plan=None,
    )
    passed, _description, details = run_evidence_plan(999, repo_root=tmp_path)
    assert passed is False
    assert details.get("halt") is True
    for field in REQUIRED_TOP_LEVEL_FIELDS:
        assert field in details["missingFields"]
    assert "resolution" in details
    assert "release-evidence-plan-issue-999.json" in details["resolution"]


def test_public_valid_plan_passes(tmp_path: Path) -> None:
    _write_caches(
        tmp_path,
        public_release=True,
        reasons=["path:apps/demo"],
        profile_paths=["apps/demo/src/app/page.tsx"],
        plan=_valid_plan(),
    )
    passed, description, details = run_evidence_plan(999, repo_root=tmp_path)
    assert passed is True
    assert details.get("planId") == "rep-999-test"
    assert details.get("planSource") == "workflow-cache"
    assert "schema-valid" in description


def test_public_valid_plan_from_committed_artifact_without_cache_plan(
    tmp_path: Path,
) -> None:
    """CI SoT: committed plan unlocks gate even when child cache has no plan."""
    _write_caches(
        tmp_path,
        public_release=True,
        reasons=["path:apps/demo"],
        profile_paths=["apps/demo/src/app/page.tsx"],
        plan=None,
    )
    _write_committed_plan(tmp_path, 999, _valid_plan())

    passed, description, details = run_evidence_plan(999, repo_root=tmp_path)

    assert passed is True
    assert details.get("planId") == "rep-999-test"
    assert details.get("planSource") == (
        "agent-runtime/artifacts/release-evidence-plan-issue-999.json"
    )
    assert "schema-valid" in description


def test_resolve_prefers_committed_plan_over_cache(tmp_path: Path) -> None:
    committed = _valid_plan()
    committed["planId"] = "rep-committed"
    cache_plan = _valid_plan()
    cache_plan["planId"] = "rep-cache"
    _write_committed_plan(tmp_path, 999, committed)
    child = {"issueLoadProfile": {"releaseEvidencePlan": cache_plan}}

    plan, source = resolve_release_evidence_plan(999, tmp_path, child_cache=child)

    assert plan is not None
    assert plan["planId"] == "rep-committed"
    assert source == "agent-runtime/artifacts/release-evidence-plan-issue-999.json"


def test_resolve_falls_back_to_meta_prepare_injection(tmp_path: Path) -> None:
    plan = _valid_plan()
    artifacts = tmp_path / "agent-runtime" / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "meta-prepare-issue-999.json").write_text(
        json.dumps({"injectionPlan": {"releaseEvidencePlan": plan}}),
        encoding="utf-8",
    )

    resolved, source = resolve_release_evidence_plan(999, tmp_path)

    assert resolved is not None
    assert resolved["planId"] == "rep-999-test"
    assert source == "agent-runtime/artifacts/meta-prepare-issue-999.json"


def test_classification_mismatch_fails(tmp_path: Path) -> None:
    _write_caches(
        tmp_path,
        public_release=False,
        reasons=[],
        profile_paths=["apps/demo/src/app/page.tsx"],
    )
    passed, _description, details = run_classification(
        999,
        repo_root=tmp_path,
        issue_body_fetcher=lambda _i: "Harness notes only",
        labels=[],
    )
    assert passed is False
    assert details["live"]["publicRelease"] is True


def test_classification_match_passes_non_public(tmp_path: Path) -> None:
    _write_caches(
        tmp_path,
        public_release=False,
        reasons=[],
        profile_paths=["agent-runtime/scripts/ci/ensure_workflow_cache.py"],
    )
    passed, _description, details = run_classification(
        999,
        repo_root=tmp_path,
        issue_body_fetcher=lambda _i: "Agent-runtime Meta gate only; no Demo UI",
        labels=[],
    )
    assert passed is True
    assert details["live"]["publicRelease"] is False


def test_missing_classification_fields_fail(tmp_path: Path) -> None:
    _write_caches(
        tmp_path,
        public_release=False,
        reasons=[],
        profile_paths=["agent-runtime/scripts/ci/ensure_workflow_cache.py"],
        omit_classification=True,
    )
    passed, _description, details = run_classification(
        999,
        repo_root=tmp_path,
        issue_body_fetcher=lambda _i: "Agent-runtime only",
        labels=[],
    )
    assert passed is False
    assert "publicRelease" in details["missingFields"]


def test_label_only_live_classification_marks_public(tmp_path: Path) -> None:
    """Label-only public issue: live classifier must see labels (not empty default)."""
    _write_caches(
        tmp_path,
        public_release=True,
        reasons=["label:public-release"],
        profile_paths=["agent-runtime/scripts/ci/ensure_workflow_cache.py"],
        plan=None,
    )
    passed, _description, details = run_classification(
        999,
        repo_root=tmp_path,
        issue_body_fetcher=lambda _i: "Agent-runtime Meta gate only; no Demo UI",
        issue_labels_fetcher=lambda _i: ["public-release"],
    )
    assert passed is True
    assert details["live"]["publicRelease"] is True
    assert "label:public-release" in details["live"]["publicReleaseReasons"]


def test_label_only_public_missing_plan_fails_closed(tmp_path: Path) -> None:
    _write_caches(
        tmp_path,
        public_release=True,
        reasons=["label:public-release"],
        profile_paths=["agent-runtime/scripts/ci/ensure_workflow_cache.py"],
        plan=None,
    )
    passed, _description, details = run_evidence_plan(999, repo_root=tmp_path)
    assert passed is False
    assert details.get("halt") is True
    assert "planId" in details["missingFields"]
