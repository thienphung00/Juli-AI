"""Wave manifest contract validation and artifact-gate helpers (#659 / CI-WAVE-1).

Pure-stdlib validator for committed ``agent-runtime/artifacts/waves/wave-<id>.json``
manifests and per-issue review/validation artifact PASS checks on wave→main.
"""

from __future__ import annotations

import argparse
import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from common import (
    AGENT_RUNTIME_ROOT,
    REVIEWS_DIR,
    VALIDATION_DIR,
    load_json,
    print_check_result,
)
from json_schema_validate import validate_json_schema

SCHEMA_PATH = AGENT_RUNTIME_ROOT / "docs" / "schemas" / "wave-manifest.schema.json"
WAVES_DIR = AGENT_RUNTIME_ROOT / "artifacts" / "waves"


@lru_cache(maxsize=1)
def load_wave_manifest_schema() -> dict[str, Any]:
    return load_json(SCHEMA_PATH)


def wave_manifest_path(wave_id: str) -> Path:
    return WAVES_DIR / f"{wave_id}.json"


def _load_artifact(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _issues_uniqueness_errors(issues: Any) -> list[str]:
    if not isinstance(issues, list):
        return []
    seen: set[int] = set()
    errors: list[str] = []
    for index, issue in enumerate(issues):
        if not isinstance(issue, int) or isinstance(issue, bool):
            continue
        if issue in seen:
            errors.append(f"$.issues[{index}]: duplicate issue {issue}")
        seen.add(issue)
    return errors


def validate_wave_manifest(manifest: Any) -> dict[str, Any]:
    """Return ``{valid, errors}`` for a parsed wave manifest object."""
    if manifest is None or not isinstance(manifest, dict):
        return {"valid": False, "errors": ["wave manifest missing or not an object"]}

    schema = load_wave_manifest_schema()
    errors = validate_json_schema(manifest, schema)
    errors.extend(_issues_uniqueness_errors(manifest.get("issues")))
    return {"valid": not errors, "errors": errors}


def validate_wave_manifest_identity(
    manifest: dict[str, Any],
    *,
    expected_wave_id: str | None = None,
    expected_branch: str | None = None,
) -> list[str]:
    """Reject manifests that do not match the active wave branch identity."""
    errors: list[str] = []
    if expected_wave_id is not None and manifest.get("waveId") != expected_wave_id:
        errors.append(
            f"waveId mismatch: manifest has {manifest.get('waveId')!r}, "
            f"expected {expected_wave_id!r}"
        )
    if expected_branch is not None and manifest.get("branch") != expected_branch:
        errors.append(
            f"branch mismatch: manifest has {manifest.get('branch')!r}, "
            f"expected {expected_branch!r}"
        )
    return errors


def issue_in_manifest(manifest: dict[str, Any], issue: int) -> bool:
    issues = manifest.get("issues") or []
    return isinstance(issues, list) and issue in issues


def check_issue_membership(manifest: Any, issue: int) -> dict[str, Any]:
    """Issue-tier policy: manifest must be valid and include the PR issue."""
    schema_result = validate_wave_manifest(manifest)
    if not schema_result["valid"]:
        return schema_result

    if not isinstance(manifest, dict):
        return {"valid": False, "errors": ["wave manifest missing or not an object"]}

    if issue_in_manifest(manifest, issue):
        return {"valid": True, "errors": []}

    return {
        "valid": False,
        "errors": [f"issue {issue} missing from manifest issues list"],
    }


def _validate_issue_artifacts(issue: int) -> list[str]:
    errors: list[str] = []

    review_path = REVIEWS_DIR / f"review-issue-{issue}.json"
    review = _load_artifact(review_path)
    if review is None:
        errors.append(f"issue {issue}: missing review artifact at {review_path.name}")
    else:
        if review.get("issue") != issue:
            errors.append(
                f"issue {issue}: review artifact issue field is {review.get('issue')!r}"
            )
        if review.get("status") != "PASS":
            errors.append(
                f"issue {issue}: review status must be PASS (got {review.get('status')!r})"
            )

    validation_path = VALIDATION_DIR / f"validation-issue-{issue}.json"
    validation = _load_artifact(validation_path)
    if validation is None:
        errors.append(
            f"issue {issue}: missing validation artifact at {validation_path.name}"
        )
    else:
        if validation.get("issue") != issue:
            errors.append(
                f"issue {issue}: validation artifact issue field is {validation.get('issue')!r}"
            )
        if validation.get("status") != "PASS":
            errors.append(
                f"issue {issue}: validation status must be PASS "
                f"(got {validation.get('status')!r})"
            )
        if validation.get("readyForMerge") is not True:
            errors.append(
                f"issue {issue}: validation readyForMerge must be true "
                f"(got {validation.get('readyForMerge')!r})"
            )

    return errors


def validate_wave_artifacts(
    manifest: Any,
    *,
    expected_wave_id: str | None = None,
    expected_branch: str | None = None,
) -> dict[str, Any]:
    """Wave→main artifact gate: manifest valid and every issue has PASS artifacts."""
    schema_result = validate_wave_manifest(manifest)
    if not schema_result["valid"]:
        return schema_result

    if not isinstance(manifest, dict):
        return {"valid": False, "errors": ["wave manifest missing or not an object"]}

    errors = list(
        validate_wave_manifest_identity(
            manifest,
            expected_wave_id=expected_wave_id,
            expected_branch=expected_branch,
        )
    )

    issues = manifest.get("issues") or []
    if not isinstance(issues, list):
        return {"valid": False, "errors": ["issues must be an array"]}

    for issue in issues:
        if not isinstance(issue, int) or isinstance(issue, bool):
            errors.append(f"issues contains non-integer entry: {issue!r}")
            continue
        errors.extend(_validate_issue_artifacts(issue))

    return {"valid": not errors, "errors": errors}


def load_wave_manifest(wave_id: str) -> dict[str, Any] | None:
    return _load_artifact(wave_manifest_path(wave_id))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Path to wave manifest JSON (default: --wave-id lookup under artifacts/waves/)",
    )
    parser.add_argument(
        "--wave-id",
        help="Wave id (e.g. wave-658) when loading the committed manifest file",
    )
    parser.add_argument(
        "--branch",
        help="Expected feature/*-wave branch name for identity checks",
    )
    parser.add_argument(
        "--issue",
        type=int,
        help="Issue number for membership policy checks",
    )
    parser.add_argument(
        "--check-artifacts",
        action="store_true",
        help="Validate review/validation PASS artifacts for manifest issues",
    )
    args = parser.parse_args()

    manifest_path = args.manifest
    if manifest_path is None and args.wave_id:
        manifest_path = wave_manifest_path(args.wave_id)
    if manifest_path is None or not manifest_path.is_file():
        print("error: wave manifest path required and must exist", file=sys.stderr)
        return 1

    manifest = _load_artifact(manifest_path)
    if manifest is None:
        print(f"error: could not parse manifest at {manifest_path}", file=sys.stderr)
        return 1

    expected_wave_id = args.wave_id or manifest.get("waveId")
    expected_branch = args.branch or manifest.get("branch")

    if args.issue is not None:
        membership = check_issue_membership(manifest, args.issue)
        identity_errors = validate_wave_manifest_identity(
            manifest,
            expected_wave_id=expected_wave_id,
            expected_branch=expected_branch,
        )
        passed = membership["valid"] and not identity_errors
        detail = ""
        if identity_errors:
            detail = identity_errors[0]
        elif membership["errors"]:
            detail = membership["errors"][0]
        return print_check_result("wave_issue_membership", passed, detail)

    if args.check_artifacts:
        result = validate_wave_artifacts(
            manifest,
            expected_wave_id=expected_wave_id,
            expected_branch=expected_branch,
        )
        detail = result["errors"][0] if result["errors"] else ""
        return print_check_result("wave_artifact_gate", result["valid"], detail)

    result = validate_wave_manifest(manifest)
    identity_errors = validate_wave_manifest_identity(
        manifest,
        expected_wave_id=expected_wave_id,
        expected_branch=expected_branch,
    )
    all_errors = result["errors"] + identity_errors
    detail = all_errors[0] if all_errors else ""
    return print_check_result("wave_manifest", not all_errors, detail)


if __name__ == "__main__":
    raise SystemExit(main())
