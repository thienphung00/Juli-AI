"""Unit tests for validation CHECKS wiring (#516 / META-4 slice A)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATE_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "validate"
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(CI_DIR))

from generate_validation_artifact import CHECKS, load_checker  # noqa: E402

REQUIRED_NEW_CHECKS: list[tuple[str, str]] = [
    ("public_release_classification", "check_public_release_classification.py"),
    ("public_release_evidence_plan", "check_public_release_evidence_plan.py"),
    ("implementation_schema_valid", "check_implementation_schema_valid.py"),
    ("implementation_tdd_evidence", "check_implementation_tdd_evidence.py"),
    ("executor_domain_matches_cache", "check_executor_domain_matches_cache.py"),
    ("phase_run_correlation", "check_phase_run_correlation.py"),
    ("release_evidence_plan_continuity", "check_release_evidence_plan_continuity.py"),
    ("release_metadata_honesty", "check_release_metadata_honesty.py"),
]


def test_checks_include_meta_gate_wiring_from_issues_513_to_515() -> None:
    checks = dict(CHECKS)
    for name, script in REQUIRED_NEW_CHECKS:
        assert name in checks, f"missing CHECKS entry: {name}"
        assert checks[name] == script, f"{name} should map to {script}"


def test_new_check_scripts_resolve_under_validate_dir() -> None:
    for name, script in REQUIRED_NEW_CHECKS:
        path = VALIDATE_DIR / script
        assert path.is_file(), f"{name} script missing: {path}"


def test_new_check_scripts_expose_run_check() -> None:
    for _name, script in REQUIRED_NEW_CHECKS:
        run_check = load_checker(script)
        assert callable(run_check)


def test_generator_fails_when_new_check_fails(
    tmp_path: Path, monkeypatch
) -> None:
    import common
    import generate_validation_artifact as gva

    validation_dir = tmp_path / "agent-runtime" / "artifacts" / "validation"
    monkeypatch.setattr(common, "VALIDATION_DIR", validation_dir)
    monkeypatch.setattr(gva, "VALIDATION_DIR", validation_dir)

    def patched_load(script_name: str):
        if script_name == "check_release_metadata_honesty.py":

            def failing(_issue: int):
                return False, "deliberate test failure", {"test": True}

            return failing

        def passing(_issue: int):
            return True, "ok", {}

        return passing

    monkeypatch.setattr(gva, "load_checker", patched_load)
    monkeypatch.setattr(sys, "argv", ["generate_validation_artifact.py", "--issue", "516"])

    exit_code = gva.main()

    artifact_path = validation_dir / "validation-issue-516.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert exit_code == 1
    assert artifact["status"] == "FAIL"
    assert artifact["failedChecks"] >= 1
    failed_names = {check["name"] for check in artifact["checks"] if check["status"] == "FAIL"}
    assert "release_metadata_honesty" in failed_names
