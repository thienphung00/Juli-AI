"""Unit tests for the merge status gate (#1569).

The merge gate reads review.status from the committed status record and blocks
when review.status is FAIL. Together with check_artifact_retention_guard.py,
this separates "is there evidence" from "did it pass".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(CI_DIR))

from check_merge_status import (  # noqa: E402
    evaluate,
    parse_issue_number,
)


def _write_record(
    status_dir: Path,
    issue: int,
    *,
    review_status: str = "PASS",
) -> Path:
    """Write a minimal status record for testing merge verdict."""
    status_dir.mkdir(parents=True, exist_ok=True)
    path = status_dir / f"issue-{issue}.json"
    payload = {
        "issue": issue,
        "wave": None,
        "review": {
            "status": review_status,
            "artifactRef": (
                f"git-history:agent-runtime/artifacts/reviews/review-issue-{issue}.json"
            ),
            "sha256": "a" * 64,
        },
        "validation": {
            "status": "PASS",
            "artifactRef": (
                f"git-history:agent-runtime/artifacts/validation/validation-issue-{issue}.json"
            ),
            "sha256": "b" * 64,
        },
        "gateVersion": 1,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# --- parse_issue_number: same as retention guard ---


@pytest.mark.parametrize(
    "raw",
    [None, "", "   ", "abc", "0", "-1", "12.5"],
)
def test_parse_issue_number_returns_none_for_non_issue_input(raw) -> None:
    assert parse_issue_number(raw) is None


def test_parse_issue_number_parses_a_real_issue_number() -> None:
    assert parse_issue_number("1569") == 1569
    assert parse_issue_number(" 1569 ") == 1569


# --- AC1: FAIL records block merge ---


def test_fails_when_review_status_is_fail(tmp_path: Path) -> None:
    """GIVEN a committed record with review.status: FAIL WHEN merge gate runs
    THEN it fails and blocks the merge."""
    issue = 1569
    _write_record(tmp_path, issue, review_status="FAIL")

    passed, detail = evaluate(issue, status_dir=tmp_path)
    assert passed is False
    assert "review.status is 'FAIL'" in detail
    assert "merge blocked" in detail


# --- AC2: PASS records proceed to merge ---


def test_passes_when_review_status_is_pass(tmp_path: Path) -> None:
    """GIVEN a committed record with review.status: PASS WHEN merge gate runs
    THEN it passes and allows merge to proceed."""
    issue = 1569
    _write_record(tmp_path, issue, review_status="PASS")

    passed, detail = evaluate(issue, status_dir=tmp_path)
    assert passed is True
    assert "review.status PASS" in detail
    assert "merge allowed" in detail


# --- PASS_WITH_WARNINGS requires signoff ---


def test_pass_with_warnings_passes_with_signoff(tmp_path: Path) -> None:
    """PASS_WITH_WARNINGS requires both warningsAcknowledged and ownerSignoffPresent."""
    issue = 1569
    status_dir = tmp_path / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    path = status_dir / f"issue-{issue}.json"
    payload = {
        "issue": issue,
        "wave": None,
        "review": {
            "status": "PASS_WITH_WARNINGS",
            "artifactRef": (
                f"git-history:agent-runtime/artifacts/reviews/review-issue-{issue}.json"
            ),
            "sha256": "a" * 64,
            "warningsAcknowledged": True,
            "ownerSignoffPresent": True,
        },
        "validation": {
            "status": "PASS",
            "artifactRef": (
                f"git-history:agent-runtime/artifacts/validation/validation-issue-{issue}.json"
            ),
            "sha256": "b" * 64,
        },
        "gateVersion": 1,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    passed, detail = evaluate(issue, status_dir=status_dir)
    assert passed is True
    assert "PASS_WITH_WARNINGS" in detail


def test_pass_with_warnings_fails_without_signoff(tmp_path: Path) -> None:
    """PASS_WITH_WARNINGS without full signoff blocks merge."""
    issue = 1569
    status_dir = tmp_path / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    path = status_dir / f"issue-{issue}.json"
    payload = {
        "issue": issue,
        "wave": None,
        "review": {
            "status": "PASS_WITH_WARNINGS",
            "artifactRef": (
                f"git-history:agent-runtime/artifacts/reviews/review-issue-{issue}.json"
            ),
            "sha256": "a" * 64,
            "warningsAcknowledged": False,  # Missing full signoff
            "ownerSignoffPresent": False,
        },
        "validation": {
            "status": "PASS",
            "artifactRef": (
                f"git-history:agent-runtime/artifacts/validation/validation-issue-{issue}.json"
            ),
            "sha256": "b" * 64,
        },
        "gateVersion": 1,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    passed, detail = evaluate(issue, status_dir=status_dir)
    assert passed is False
    assert "warningsAcknowledged" in detail


# --- Fail-closed: missing or malformed record ---


def test_fails_when_record_missing(tmp_path: Path) -> None:
    """Missing record blocks merge with clear error."""
    issue = 1569
    passed, detail = evaluate(issue, status_dir=tmp_path)
    assert passed is False
    assert "missing" in detail.lower()
    assert f"issue-{issue}.json" in detail


def test_fails_when_json_malformed(tmp_path: Path) -> None:
    """Malformed JSON blocks merge."""
    issue = 1569
    status_dir = tmp_path / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    path = status_dir / f"issue-{issue}.json"
    path.write_text("{not valid json", encoding="utf-8")

    passed, detail = evaluate(issue, status_dir=status_dir)
    assert passed is False
    assert "not valid JSON" in detail


def test_fails_when_record_unreadable(tmp_path: Path, monkeypatch) -> None:
    """Unreadable record blocks merge."""
    issue = 1569
    status_dir = tmp_path / "status"
    record_path = _write_record(status_dir, issue)
    original_read_bytes = Path.read_bytes

    def _raise(self: Path):
        if self == record_path:
            raise OSError("permission denied (simulated)")
        return original_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", _raise)
    passed, detail = evaluate(issue, status_dir=status_dir)
    assert passed is False
    assert "could not read" in detail
