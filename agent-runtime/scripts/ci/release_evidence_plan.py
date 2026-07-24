"""Validate releaseEvidencePlan objects against ADR-035 / PRD #500 contracts.

Pure-stdlib validator (no jsonschema) so Meta CI validate-artifacts can import
without installing optional deps.
"""

from __future__ import annotations

from typing import Any

REQUIRED_TOP_LEVEL_FIELDS: list[str] = [
    "planId",
    "affectedPublicSurfaces",
    "candidateVerificationJourney",
    "staticAssetChecks",
    "migrationCompatibility",
    "rollbackAssertion",
    "requiredArtifacts",
    "acceptanceCommands",
    "doNotInfer",
]

_JOURNEY_REQUIRED = [
    "mode",
    "stableTrafficPercent",
    "candidatePublicTrafficPercent",
    "restrictedRoute",
    "syntheticShopRequired",
    "workersDisabledOnCandidate",
    "journeys",
]

_STATIC_REQUIRED = [
    "required",
    "htmlRoutes",
    "discoverFromHtml",
    "assetTypes",
    "failOnMissing",
    "failOnNon200",
]

_MIGRATION_REQUIRED = [
    "schemaChangeInScope",
    "expandContractOnly",
    "stableAndCandidateCompatible",
    "destructiveMigrationAllowed",
    "notes",
]

_ROLLBACK_REQUIRED = [
    "preCutoverFailureBehavior",
    "postCutoverFailureBehavior",
    "retainedStableRequired",
    "automatic",
]

_ARTIFACTS_REQUIRED = [
    "implementation",
    "intentReview",
    "review",
    "validation",
    "releaseMetadataHonest",
]


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _nonempty_string_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= 1
        and all(_nonempty_string(item) for item in value)
    )


def _require_keys(obj: dict[str, Any], keys: list[str], path: str, errors: list[str]) -> None:
    for key in keys:
        if key not in obj:
            errors.append(f"{path}: missing required property {key!r}")


def validate_release_evidence_plan(plan: Any) -> dict[str, Any]:
    """Return ``{valid, missingFields, errors}`` — fail closed on incomplete plans."""
    missing: list[str] = []
    errors: list[str] = []

    if plan is None or not isinstance(plan, dict):
        return {
            "valid": False,
            "missingFields": list(REQUIRED_TOP_LEVEL_FIELDS),
            "errors": ["releaseEvidencePlan missing or not an object"],
        }

    for field in REQUIRED_TOP_LEVEL_FIELDS:
        if field not in plan:
            missing.append(field)

    if "planId" in plan and not _nonempty_string(plan.get("planId")):
        errors.append("planId: must be a non-empty string")
        if "planId" not in missing:
            missing.append("planId")

    if "affectedPublicSurfaces" in plan and not _nonempty_string_list(
        plan.get("affectedPublicSurfaces")
    ):
        errors.append("affectedPublicSurfaces: must be a non-empty string array")
        if "affectedPublicSurfaces" not in missing:
            missing.append("affectedPublicSurfaces")

    if "acceptanceCommands" in plan and not _nonempty_string_list(plan.get("acceptanceCommands")):
        errors.append("acceptanceCommands: must be a non-empty string array")
        if "acceptanceCommands" not in missing:
            missing.append("acceptanceCommands")

    if "doNotInfer" in plan and not _nonempty_string_list(plan.get("doNotInfer")):
        errors.append("doNotInfer: must be a non-empty string array")
        if "doNotInfer" not in missing:
            missing.append("doNotInfer")

    journey = plan.get("candidateVerificationJourney")
    if "candidateVerificationJourney" in plan:
        if not isinstance(journey, dict):
            errors.append("candidateVerificationJourney: must be an object")
        else:
            _require_keys(journey, _JOURNEY_REQUIRED, "candidateVerificationJourney", errors)
            if journey.get("mode") != "candidate_verification":
                errors.append(
                    "candidateVerificationJourney.mode: must be 'candidate_verification'"
                )
            pct = journey.get("candidatePublicTrafficPercent")
            if pct is not None and pct != 0:
                errors.append(
                    "candidateVerificationJourney.candidatePublicTrafficPercent must be 0 "
                    f"(got {pct!r})"
                )
            if not _nonempty_string(journey.get("restrictedRoute")):
                errors.append(
                    "candidateVerificationJourney.restrictedRoute: must be a non-empty string"
                )
            journeys = journey.get("journeys")
            if not isinstance(journeys, list) or len(journeys) < 1:
                errors.append("candidateVerificationJourney.journeys: must be a non-empty array")
            else:
                for index, item in enumerate(journeys):
                    path = f"candidateVerificationJourney.journeys[{index}]"
                    if not isinstance(item, dict):
                        errors.append(f"{path}: must be an object")
                        continue
                    for key in ("name", "entryUrl", "assertions"):
                        if key not in item:
                            errors.append(f"{path}: missing required property {key!r}")
                    if "assertions" in item and not _nonempty_string_list(item.get("assertions")):
                        errors.append(f"{path}.assertions: must be a non-empty string array")
            api_side = journey.get("apiSideEffectsInScope", True)
            if api_side and journey.get("workersDisabledOnCandidate") is False:
                errors.append(
                    "candidateVerificationJourney.workersDisabledOnCandidate must be true "
                    "when apiSideEffectsInScope is true"
                )

    static = plan.get("staticAssetChecks")
    if "staticAssetChecks" in plan:
        if not isinstance(static, dict):
            errors.append("staticAssetChecks: must be an object")
        else:
            _require_keys(static, _STATIC_REQUIRED, "staticAssetChecks", errors)
            if not _nonempty_string_list(static.get("htmlRoutes")):
                errors.append("staticAssetChecks.htmlRoutes: must be a non-empty string array")
            if not _nonempty_string_list(static.get("assetTypes")):
                errors.append("staticAssetChecks.assetTypes: must be a non-empty string array")

    migration = plan.get("migrationCompatibility")
    if "migrationCompatibility" in plan:
        if not isinstance(migration, dict):
            errors.append("migrationCompatibility: must be an object")
        else:
            _require_keys(migration, _MIGRATION_REQUIRED, "migrationCompatibility", errors)
            if not _nonempty_string(migration.get("notes")):
                errors.append("migrationCompatibility.notes: must be a non-empty string")
            if migration.get("destructiveMigrationAllowed") is True:
                errors.append(
                    "migrationCompatibility.destructiveMigrationAllowed must be false"
                )
            if migration.get("schemaChangeInScope") is True:
                if migration.get("expandContractOnly") is not True:
                    errors.append(
                        "migrationCompatibility.expandContractOnly must be true when "
                        "schemaChangeInScope is true"
                    )
                if migration.get("destructiveMigrationAllowed") is not False:
                    errors.append(
                        "migrationCompatibility.destructiveMigrationAllowed must be false when "
                        "schemaChangeInScope is true"
                    )

    rollback = plan.get("rollbackAssertion")
    if "rollbackAssertion" in plan:
        if not isinstance(rollback, dict):
            errors.append("rollbackAssertion: must be an object")
        else:
            _require_keys(rollback, _ROLLBACK_REQUIRED, "rollbackAssertion", errors)
            for key in ("preCutoverFailureBehavior", "postCutoverFailureBehavior"):
                if key in rollback and not _nonempty_string(rollback.get(key)):
                    errors.append(f"rollbackAssertion.{key}: must be a non-empty string")

    artifacts = plan.get("requiredArtifacts")
    if "requiredArtifacts" in plan:
        if not isinstance(artifacts, dict):
            errors.append("requiredArtifacts: must be an object")
        else:
            _require_keys(artifacts, _ARTIFACTS_REQUIRED, "requiredArtifacts", errors)

    ordered_missing: list[str] = []
    seen: set[str] = set()
    for field in missing:
        if field not in seen:
            ordered_missing.append(field)
            seen.add(field)

    valid = not ordered_missing and not errors
    return {
        "valid": valid,
        "missingFields": ordered_missing,
        "errors": errors,
    }
