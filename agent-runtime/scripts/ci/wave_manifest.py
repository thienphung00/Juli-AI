"""Wave manifest contract validation and artifact-gate helpers (#659 / CI-WAVE-1).

Pure-stdlib validator for committed ``agent-runtime/artifacts/waves/wave-<id>.json``
manifests and per-issue review/validation artifact PASS checks on wave→main.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from common import (
    AGENT_RUNTIME_ROOT,
    REVIEWS_DIR,
    STATUS_DIR,
    VALIDATION_DIR,
    load_json,
    print_check_result,
)
from json_schema_validate import validate_json_schema

SCHEMA_PATH = AGENT_RUNTIME_ROOT / "docs" / "schemas" / "wave-manifest.schema.json"
STATUS_SCHEMA_PATH = AGENT_RUNTIME_ROOT / "docs" / "schemas" / "status-record.schema.json"
WAVES_DIR = AGENT_RUNTIME_ROOT / "artifacts" / "waves"


@lru_cache(maxsize=1)
def load_wave_manifest_schema() -> dict[str, Any]:
    return load_json(SCHEMA_PATH)


@lru_cache(maxsize=1)
def load_status_record_schema() -> dict[str, Any]:
    return load_json(STATUS_SCHEMA_PATH)


def wave_manifest_path(wave_id: str) -> Path:
    return WAVES_DIR / f"{wave_id}.json"


def status_record_path(issue: int) -> Path:
    return STATUS_DIR / f"issue-{issue}.json"


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


def _load_status_record(issue: int) -> dict[str, Any] | None:
    return _load_artifact(status_record_path(issue))


def _sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _validate_issue_artifacts(issue: int, *, verify_integrity: bool = False) -> list[str]:
    """Read the compact status/issue-<N>.json record (#670 P1 Option A).

    Verbose review/validation bodies stay local only — gitignored, never
    committed, never uploaded anywhere; the wave->main gate asserts PASS
    from the compact record only. When
    ``verify_integrity`` is set and a verbose body still exists on disk
    (e.g. in the working tree during an agent loop, before it is gitignored
    away at commit time), its sha256 is checked against the record.
    """
    errors: list[str] = []

    record_path = status_record_path(issue)
    record = _load_status_record(issue)
    if record is None:
        errors.append(f"issue {issue}: missing status record at {record_path.name}")
        return errors

    schema_errors = validate_json_schema(record, load_status_record_schema())
    if schema_errors:
        errors.extend(f"issue {issue}: status record {msg}" for msg in schema_errors)

    if record.get("issue") != issue:
        errors.append(f"issue {issue}: status record issue field is {record.get('issue')!r}")

    review = record.get("review") if isinstance(record.get("review"), dict) else {}
    if review.get("status") != "PASS":
        errors.append(f"issue {issue}: review status must be PASS (got {review.get('status')!r})")

    validation = record.get("validation") if isinstance(record.get("validation"), dict) else {}
    if validation.get("status") != "PASS":
        errors.append(
            f"issue {issue}: validation status must be PASS (got {validation.get('status')!r})"
        )

    if verify_integrity:
        errors.extend(_verify_body_integrity(issue, "review", review, REVIEWS_DIR))
        errors.extend(_verify_body_integrity(issue, "validation", validation, VALIDATION_DIR))

    return errors


def _verify_body_integrity(
    issue: int, kind: str, entry: dict[str, Any], body_dir: Path
) -> list[str]:
    expected = entry.get("sha256") if isinstance(entry, dict) else None
    if not expected:
        return [f"issue {issue}: {kind} record missing sha256"]

    body_path = body_dir / f"{kind}-issue-{issue}.json"
    if not body_path.is_file():
        # Verbose body not present locally (expected once the working tree
        # that wrote it is gone — bodies are never committed or uploaded
        # anywhere else) — nothing to verify against.
        return []

    actual = _sha256_file(body_path)
    if actual != expected:
        return [f"issue {issue}: {kind} sha256 mismatch (record {expected}, on-disk {actual})"]
    return []


def waived_issues(manifest: dict[str, Any]) -> set[int]:
    """Issue numbers this manifest's waiver covers, if it carries one.

    The waiver lives inside the wave's own manifest and names its issues one by
    one, so it cannot reach another wave and cannot grow to cover an issue added
    after the decision was recorded.
    """
    waiver = manifest.get("artifactWaiver")
    if not isinstance(waiver, dict):
        return set()

    listed = waiver.get("issues")
    if not isinstance(listed, list):
        return set()

    return {issue for issue in listed if isinstance(issue, int) and not isinstance(issue, bool)}


def describe_waiver(manifest: dict[str, Any]) -> str | None:
    """One-line summary of an active waiver, for the gate to print. None if absent."""
    waiver = manifest.get("artifactWaiver")
    if not isinstance(waiver, dict):
        return None

    covered = sorted(waived_issues(manifest))
    return (
        f"artifact waiver active for {len(covered)} issue(s) {covered} "
        f"— {waiver.get('adr')}, approved by {waiver.get('approvedBy')}: {waiver.get('reason')}"
    )


def validate_wave_artifacts(
    manifest: Any,
    *,
    expected_wave_id: str | None = None,
    expected_branch: str | None = None,
    verify_integrity: bool = False,
) -> dict[str, Any]:
    """Wave→main artifact gate: manifest valid and every issue has a PASS status record.

    An issue named by this manifest's ``artifactWaiver`` is accepted without a
    status record. The waiver never suppresses the failure silently — the CLI
    prints it — and it cannot cover an issue that is not in the wave.
    """
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

    waived = waived_issues(manifest)

    # A waiver may only excuse issues the wave actually carries. Anything else is
    # a drafting error and must fail rather than sit unnoticed in the manifest.
    for issue in sorted(waived - {i for i in issues if isinstance(i, int)}):
        errors.append(f"artifactWaiver covers issue {issue}, which is not in this wave")

    for issue in issues:
        if not isinstance(issue, int) or isinstance(issue, bool):
            errors.append(f"issues contains non-integer entry: {issue!r}")
            continue
        if issue in waived:
            continue
        errors.extend(_validate_issue_artifacts(issue, verify_integrity=verify_integrity))

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
        help="Validate PASS status records (agent-runtime/artifacts/status/) for manifest issues",
    )
    parser.add_argument(
        "--verify-integrity",
        action="store_true",
        help="With --check-artifacts, also sha256-verify verbose bodies present on disk",
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
            verify_integrity=args.verify_integrity,
        )
        # A waived gate must never read like a clean one in the log.
        waiver_line = describe_waiver(manifest) if isinstance(manifest, dict) else None
        if waiver_line:
            print(f"wave_artifact_gate: WAIVED — {waiver_line}")
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
