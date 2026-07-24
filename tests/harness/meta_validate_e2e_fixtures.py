"""Shared fixtures for Meta prepare → Validate E2E matrix tests (#516 / META-4)."""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "agent-runtime" / "scripts"
VALIDATE_DIR = SCRIPTS_DIR / "validate"
CI_DIR = SCRIPTS_DIR / "ci"
UNIT_DIR = REPO_ROOT / "tests" / "unit"

for path in (VALIDATE_DIR, CI_DIR, SCRIPTS_DIR, UNIT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import meta_prepare_executor as mpe  # noqa: E402
from common import build_implementation_artifact, write_json  # noqa: E402
from test_public_release_meta_gates import _valid_plan, _write_caches  # noqa: E402

PUBLIC_ISSUE = 516001
NON_PUBLIC_ISSUE = 516002
PARENT_ISSUE = 516500
PHASE_RUN_ID = "516-e2e-phase-run"
PLAN_ID = "rep-516-e2e-public"

_MIN_CONFIG = {"workflow_prompt_cache": {"requireValidCacheBeforeExecutor": True}}

# META-3 validate gates exercised by the E2E matrix (Agent A may extend CHECKS later).
META_VALIDATE_CHECKS: list[tuple[str, str]] = [
    ("release_evidence_plan_continuity", "check_release_evidence_plan_continuity.py"),
    ("phase_run_correlation", "check_phase_run_correlation.py"),
    ("implementation_tdd_evidence", "check_implementation_tdd_evidence.py"),
]


def valid_release_plan(*, plan_id: str = PLAN_ID) -> dict[str, Any]:
    plan = _valid_plan()
    plan["planId"] = plan_id
    return plan


def patch_artifact_dirs(monkeypatch: pytest.MonkeyPatch, repo_root: Path) -> None:
    import common

    monkeypatch.setattr(
        common,
        "IMPLEMENTATIONS_DIR",
        repo_root / "agent-runtime" / "artifacts" / "implementations",
    )
    monkeypatch.setattr(
        common,
        "INTENT_REVIEWS_DIR",
        repo_root / "agent-runtime" / "artifacts" / "intent-reviews",
    )
    monkeypatch.setattr(
        common,
        "REVIEWS_DIR",
        repo_root / "agent-runtime" / "artifacts" / "reviews",
    )
    monkeypatch.setattr(
        common,
        "VALIDATION_DIR",
        repo_root / "agent-runtime" / "artifacts" / "validation",
    )


def ensure_public_issue_cache(
    repo: Path,
    *,
    issue_id: int = PUBLIC_ISSUE,
    plan: dict[str, Any] | None = None,
) -> None:
    _write_caches(
        repo,
        issue_id=issue_id,
        parent_id=PARENT_ISSUE,
        public_release=True,
        reasons=["path:apps/demo"],
        profile_paths=["apps/demo/src/app/page.tsx"],
        plan=plan,
    )


def ensure_non_public_issue_cache(
    repo: Path,
    *,
    issue_id: int = NON_PUBLIC_ISSUE,
) -> None:
    _write_caches(
        repo,
        issue_id=issue_id,
        parent_id=PARENT_ISSUE,
        public_release=False,
        reasons=[],
        profile_paths=["agent-runtime/scripts/meta_prepare_executor.py"],
        plan=None,
    )


def _tdd_overrides(**extra: Any) -> dict[str, Any]:
    return {
        "executionDurationMs": 1200,
        "tokenUsage": {"input": 10, "output": 5, "total": 15},
        "filesModified": ["agent-runtime/scripts/validate/check_implementation_tdd_evidence.py"],
        "testsAdded": ["tests/harness/test_meta_validate_e2e_public_release.py"],
        "testsUpdated": [],
        "redGreenRefactorEvidence": [
            {"cycle": 1, "commands": [{"command": "pytest -q", "exitCode": 0}]}
        ],
        **extra,
    }


def write_matching_phase_artifacts(
    repo: Path,
    issue: int,
    *,
    phase_run_id: str = PHASE_RUN_ID,
    plan_id: str | None = PLAN_ID,
    public_release: bool = True,
    tdd_overrides: dict[str, Any] | None = None,
) -> None:
    overrides = _tdd_overrides(**(tdd_overrides or {}))
    artifact = build_implementation_artifact(
        issue,
        "backend",
        phase_run_id=phase_run_id,
        overrides=overrides,
    )
    if public_release and plan_id is not None:
        artifact["releaseEvidencePlanId"] = plan_id

    impl_dir = repo / "agent-runtime" / "artifacts" / "implementations"
    impl_dir.mkdir(parents=True, exist_ok=True)
    write_json(impl_dir / f"implementation-issue-{issue}.json", artifact)

    required = (valid_release_plan(plan_id=plan_id or PLAN_ID) if public_release else {}).get(
        "requiredArtifacts",
        {
            "implementation": True,
            "intentReview": True,
            "review": True,
            "validation": True,
        },
    )
    if public_release:
        cache_path = repo / "agent-runtime" / "artifacts" / "workflow-cache" / f"issue-context-cache-{issue}.json"
        if cache_path.exists():
            child = json.loads(cache_path.read_text(encoding="utf-8"))
            profile = child.setdefault("issueLoadProfile", {})
            profile.setdefault("releaseEvidencePlan", {})["requiredArtifacts"] = required

    for subdir, filename, key in (
        ("intent-reviews", f"intent-review-issue-{issue}.json", "intentReview"),
        ("reviews", f"review-issue-{issue}.json", "review"),
        ("validation", f"validation-issue-{issue}.json", "validation"),
    ):
        if not required.get(key, True):
            continue
        payload: dict[str, Any] = {"issue": issue, "phaseRunId": phase_run_id}
        if public_release and plan_id is not None:
            payload["releaseEvidencePlanId"] = plan_id
        directory = repo / "agent-runtime" / "artifacts" / subdir
        directory.mkdir(parents=True, exist_ok=True)
        write_json(directory / filename, payload)


def run_meta_prepare(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    issue: int,
    *,
    gates_passed: bool | None = None,
    gate_results: list[dict[str, Any]] | None = None,
) -> tuple[int, dict[str, Any]]:
    if gates_passed is None:
        gates_passed = gate_results is None or all(item["passed"] for item in (gate_results or []))

    if gate_results is None:
        gate_results = [
            {
                "gate": "public_release_evidence_plan",
                "passed": gates_passed,
                "description": "ok" if gates_passed else "failed",
                "details": {},
            }
        ]

    monkeypatch.setattr(mpe, "load_runtime_config", lambda repo_root, config=None: _MIN_CONFIG)
    monkeypatch.setattr(
        mpe,
        "run_all_gates",
        lambda issue_id, **kwargs: (gates_passed, gate_results),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "meta_prepare_executor.py",
            "--issue",
            str(issue),
            "--skip-ensure",
            "--repo-root",
            str(repo),
        ],
    )
    buffer = StringIO()
    with redirect_stdout(buffer):
        code = mpe.main()
    return code, json.loads(buffer.getvalue())


def evidence_plan_gate_result(
    repo: Path,
    issue: int,
) -> tuple[bool, list[dict[str, Any]]]:
    from check_public_release_evidence_plan import run_check as run_evidence_plan  # noqa: E402

    passed, description, details = run_evidence_plan(issue, repo_root=repo)
    return passed, [
        {
            "gate": "public_release_evidence_plan",
            "passed": passed,
            "description": description,
            "details": details,
        }
    ]


def load_checker(script_name: str):
    path = VALIDATE_DIR / script_name
    spec = importlib.util.spec_from_file_location(script_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run_check


def _invoke_run_check(
    run_check,
    issue: int,
    *,
    repo_root: Path,
) -> tuple[bool, str, dict[str, Any]]:
    params = inspect.signature(run_check).parameters
    if "repo_root" in params:
        return run_check(issue, repo_root=repo_root)
    return run_check(issue)


def meta_validate_check_names() -> list[str]:
    try:
        from generate_validation_artifact import CHECKS  # noqa: E402

        wired = {name for name, _ in CHECKS}
        return [name for name, _ in META_VALIDATE_CHECKS if name in wired]
    except ImportError:
        return [name for name, _ in META_VALIDATE_CHECKS]


def resolved_meta_validate_checks() -> list[tuple[str, str]]:
    try:
        from generate_validation_artifact import CHECKS  # noqa: E402

        wired = dict(CHECKS)
        return [(name, wired[name]) for name, _ in META_VALIDATE_CHECKS if name in wired]
    except ImportError:
        return list(META_VALIDATE_CHECKS)


def run_meta_validate_matrix(
    issue: int,
    *,
    repo_root: Path,
    checks: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    selected = checks or resolved_meta_validate_checks()
    results: list[dict[str, Any]] = []
    failed = 0
    for check_name, script in selected:
        run_check = load_checker(script)
        passed, description, details = _invoke_run_check(run_check, issue, repo_root=repo_root)
        if not passed:
            failed += 1
        results.append(
            {
                "name": check_name,
                "status": "PASS" if passed else "FAIL",
                "description": description,
                "details": details,
            }
        )
    status = "PASS" if failed == 0 else "FAIL"
    return {
        "status": status,
        "failedChecks": failed,
        "passedChecks": len(results) - failed,
        "checks": results,
        "overallSummary": (
            "All meta validate checks passed."
            if failed == 0
            else f"{failed} meta validate check(s) failed."
        ),
    }
