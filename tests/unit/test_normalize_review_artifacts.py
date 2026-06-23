from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "ci"))

from common import (  # noqa: E402
    build_review_artifact,
    normalize_review_findings,
    review_status_issues,
)


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
