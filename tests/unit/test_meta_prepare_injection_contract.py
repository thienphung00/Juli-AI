"""Unit tests for Meta → Executor injection contract (#514 / META-2)."""

from __future__ import annotations

import json
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "agent-runtime" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import meta_prepare_executor as mpe  # noqa: E402
from meta_prepare_executor import injection_plan  # noqa: E402

TDD_CONTRACT = {
    "required": True,
    "minRedGreenCycles": 1,
    "requireTestsAddedOrUpdated": True,
    "requirePassingCommandEvidence": True,
}

_MIN_CONFIG = {"workflow_prompt_cache": {"requireValidCacheBeforeExecutor": True}}


def _child_and_parent(
    *,
    public_release: bool = False,
    plan: dict[str, Any] | None = None,
    executor_domain: str = "backend",
) -> tuple[dict[str, Any], dict[str, Any]]:
    profile: dict[str, Any] = {
        "executorDomain": executor_domain,
        "requiredDocs": ["agent-runtime/scripts/meta_prepare_executor.py"],
        "requiredModules": [],
        "acceptanceCriteria": ["x"],
        "loadWhenNeeded": [],
    }
    if plan is not None:
        profile["releaseEvidencePlan"] = plan
    parent = {"parentScopeBlock": "# parent", "doNotLoad": ["web/"]}
    child: dict[str, Any] = {
        "publicRelease": public_release,
        "publicReleaseReasons": ["path:apps/demo"] if public_release else [],
        "issueLoadProfile": profile,
        "harnessUtility": {
            "skills": [
                {"path": ".cursor/skills/domain/backend/SKILL.md", "purpose": "exec"},
            ],
            "rulesTier2": [],
            "mcps": [],
            "tools": ["Read"],
        },
        "phaseCacheBlocks": {"meta": "# meta"},
        "promptCacheBlock": "# issue",
        "doNotLoad": ["web/"],
    }
    return child, parent


def _run_meta_prepare(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    issue_id: int = 999,
    gates_passed: bool = True,
    gate_results: list[dict[str, Any]] | None = None,
) -> tuple[int, dict[str, Any]]:
    if gate_results is None:
        gate_results = [
            {
                "gate": "public_release_evidence_plan",
                "passed": gates_passed,
                "description": "ok" if gates_passed else "failed",
                "details": {},
            }
        ]
    monkeypatch.setattr(
        mpe,
        "load_runtime_config",
        lambda repo_root, config=None: _MIN_CONFIG,
    )
    monkeypatch.setattr(
        mpe,
        "run_all_gates",
        lambda issue, **kwargs: (gates_passed, gate_results),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "meta_prepare_executor.py",
            "--issue",
            str(issue_id),
            "--skip-ensure",
            "--repo-root",
            str(tmp_path),
        ],
    )
    buffer = StringIO()
    with redirect_stdout(buffer):
        code = mpe.main()
    return code, json.loads(buffer.getvalue())


def test_non_public_ready_omits_plan_keys_and_includes_tdd_contract() -> None:
    child, parent = _child_and_parent(public_release=False, plan=None)
    plan = injection_plan(child, parent)

    assert plan["publicRelease"] is False
    assert plan["tddContract"] == TDD_CONTRACT
    assert "releaseEvidencePlan" not in plan
    assert "releaseEvidencePlanId" not in plan
    assert plan["executorDomain"] == "backend"


def test_public_valid_plan_injects_full_plan_and_ids() -> None:
    release_plan = {
        "planId": "rep-514-test",
        "affectedPublicSurfaces": ["demo.app-juli.com"],
        "candidateVerificationJourney": {"mode": "candidate_verification", "journeys": []},
        "staticAssetChecks": {"required": True},
        "migrationCompatibility": {"schemaChangeInScope": False},
        "rollbackAssertion": {"automatic": True},
        "requiredArtifacts": {"implementation": True},
        "acceptanceCommands": ["pytest -q"],
        "doNotInfer": ["x"],
    }
    child, parent = _child_and_parent(public_release=True, plan=release_plan)
    plan = injection_plan(child, parent)

    assert plan["publicRelease"] is True
    assert plan["tddContract"] == TDD_CONTRACT
    assert plan["releaseEvidencePlan"] == release_plan
    assert plan["releaseEvidencePlanId"] == "rep-514-test"


def test_harness_utility_excludes_review_validate_skill_paths() -> None:
    child, parent = _child_and_parent(public_release=False)
    child["harnessUtility"] = {
        "skills": [
            {"path": ".cursor/skills/domain/backend/SKILL.md", "purpose": "exec"},
            {"path": ".cursor/skills/standalone/intent-review/SKILL.md", "purpose": "review"},
            {"path": ".cursor/skills/standalone/guardrails/SKILL.md", "purpose": "review"},
            {"path": ".cursor/skills/standalone/validate/SKILL.md", "purpose": "validate"},
        ],
        "rulesTier2": [],
        "mcps": [],
        "tools": ["Read"],
    }
    plan = injection_plan(child, parent)
    paths = [skill["path"] for skill in plan["harnessUtility"]["skills"]]

    assert paths == [".cursor/skills/domain/backend/SKILL.md"]


def test_executor_domain_mismatch_detected() -> None:
    child, parent = _child_and_parent(public_release=False, executor_domain="backend")
    plan = injection_plan(child, parent)
    plan["executorDomain"] = "ui-ux"

    assert mpe.executor_domain_mismatch(child, plan) is True


def test_public_missing_plan_halts_with_missing_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sys.path.insert(0, str(REPO_ROOT / "tests" / "unit"))
    from test_public_release_meta_gates import _write_caches  # noqa: E402

    _write_caches(
        tmp_path,
        public_release=True,
        reasons=["path:apps/demo"],
        profile_paths=["apps/demo/src/app/page.tsx"],
        plan=None,
    )
    gate_results = [
        {
            "gate": "public_release_evidence_plan",
            "passed": False,
            "description": "missing plan",
            "details": {
                "halt": True,
                "missingFields": ["planId", "affectedPublicSurfaces"],
                "resolution": "Complete issueLoadProfile.releaseEvidencePlan fields",
            },
        }
    ]
    code, payload = _run_meta_prepare(
        tmp_path, monkeypatch, gates_passed=False, gate_results=gate_results
    )

    assert code == 1
    assert payload["readyForExecutor"] is False
    assert payload["halt"] is True
    assert payload["failedGate"] == "public_release_evidence_plan"
    assert payload["missingFields"] == ["planId", "affectedPublicSurfaces"]
    assert payload["resolution"]


def test_public_valid_plan_ready_injection_matches_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sys.path.insert(0, str(REPO_ROOT / "tests" / "unit"))
    from test_public_release_meta_gates import _valid_plan, _write_caches  # noqa: E402

    plan_obj = _valid_plan()
    _write_caches(
        tmp_path,
        public_release=True,
        reasons=["path:apps/demo"],
        profile_paths=["apps/demo/src/app/page.tsx"],
        plan=plan_obj,
    )
    code, payload = _run_meta_prepare(tmp_path, monkeypatch)

    assert code == 0
    assert payload["readyForExecutor"] is True
    assert payload["halt"] is False
    injection = payload["injectionPlan"]
    assert injection["publicRelease"] is True
    assert injection["tddContract"] == TDD_CONTRACT
    assert injection["releaseEvidencePlan"] == plan_obj
    assert injection["releaseEvidencePlanId"] == plan_obj["planId"]


def test_non_public_integration_ready_without_plan_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sys.path.insert(0, str(REPO_ROOT / "tests" / "unit"))
    from test_public_release_meta_gates import _write_caches  # noqa: E402

    _write_caches(
        tmp_path,
        public_release=False,
        reasons=[],
        profile_paths=["agent-runtime/scripts/meta_prepare_executor.py"],
        plan=None,
    )
    code, payload = _run_meta_prepare(tmp_path, monkeypatch)

    assert code == 0
    injection = payload["injectionPlan"]
    assert injection["publicRelease"] is False
    assert injection["tddContract"] == TDD_CONTRACT
    assert "releaseEvidencePlan" not in injection
    assert "releaseEvidencePlanId" not in injection


def test_domain_mismatch_halts_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sys.path.insert(0, str(REPO_ROOT / "tests" / "unit"))
    from test_public_release_meta_gates import _write_caches  # noqa: E402

    _write_caches(
        tmp_path,
        public_release=False,
        reasons=[],
        profile_paths=["agent-runtime/scripts/meta_prepare_executor.py"],
        plan=None,
    )

    real_injection_plan = mpe.injection_plan

    def _mismatched_plan(child: dict[str, Any], parent: dict[str, Any]) -> dict[str, Any]:
        plan = real_injection_plan(child, parent)
        plan["executorDomain"] = "ui-ux"
        return plan

    monkeypatch.setattr(mpe, "injection_plan", _mismatched_plan)
    code, payload = _run_meta_prepare(tmp_path, monkeypatch)

    assert code == 1
    assert payload["readyForExecutor"] is False
    assert payload["halt"] is True
    assert payload["failedGate"] == "executor_domain_alignment"
    assert payload["missingFields"] == []
    assert payload["resolution"]
