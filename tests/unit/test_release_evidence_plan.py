"""Unit tests for releaseEvidencePlan schema validation (#513 / META-1)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(CI_DIR))

from release_evidence_plan import (  # noqa: E402
    REQUIRED_TOP_LEVEL_FIELDS,
    validate_release_evidence_plan,
)


def _valid_plan() -> dict:
    return {
        "planId": "rep-513-abc",
        "affectedPublicSurfaces": ["demo.app-juli.com"],
        "candidateVerificationJourney": {
            "mode": "candidate_verification",
            "stableTrafficPercent": 100,
            "candidatePublicTrafficPercent": 0,
            "restrictedRoute": "test listener :8443",
            "syntheticShopRequired": True,
            "workersDisabledOnCandidate": True,
            "journeys": [
                {
                    "name": "demo-home-styled",
                    "entryUrl": "/",
                    "assertions": ["html_200", "css_assets_200"],
                }
            ],
        },
        "staticAssetChecks": {
            "required": True,
            "htmlRoutes": ["/"],
            "discoverFromHtml": True,
            "assetTypes": ["css", "js"],
            "failOnMissing": True,
            "failOnNon200": True,
        },
        "migrationCompatibility": {
            "schemaChangeInScope": False,
            "expandContractOnly": True,
            "stableAndCandidateCompatible": True,
            "destructiveMigrationAllowed": False,
            "notes": "No schema change",
        },
        "rollbackAssertion": {
            "preCutoverFailureBehavior": "discard_candidate_keep_stable",
            "postCutoverFailureBehavior": "restore_stable_listener",
            "retainedStableRequired": True,
            "automatic": True,
        },
        "requiredArtifacts": {
            "implementation": True,
            "intentReview": True,
            "review": True,
            "validation": True,
            "releaseMetadataHonest": True,
        },
        "acceptanceCommands": [
            "pytest tests/unit/test_release_evidence_plan.py -q",
        ],
        "doNotInfer": [
            "release evidence fields",
            "smoke asset lists",
            "rollback behavior",
        ],
    }


def test_valid_plan_passes() -> None:
    result = validate_release_evidence_plan(_valid_plan())
    assert result["valid"] is True
    assert result["missingFields"] == []
    assert result["errors"] == []


@pytest.mark.parametrize("field", REQUIRED_TOP_LEVEL_FIELDS)
def test_each_missing_required_field_fails(field: str) -> None:
    plan = _valid_plan()
    del plan[field]
    result = validate_release_evidence_plan(plan)
    assert result["valid"] is False
    assert field in result["missingFields"]


def test_empty_affected_surfaces_fails() -> None:
    plan = _valid_plan()
    plan["affectedPublicSurfaces"] = []
    result = validate_release_evidence_plan(plan)
    assert result["valid"] is False
    assert "affectedPublicSurfaces" in result["missingFields"] or any(
        "affectedPublicSurfaces" in e for e in result["errors"]
    )


def test_empty_plan_id_fails() -> None:
    plan = _valid_plan()
    plan["planId"] = ""
    result = validate_release_evidence_plan(plan)
    assert result["valid"] is False
    assert "planId" in result["missingFields"] or any("planId" in e for e in result["errors"])


def test_candidate_public_traffic_nonzero_fails() -> None:
    plan = _valid_plan()
    plan["candidateVerificationJourney"]["candidatePublicTrafficPercent"] = 5
    result = validate_release_evidence_plan(plan)
    assert result["valid"] is False
    assert any("candidatePublicTrafficPercent" in e for e in result["errors"])


def test_destructive_migration_allowed_fails() -> None:
    plan = _valid_plan()
    plan["migrationCompatibility"]["destructiveMigrationAllowed"] = True
    result = validate_release_evidence_plan(plan)
    assert result["valid"] is False
    assert any("destructiveMigrationAllowed" in e for e in result["errors"])


def test_schema_change_requires_expand_contract() -> None:
    plan = _valid_plan()
    plan["migrationCompatibility"]["schemaChangeInScope"] = True
    plan["migrationCompatibility"]["expandContractOnly"] = False
    result = validate_release_evidence_plan(plan)
    assert result["valid"] is False
    assert any("expandContractOnly" in e for e in result["errors"])


def test_workers_not_disabled_when_api_side_effects_fails() -> None:
    plan = _valid_plan()
    journey = plan["candidateVerificationJourney"]
    journey["workersDisabledOnCandidate"] = False
    journey["apiSideEffectsInScope"] = True
    result = validate_release_evidence_plan(plan)
    assert result["valid"] is False
    assert any("workersDisabledOnCandidate" in e for e in result["errors"])


def test_none_plan_reports_all_required_missing() -> None:
    result = validate_release_evidence_plan(None)
    assert result["valid"] is False
    for field in REQUIRED_TOP_LEVEL_FIELDS:
        assert field in result["missingFields"]
