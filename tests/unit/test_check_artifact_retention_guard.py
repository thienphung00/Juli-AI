"""Unit tests for the issue-tier artifact retention guard (#1064).

Design correction (issue #1064 comment "Design correction before implementation"):
CI cannot upload implementation artifacts because they are gitignored and never reach
the pushed branch. What CI *can* see is the committed compact status record at
``agent-runtime/artifacts/status/issue-<N>.json`` (ADR-052's #670 amendment). This guard
fails an issue-tier PR when that record is absent or not PASS, and it must never pass
because it could not determine an answer -- every unreadable/malformed/schema-invalid
path is a FAIL, never a silent pass.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(CI_DIR))

from check_artifact_retention_guard import (  # noqa: E402
    GENERATE_COMMAND,
    evaluate,
    parse_issue_number,
    status_record_path,
)


def _write_record(
    status_dir: Path,
    issue: int,
    *,
    payload: dict | None = None,
    raw_text: str | None = None,
    review_status: str = "PASS",
    validation_status: str = "PASS",
    record_issue: int | None = None,
) -> Path:
    status_dir.mkdir(parents=True, exist_ok=True)
    path = status_dir / f"issue-{issue}.json"
    if raw_text is not None:
        path.write_text(raw_text, encoding="utf-8")
        return path
    if payload is None:
        payload = {
            "issue": record_issue if record_issue is not None else issue,
            "wave": None,
            "review": {
                "status": review_status,
                "artifactRef": (
                    f"git-history:agent-runtime/artifacts/reviews/review-issue-{issue}.json"
                ),
                "sha256": "a" * 64,
            },
            "validation": {
                "status": validation_status,
                "artifactRef": (
                    f"git-history:agent-runtime/artifacts/validation/validation-issue-{issue}.json"
                ),
                "sha256": "b" * 64,
            },
            "gateVersion": 1,
        }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# --- parse_issue_number: the SKIP signal for docs/hotfix/non-issue branches ---


@pytest.mark.parametrize(
    "raw",
    [None, "", "   ", "abc", "0", "-1", "12.5"],
)
def test_parse_issue_number_returns_none_for_non_issue_input(raw) -> None:
    assert parse_issue_number(raw) is None


def test_parse_issue_number_parses_a_real_issue_number() -> None:
    assert parse_issue_number("1064") == 1064
    assert parse_issue_number(" 1064 ") == 1064


# --- Revised acceptance criteria ---


def test_fails_with_missing_path_and_producing_command_when_record_absent(
    tmp_path: Path,
) -> None:
    passed, detail = evaluate(1064, status_dir=tmp_path)
    assert passed is False
    assert str(status_record_path(1064, tmp_path)) in detail
    assert GENERATE_COMMAND in detail


def test_passes_once_a_pass_record_is_committed(tmp_path: Path) -> None:
    _write_record(tmp_path, 1064, review_status="PASS", validation_status="PASS")
    passed, detail = evaluate(1064, status_dir=tmp_path)
    assert passed is True
    assert "PASS" in detail


def test_fails_and_names_the_gate_when_review_not_pass(tmp_path: Path) -> None:
    _write_record(tmp_path, 1064, review_status="FAIL", validation_status="PASS")
    passed, detail = evaluate(1064, status_dir=tmp_path)
    assert passed is False
    assert "review" in detail.lower()
    assert "FAIL" in detail


def test_fails_and_names_the_gate_when_validation_not_pass(tmp_path: Path) -> None:
    _write_record(tmp_path, 1064, review_status="PASS", validation_status="FAIL")
    passed, detail = evaluate(1064, status_dir=tmp_path)
    assert passed is False
    assert "validation" in detail.lower()
    assert "FAIL" in detail


def test_fails_when_review_is_pass_with_warnings_not_exact_pass(tmp_path: Path) -> None:
    _write_record(tmp_path, 1064, review_status="PASS_WITH_WARNINGS", validation_status="PASS")
    passed, detail = evaluate(1064, status_dir=tmp_path)
    assert passed is False
    assert "review" in detail.lower()


# --- Fail-closed: never pass because it could not determine an answer ---


def test_fails_when_json_is_malformed(tmp_path: Path) -> None:
    _write_record(tmp_path, 1064, raw_text="{not valid json")
    passed, detail = evaluate(1064, status_dir=tmp_path)
    assert passed is False
    assert "not valid JSON" in detail


def test_fails_when_record_is_not_a_json_object(tmp_path: Path) -> None:
    _write_record(tmp_path, 1064, raw_text="[1, 2, 3]")
    passed, detail = evaluate(1064, status_dir=tmp_path)
    assert passed is False


def test_fails_when_schema_is_violated(tmp_path: Path) -> None:
    # Missing required "gateVersion" and malformed sha256 -> schema-invalid.
    _write_record(
        tmp_path,
        1064,
        payload={
            "issue": 1064,
            "review": {"status": "PASS", "artifactRef": "x", "sha256": "not-a-sha"},
            "validation": {"status": "PASS", "artifactRef": "x", "sha256": "b" * 64},
        },
    )
    passed, detail = evaluate(1064, status_dir=tmp_path)
    assert passed is False
    assert "schema" in detail.lower()


def test_fails_when_review_or_validation_object_missing(tmp_path: Path) -> None:
    _write_record(
        tmp_path,
        1064,
        payload={
            "issue": 1064,
            "review": {"status": "PASS", "artifactRef": "x", "sha256": "a" * 64},
            "gateVersion": 1,
        },
    )
    passed, detail = evaluate(1064, status_dir=tmp_path)
    assert passed is False


def test_fails_when_status_record_issue_field_mismatches(tmp_path: Path) -> None:
    _write_record(tmp_path, 1064, record_issue=999)
    passed, detail = evaluate(1064, status_dir=tmp_path)
    assert passed is False
    assert "999" in detail


def test_fails_when_record_is_unreadable(tmp_path: Path, monkeypatch) -> None:
    record_path = _write_record(tmp_path, 1064)
    original_read_bytes = Path.read_bytes

    def _raise(self: Path):
        if self == record_path:
            raise OSError("permission denied (simulated)")
        return original_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", _raise)
    passed, detail = evaluate(1064, status_dir=tmp_path)
    assert passed is False
    assert "could not read" in detail


@pytest.mark.parametrize(
    "setup",
    [
        "missing",
        "malformed_json",
        "not_an_object",
        "missing_gate_version",
        "review_not_pass",
        "validation_not_pass",
        "issue_mismatch",
    ],
)
def test_fail_closed_never_passes_when_it_cannot_determine_an_answer(
    tmp_path: Path, setup: str
) -> None:
    """The one property this whole guard exists to guarantee: no code path
    returns passed=True without having read a genuine PASS/PASS record for
    the right issue. Every ambiguous or broken input must FAIL, not pass."""
    issue = 1064
    if setup == "missing":
        pass  # no file written at all
    elif setup == "malformed_json":
        _write_record(tmp_path, issue, raw_text="{{{not json")
    elif setup == "not_an_object":
        _write_record(tmp_path, issue, raw_text="null")
    elif setup == "missing_gate_version":
        _write_record(
            tmp_path,
            issue,
            payload={
                "issue": issue,
                "review": {"status": "PASS", "artifactRef": "x", "sha256": "a" * 64},
                "validation": {
                    "status": "PASS",
                    "artifactRef": "x",
                    "sha256": "b" * 64,
                },
            },
        )
    elif setup == "review_not_pass":
        _write_record(tmp_path, issue, review_status="FAIL")
    elif setup == "validation_not_pass":
        _write_record(tmp_path, issue, validation_status="FAIL")
    elif setup == "issue_mismatch":
        _write_record(tmp_path, issue, record_issue=1)

    passed, detail = evaluate(issue, status_dir=tmp_path)
    assert passed is False
    assert detail  # a reason is always given -- no silent skip/fail
