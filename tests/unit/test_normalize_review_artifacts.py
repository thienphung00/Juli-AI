from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "agent-runtime" / "scripts" / "ci"))

from common import (  # noqa: E402
    FINDING_ARRAY_KEYS,
    build_review_artifact,
    derive_review_status,
    normalize_review_findings,
    review_status_issues,
)

SCHEMA_PATH = REPO_ROOT / "agent-runtime" / "docs" / "schemas" / "review-artifact.schema.json"


def test_normalize_migrates_warnings_and_aligns_status() -> None:
    existing = {
        "issue": 200,
        "status": "PASS",
        "criticalFindings": [],
        "warnings": [{"severity": "WARNING", "message": "provisional threshold"}],
        "modulesTouched": ["web"],
        "testCoverage": {
            "acceptance": {"total": 0, "mapped": 0, "unmapped": [], "mappings": []},
            "unit": {"passed": 1, "failed": 0},
        },
    }
    artifact = build_review_artifact(200, existing=existing, update_timestamp=False)
    assert artifact["status"] == "PASS_WITH_WARNINGS"
    assert "warnings" not in artifact
    assert len(artifact["criticalFindings"]) == 1
    assert artifact["criticalFindings"][0]["severity"] == "WARNING"
    assert not review_status_issues(artifact)


def test_normalize_does_not_backfill_signoff_fields() -> None:
    existing = {
        "issue": 201,
        "status": "PASS",
        "criticalFindings": [{"severity": "WARNING", "description": "warn"}],
        "modulesTouched": ["web"],
        "testCoverage": {
            "acceptance": {"total": 0, "mapped": 0, "unmapped": [], "mappings": []},
            "unit": {"passed": 0, "failed": 0},
        },
    }
    artifact = build_review_artifact(201, existing=existing, update_timestamp=False)
    finding = artifact["criticalFindings"][0]
    assert finding.get("acceptanceByReviewer") is None
    assert finding.get("ownerAck") is None
    assert artifact.get("reviewerSignoff") is None


def test_normalize_review_artifacts_check_reports_issues(tmp_path: Path) -> None:
    reviews_dir = tmp_path / "artifacts" / "reviews"
    reviews_dir.mkdir(parents=True)
    review = {
        "id": "review-issue-202",
        "issue": 202,
        "status": "PASS",
        "criticalFindings": [{"severity": "WARNING", "description": "warn"}],
        "modulesTouched": ["web"],
        "testCoverage": {
            "acceptance": {"total": 0, "mapped": 0, "unmapped": [], "mappings": []},
            "unit": {"passed": 0, "failed": 0},
        },
    }
    (reviews_dir / "review-issue-202.json").write_text(json.dumps(review), encoding="utf-8")

    import common

    original_dir = common.REVIEWS_DIR
    common.REVIEWS_DIR = reviews_dir
    try:
        issues = review_status_issues(review)
        assert any("does not match derived" in issue for issue in issues)
        normalized = build_review_artifact(202, existing=review, update_timestamp=False)
        assert normalized["status"] == "PASS_WITH_WARNINGS"
    finally:
        common.REVIEWS_DIR = original_dir


def test_legacy_warning_preserves_severity() -> None:
    artifact = {
        "criticalFindings": [],
        "warnings": [{"severity": "WARNING", "message": "note", "domain": "security"}],
    }
    findings = normalize_review_findings(artifact)
    assert findings[0]["severity"] == "WARNING"
    assert findings[0]["type"] == "security"


# Hard-coded, not sourced from ``common.FINDING_ARRAY_KEYS``: if that constant
# were ever neutered back down to a subset, importing it here for the
# parametrize list would silently shrink the test matrix along with it rather
# than turning red. This literal mirrors the five names the review-artifact
# schema declares (`test_schema_finding_arrays_all_have_a_reader` checks the
# production constant against the same schema).
SCHEMA_FINDING_ARRAYS = (
    "criticalFindings",
    "findings",
    "securityFindings",
    "architectureFindings",
    "maintainabilityFindings",
)


@pytest.mark.parametrize("array_name", sorted(SCHEMA_FINDING_ARRAYS))
def test_normalize_review_findings_sees_a_warning_in_every_schema_array(
    array_name: str,
) -> None:
    """#1601: each of the five schema-defined finding arrays must be read.

    Before the fix, only ``criticalFindings`` (plus legacy ``warnings[]``) was
    merged -- a WARNING placed in ``findings``, ``securityFindings``,
    ``architectureFindings``, or ``maintainabilityFindings`` (the name a
    reviewer reaches for first) was invisible to every gate and the review
    derived a clean PASS.
    """
    artifact = {
        array_name: [
            {"id": f"1601-{array_name}", "severity": "WARNING", "description": "unseen finding"}
        ]
    }
    findings = normalize_review_findings(artifact)
    descriptions = [f.get("description") for f in findings]
    assert "unseen finding" in descriptions
    assert derive_review_status(findings) == "PASS_WITH_WARNINGS"


def test_normalize_review_findings_deduplicates_derived_array_copies() -> None:
    """``enrich_review_artifact`` derives the four extra arrays from
    ``criticalFindings`` as identity-preserving subsets. Reading all five arrays
    must not double-count that common case.
    """
    finding = {"id": "dup-1", "severity": "WARNING", "description": "N+1 query"}
    artifact = {
        "criticalFindings": [finding],
        "findings": [finding],
        "maintainabilityFindings": [finding],
    }
    findings = normalize_review_findings(artifact)
    assert len(findings) == 1


def test_schema_finding_arrays_all_have_a_reader() -> None:
    """Detect a schema-defined finding array with no reader (#1601).

    Every property in the review-artifact schema that is an array and whose
    name identifies it as a finding collection (ends in "findings",
    case-insensitively -- ``findings``, ``criticalFindings``,
    ``securityFindings``, ``architectureFindings``, ``maintainabilityFindings``)
    must be a member of ``common.FINDING_ARRAY_KEYS``. Adding a new
    ``somethingFindings`` array to the schema without adding it to the reader
    fails this test instead of silently going unread.
    """
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    finding_arrays = {
        name
        for name, prop in schema.get("properties", {}).items()
        if isinstance(prop, dict)
        and prop.get("type") == "array"
        and name.lower().endswith("findings")
    }
    assert finding_arrays == set(FINDING_ARRAY_KEYS)
