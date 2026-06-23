from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "ci"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "validate"))

from common import (  # noqa: E402
    build_review_artifact,
    criterion_matches_test,
    derive_review_status,
    effective_mandatory_fail_reasons,
    finalize_review_artifact,
    finding_is_acknowledged,
    legacy_warning_to_finding,
    mandatory_fail_reasons,
    merge_override_active,
    ml_gates_satisfied,
    normalize_review_findings,
    overridden_merge_valid,
    owner_signoff_valid,
    review_status_issues,
    reviewer_signoff_valid,
    unacknowledged_findings,
)
from check_review_artifact import run_check as run_review_check  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "scripts" / "validate"))
from check_critical_findings_resolved import run_check as run_critical_check  # noqa: E402
from check_findings_acknowledged import run_check as run_ack_check  # noqa: E402
from check_ml_gates import run_check as run_ml_gates_check  # noqa: E402
from check_owner_signoff import run_check as run_owner_signoff_check  # noqa: E402
from check_reviewer_signoff import run_check as run_reviewer_signoff_check  # noqa: E402


def _write_review_artifact(tmp_path: Path, review: dict) -> None:
    issue = review["issue"]
    review_path = tmp_path / "artifacts" / "reviews" / f"review-issue-{issue}.json"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(__import__("json").dumps(review), encoding="utf-8")


def _patch_reviews_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import common

    reviews_dir = tmp_path / "artifacts" / "reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(common, "REVIEWS_DIR", reviews_dir)


def test_criterion_matches_test_rejects_single_token_overlap() -> None:
    assert criterion_matches_test("No TikTok API calls", "test_has_no_tiktok") is False


def test_criterion_matches_test_accepts_criterion_suffix_in_test_name() -> None:
    assert criterion_matches_test(
        "No TikTok API calls",
        "test_ad_performance_trainer_has_no_tiktok_api_calls",
    )


def test_criterion_matches_test_accepts_multi_token_overlap() -> None:
    assert criterion_matches_test(
        "CLI train writes metrics JSON including ROAS MAPE on held-out window",
        "test_train_writes_roas_mape_metrics_json",
    )


def test_legacy_warning_migrates_to_critical_findings() -> None:
    artifact = {
        "status": "PASS",
        "criticalFindings": [],
        "warnings": [
            {
                "severity": "WARNING",
                "domain": "Observability",
                "location": "web/src/lib/services/home.ts",
                "message": "errors swallowed",
            }
        ],
    }
    findings = normalize_review_findings(artifact)
    assert len(findings) == 1
    assert findings[0]["severity"] == "WARNING"
    assert findings[0]["type"] == "other"
    assert findings[0]["description"] == (
        "web/src/lib/services/home.ts — errors swallowed"
    )
    assert derive_review_status(findings) == "PASS_WITH_WARNINGS"


def test_review_status_issues_flags_legacy_warnings_and_pass_mismatch() -> None:
    artifact = {
        "status": "PASS",
        "criticalFindings": [],
        "warnings": [{"message": "provisional threshold", "severity": "WARNING"}],
    }
    issues = review_status_issues(artifact)
    assert issues == [
        "legacy warnings[] has 1 entry; migrate to criticalFindings and set status via generate_review_artifact.py",
        "status 'PASS' does not match derived 'PASS_WITH_WARNINGS' (warnings=1, critical=0)",
    ]


def test_finalize_review_artifact_aligns_status() -> None:
    artifact = {
        "id": "review-issue-95",
        "issue": 95,
        "status": "PASS",
        "criticalFindings": [],
        "warnings": [
            {"severity": "WARNING", "message": "swallowed API errors"},
            {"severity": "WARNING", "message": "done.md title stale"},
        ],
        "modulesTouched": ["web"],
        "testCoverage": {
            "acceptance": {"total": 1, "mapped": 1, "mappings": []},
            "unit": {"passed": 1, "failed": 0},
        },
    }
    finalized = finalize_review_artifact(artifact)
    assert finalized["status"] == "PASS_WITH_WARNINGS"
    assert "warnings" not in finalized
    assert len(finalized["criticalFindings"]) == 2
    assert finalized["reviewFailures"] == 0
    assert finalized["severity"] == "medium"


def test_critical_finding_requires_fail() -> None:
    findings = [{"severity": "CRITICAL", "description": "N+1 query"}]
    assert derive_review_status(findings) == "FAIL"


def test_action_required_requires_fail() -> None:
    findings = [{"severity": "WARNING", "actionRequired": True, "description": "fix me"}]
    assert derive_review_status(findings) == "FAIL"


@pytest.mark.parametrize(
    ("findings", "expected_status"),
    [
        ([], "PASS"),
        ([{"severity": "INFO", "description": "note"}], "PASS"),
        ([{"severity": "WARNING", "description": "warn"}], "PASS_WITH_WARNINGS"),
        ([{"severity": "CRITICAL", "description": "block"}], "FAIL"),
        (
            [
                {"severity": "WARNING", "description": "warn"},
                {"severity": "CRITICAL", "description": "block"},
            ],
            "FAIL",
        ),
        (
            [{"severity": "INFO", "actionRequired": True, "description": "fix"}],
            "FAIL",
        ),
    ],
    ids=[
        "empty",
        "info_only",
        "warning_only",
        "critical_only",
        "critical_over_warning",
        "action_required",
    ],
)
def test_derive_review_status_matrix(
    findings: list[dict[str, object]], expected_status: str
) -> None:
    assert derive_review_status(findings) == expected_status


@pytest.mark.parametrize(
    ("severity", "expected_structural_pass"),
    [
        ("CRITICAL", True),
        ("WARNING", True),
    ],
)
def test_run_check_respects_review_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    severity: str,
    expected_structural_pass: bool,
) -> None:
    review = {
        "id": "review-issue-1",
        "issue": 1,
        "status": "PASS_WITH_WARNINGS" if severity == "WARNING" else "FAIL",
        "criticalFindings": [{"severity": severity, "description": "issue"}],
        "modulesTouched": ["web"],
        "testCoverage": {
            "acceptance": {"total": 1, "mapped": 1, "mappings": []},
        },
    }
    _write_review_artifact(tmp_path, review)
    _patch_reviews_dir(tmp_path, monkeypatch)
    passed, message, details = run_review_check(1)
    assert passed is expected_structural_pass
    if severity == "WARNING":
        assert "gating warning" in message
        assert details["status"] == "PASS_WITH_WARNINGS"
        assert details["derivedStatus"] == "PASS_WITH_WARNINGS"
        assert details["warningCount"] == 1
        critical_passed, _, _ = run_critical_check(1)
        assert critical_passed is True
    else:
        critical_passed, _, _ = run_critical_check(1)
        assert critical_passed is False


def test_critical_check_fails_on_fail_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    review = {
        "id": "review-issue-9",
        "issue": 9,
        "status": "FAIL",
        "criticalFindings": [{"severity": "CRITICAL", "description": "blocker"}],
        "modulesTouched": ["web"],
        "testCoverage": {
            "acceptance": {"total": 0, "mapped": 0, "mappings": []},
        },
    }
    _write_review_artifact(tmp_path, review)
    _patch_reviews_dir(tmp_path, monkeypatch)
    passed, message, details = run_critical_check(9)
    assert passed is False
    assert "FAIL" in message
    assert details["status"] == "FAIL"


def test_run_check_passes_when_artifact_aligned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    review = {
        "id": "review-issue-42",
        "issue": 42,
        "status": "PASS",
        "criticalFindings": [],
        "modulesTouched": ["web"],
        "testCoverage": {
            "acceptance": {"total": 0, "mapped": 0, "mappings": []},
        },
    }
    _write_review_artifact(tmp_path, review)
    _patch_reviews_dir(tmp_path, monkeypatch)
    passed, message, details = run_review_check(42)
    assert passed is True
    assert "status PASS" in message
    assert details == {"status": "PASS", "derivedStatus": "PASS", "warningCount": 0}


def test_run_check_rejects_legacy_warnings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    review = {
        "id": "review-issue-7",
        "issue": 7,
        "status": "PASS_WITH_WARNINGS",
        "criticalFindings": [],
        "warnings": [{"severity": "WARNING", "message": "stale field"}],
        "modulesTouched": ["web"],
        "testCoverage": {
            "acceptance": {"total": 0, "mapped": 0, "mappings": []},
        },
    }
    _write_review_artifact(tmp_path, review)
    _patch_reviews_dir(tmp_path, monkeypatch)
    passed, message, details = run_review_check(7)
    assert passed is False
    assert message.startswith("legacy warnings[] has 1 entry")
    assert "issues" in details


def test_run_check_rejects_status_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    review = {
        "id": "review-issue-8",
        "issue": 8,
        "status": "PASS",
        "criticalFindings": [{"severity": "WARNING", "description": "warn"}],
        "modulesTouched": ["web"],
        "testCoverage": {
            "acceptance": {"total": 0, "mapped": 0, "mappings": []},
        },
    }
    _write_review_artifact(tmp_path, review)
    _patch_reviews_dir(tmp_path, monkeypatch)
    passed, message, _ = run_review_check(8)
    assert passed is False
    assert message == (
        "status 'PASS' does not match derived 'PASS_WITH_WARNINGS' (warnings=1, critical=0)"
    )


def test_critical_check_rejects_nonzero_review_failures_with_pass_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    review = {
        "id": "review-issue-11",
        "issue": 11,
        "status": "PASS_WITH_WARNINGS",
        "reviewFailures": 1,
        "criticalFindings": [{"severity": "WARNING", "description": "warn"}],
        "modulesTouched": ["web"],
        "testCoverage": {
            "acceptance": {"total": 0, "mapped": 0, "mappings": []},
        },
    }
    _write_review_artifact(tmp_path, review)
    _patch_reviews_dir(tmp_path, monkeypatch)
    passed, message, details = run_critical_check(11)
    assert passed is False
    assert "reviewFailures is 1" in message


def test_finalize_review_artifact_counts_action_required_as_failure() -> None:
    artifact = {
        "id": "review-issue-10",
        "issue": 10,
        "status": "PASS",
        "criticalFindings": [
            {"severity": "WARNING", "actionRequired": True, "description": "must fix"}
        ],
        "modulesTouched": ["web"],
        "testCoverage": {
            "acceptance": {"total": 0, "mapped": 0, "mappings": []},
            "unit": {"passed": 1, "failed": 0},
        },
    }
    finalized = finalize_review_artifact(artifact)
    assert finalized["status"] == "FAIL"
    assert finalized["reviewFailures"] == 1
    assert finalized["severity"] == "medium"


def test_legacy_warning_to_finding_maps_domain() -> None:
    finding = legacy_warning_to_finding(
        {"domain": "security", "message": "key in default param", "location": "connectors/tiktok.py"}
    )
    assert finding["type"] == "security"
    assert finding["severity"] == "WARNING"
    assert "tiktok.py" in finding["description"]


def test_build_review_artifact_preserves_existing_content() -> None:
    existing = {
        "id": "review-issue-118",
        "issue": 118,
        "timestamp": "2026-06-05T20:00:00Z",
        "summary": "Seller home shell with persona switcher",
        "modulesTouched": ["web"],
        "testCoverage": {
            "acceptance": {
                "total": 7,
                "mapped": 7,
                "unmapped": [],
                "mappings": [{"criterion": "AC1", "test": "web/src/__tests__/test_a.tsx::ac1"}],
            },
            "unit": {"passed": 158, "failed": 0},
        },
    }
    artifact = build_review_artifact(118, existing=existing, update_timestamp=False)
    assert artifact["summary"] == "Seller home shell with persona switcher"
    assert artifact["modulesTouched"] == ["web"]
    assert artifact["testCoverage"]["acceptance"]["total"] == 7
    assert artifact["testCoverage"]["unit"]["passed"] == 158
    assert artifact["timestamp"] == "2026-06-05T20:00:00Z"
    assert artifact["schemaVersion"] == "1.0.0"


def test_build_review_artifact_applies_overrides_with_deep_merge() -> None:
    existing = {
        "issue": 95,
        "summary": "keep unless overridden",
        "testCoverage": {
            "acceptance": {"total": 5, "mapped": 5, "unmapped": [], "mappings": []},
            "unit": {"passed": 10, "failed": 0},
        },
    }
    overrides = {
        "criticalFindings": [
            {"severity": "WARNING", "type": "other", "description": "swallowed API errors"}
        ],
        "testCoverage": {"unit": {"failed": 1}},
    }
    artifact = build_review_artifact(95, existing=existing, overrides=overrides)
    assert artifact["summary"] == "keep unless overridden"
    assert artifact["status"] == "FAIL"
    assert artifact["testCoverage"]["acceptance"]["total"] == 5
    assert artifact["testCoverage"]["unit"]["failed"] == 1
    assert artifact["testCoverage"]["unit"]["passed"] == 10


def test_finding_is_acknowledged_requires_dual_signoff_and_resolution() -> None:
    assert finding_is_acknowledged(
        {
            "acceptanceByReviewer": True,
            "ownerAck": True,
            "fixedInCommit": "abc123",
        }
    )
    assert finding_is_acknowledged(
        {
            "acceptanceByReviewer": True,
            "ownerAck": True,
            "shipAsIsReason": "documented in ADR-017",
        }
    )
    assert not finding_is_acknowledged(
        {"acceptanceByReviewer": True, "ownerAck": False, "fixedInCommit": "abc123"}
    )


def test_unacknowledged_findings_blocks_pass_with_warnings_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    review = {
        "id": "review-issue-50",
        "issue": 50,
        "status": "PASS_WITH_WARNINGS",
        "criticalFindings": [
            {"severity": "WARNING", "description": "N+1 query"},
        ],
        "modulesTouched": ["web"],
        "testCoverage": {
            "acceptance": {"total": 0, "mapped": 0, "mappings": []},
        },
    }
    _write_review_artifact(tmp_path, review)
    _patch_reviews_dir(tmp_path, monkeypatch)
    ack_passed, _, _ = run_ack_check(50)
    reviewer_passed, _, _ = run_reviewer_signoff_check(50)
    owner_passed, _, _ = run_owner_signoff_check(50)
    assert ack_passed is False
    assert reviewer_passed is False
    assert owner_passed is False


def test_gated_warnings_merge_when_fully_acknowledged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    review = {
        "id": "review-issue-51",
        "issue": 51,
        "status": "PASS_WITH_WARNINGS",
        "criticalFindings": [
            {
                "severity": "WARNING",
                "description": "N+1 query",
                "acceptanceByReviewer": True,
                "ownerAck": True,
                "shipAsIsReason": "acceptable at current scale",
            }
        ],
        "reviewerSignoff": {
            "statement": "I reviewed and accepted these risks",
            "timestamp": "2026-06-23T12:00:00Z",
            "acceptedRisks": True,
        },
        "ownerSignoff": {
            "statement": "I acknowledge and will fix",
            "timestamp": "2026-06-23T12:05:00Z",
            "acknowledged": True,
        },
        "modulesTouched": ["web"],
        "testCoverage": {
            "acceptance": {"total": 0, "mapped": 0, "mappings": []},
        },
    }
    _write_review_artifact(tmp_path, review)
    _patch_reviews_dir(tmp_path, monkeypatch)
    assert run_ack_check(51)[0] is True
    assert run_reviewer_signoff_check(51)[0] is True
    assert run_owner_signoff_check(51)[0] is True
    assert run_critical_check(51)[0] is True


def test_mandatory_fail_reasons_include_test_regression() -> None:
    artifact = {
        "criticalFindings": [],
        "modulesTouched": ["web"],
        "testCoverage": {
            "acceptance": {"total": 2, "mapped": 2, "unmapped": []},
            "unit": {"passed": 3, "failed": 1},
        },
    }
    reasons = mandatory_fail_reasons(artifact)
    assert any("test regression" in r for r in reasons)
    assert derive_review_status([], artifact) == "FAIL"


def test_ml_gates_required_for_ml_modules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    review = {
        "id": "review-issue-140",
        "issue": 140,
        "status": "PASS_WITH_WARNINGS",
        "criticalFindings": [{"severity": "WARNING", "description": "fixture note"}],
        "modulesTouched": ["src/modules/ml/ad_performance"],
        "testCoverage": {
            "acceptance": {"total": 1, "mapped": 1, "mappings": []},
        },
    }
    ok, problems = ml_gates_satisfied(review)
    assert ok is False
    assert problems
    _write_review_artifact(tmp_path, review)
    _patch_reviews_dir(tmp_path, monkeypatch)
    assert run_ml_gates_check(140)[0] is False

    review["mlGates"] = {
        "coldStartThresholdDocumented": True,
        "promotionGateDocumented": True,
    }
    _write_review_artifact(tmp_path, review)
    assert run_ml_gates_check(140)[0] is True


def test_reviewer_and_owner_signoff_helpers() -> None:
    review = {"status": "PASS_WITH_WARNINGS"}
    assert reviewer_signoff_valid(review)[0] is False
    assert owner_signoff_valid(review)[0] is False
    review["reviewerSignoff"] = {
        "statement": "I reviewed and accepted these risks",
        "timestamp": "2026-06-23T12:00:00Z",
        "acceptedRisks": True,
    }
    review["ownerSignoff"] = {
        "statement": "I acknowledge and will fix",
        "timestamp": "2026-06-23T12:05:00Z",
        "acknowledged": True,
    }
    assert reviewer_signoff_valid(review)[0] is True
    assert owner_signoff_valid(review)[0] is True


def test_unacknowledged_findings_helper() -> None:
    findings = [
        {"severity": "WARNING", "description": "a"},
        {
            "severity": "WARNING",
            "description": "b",
            "acceptanceByReviewer": True,
            "ownerAck": True,
            "fixedInCommit": "abc",
        },
    ]
    assert len(unacknowledged_findings(findings)) == 1


def test_deep_merge_under_merges_nested_dicts() -> None:
    from common import deep_merge_under

    base = {"testCoverage": {"acceptance": {"total": 5, "mapped": 5}, "unit": {"passed": 1}}}
    overlay = {"testCoverage": {"unit": {"failed": 2}}}
    merged = deep_merge_under(base, overlay)
    assert merged["testCoverage"]["acceptance"]["total"] == 5
    assert merged["testCoverage"]["unit"]["failed"] == 2
    assert merged["testCoverage"]["unit"]["passed"] == 1


def test_critical_security_pass_status_fails_critical_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    review = {
        "id": "review-issue-999",
        "issue": 999,
        "status": "PASS",
        "criticalFindings": [
            {
                "severity": "CRITICAL",
                "type": "security",
                "description": "Hardcoded API key in code",
            }
        ],
        "modulesTouched": ["web"],
        "testCoverage": {
            "acceptance": {"total": 0, "mapped": 0, "unmapped": [], "mappings": []},
            "unit": {"passed": 0, "failed": 0},
        },
    }
    _write_review_artifact(tmp_path, review)
    _patch_reviews_dir(tmp_path, monkeypatch)
    passed, message, details = run_critical_check(999)
    assert passed is False
    assert "CRITICAL security finding" in message
    assert details["derivedStatus"] == "FAIL"


def test_mixed_findings_one_unacknowledged_blocks_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    review = {
        "id": "review-issue-300",
        "issue": 300,
        "status": "PASS_WITH_WARNINGS",
        "criticalFindings": [
            {
                "severity": "WARNING",
                "description": "N+1",
                "acceptanceByReviewer": True,
                "ownerAck": True,
                "shipAsIsReason": "ok",
            },
            {
                "severity": "WARNING",
                "description": "ML threshold",
                "acceptanceByReviewer": False,
                "ownerAck": True,
                "shipAsIsReason": "will fix in hotfix",
            },
        ],
        "reviewerSignoff": {
            "statement": "reviewed",
            "timestamp": "2026-06-23T12:00:00Z",
            "acceptedRisks": True,
        },
        "ownerSignoff": {
            "statement": "ack",
            "timestamp": "2026-06-23T12:05:00Z",
            "acknowledged": True,
        },
        "modulesTouched": ["web"],
        "testCoverage": {
            "acceptance": {"total": 0, "mapped": 0, "unmapped": [], "mappings": []},
            "unit": {"passed": 0, "failed": 0},
        },
    }
    _write_review_artifact(tmp_path, review)
    _patch_reviews_dir(tmp_path, monkeypatch)
    ack_passed, message, _ = run_ack_check(300)
    assert ack_passed is False
    assert "1 WARNING finding(s) missing" in message


def test_overridden_merge_allows_ml_gate_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    review = {
        "id": "review-issue-301",
        "issue": 301,
        "status": "FAIL",
        "criticalFindings": [],
        "modulesTouched": ["src/modules/ml/ad_performance"],
        "testCoverage": {
            "acceptance": {"total": 1, "mapped": 1, "unmapped": [], "mappings": []},
            "unit": {"passed": 1, "failed": 0},
        },
        "overriddenMerge": {
            "timestamp": "2026-06-24T08:15:00Z",
            "overriddenBy": "thien@juli.ai",
            "reason": "Production incident hotfix",
            "incidentLink": "INC-789",
        },
    }
    assert mandatory_fail_reasons(review)
    assert not effective_mandatory_fail_reasons(review)
    assert merge_override_active(review)
    _write_review_artifact(tmp_path, review)
    _patch_reviews_dir(tmp_path, monkeypatch)
    passed, message, details = run_critical_check(301)
    assert passed is True
    assert details["mergeOverrideActive"] is True
    assert "overridden" in message.lower()


def test_overridden_merge_rejects_security_fail() -> None:
    review = {
        "criticalFindings": [
            {"type": "security", "severity": "CRITICAL", "description": "key leak"}
        ],
        "modulesTouched": ["web"],
        "testCoverage": {
            "acceptance": {"total": 0, "mapped": 0, "unmapped": []},
            "unit": {"passed": 0, "failed": 0},
        },
        "overriddenMerge": {
            "timestamp": "2026-06-24T08:15:00Z",
            "overriddenBy": "thien@juli.ai",
            "reason": "hotfix",
            "incidentLink": "INC-789",
        },
    }
    assert effective_mandatory_fail_reasons(review)
    assert not merge_override_active(review)


def test_overridden_merge_requires_all_fields() -> None:
    review = {"overriddenMerge": {"reason": "missing fields"}}
    valid, issue = overridden_merge_valid(review)
    assert valid is False
    assert "missing" in issue


def test_ml_gates_scan_source_thresholds() -> None:
    review = {
        "modulesTouched": ["src/modules/ml/ad_performance"],
        "mlGates": {
            "coldStartThresholdDocumented": True,
            "promotionGateDocumented": True,
        },
    }
    ok, problems = ml_gates_satisfied(review)
    assert ok is True
    assert problems == []


def test_ml_gates_fail_when_source_constants_missing() -> None:
    review = {
        "modulesTouched": ["src/modules/ml/ad_performance"],
        "mlGates": {
            "coldStartThresholdDocumented": True,
            "promotionGateDocumented": True,
            "thresholds": {"NONEXISTENT_CONSTANT": 99},
        },
    }
    ok, problems = ml_gates_satisfied(review)
    assert ok is False
    assert any("NONEXISTENT_CONSTANT" in p for p in problems)


def test_reviewer_signoff_without_per_finding_acceptance_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    review = {
        "id": "review-issue-302",
        "issue": 302,
        "status": "PASS_WITH_WARNINGS",
        "criticalFindings": [
            {"severity": "WARNING", "description": "warn", "ownerAck": True, "shipAsIsReason": "ok"}
        ],
        "reviewerSignoff": {
            "statement": "reviewed",
            "timestamp": "2026-06-23T12:00:00Z",
            "acceptedRisks": True,
        },
        "ownerSignoff": {
            "statement": "ack",
            "timestamp": "2026-06-23T12:05:00Z",
            "acknowledged": True,
        },
        "modulesTouched": ["web"],
        "testCoverage": {
            "acceptance": {"total": 0, "mapped": 0, "unmapped": [], "mappings": []},
            "unit": {"passed": 0, "failed": 0},
        },
    }
    _write_review_artifact(tmp_path, review)
    _patch_reviews_dir(tmp_path, monkeypatch)
    assert run_reviewer_signoff_check(302)[0] is True
    assert run_ack_check(302)[0] is False
