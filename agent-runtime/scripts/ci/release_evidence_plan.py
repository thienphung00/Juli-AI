"""Validate releaseEvidencePlan objects against JSON Schema + ADR-035 invariants."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

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

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "schemas"
    / "release-evidence-plan.schema.json"
)


def load_release_evidence_plan_schema() -> dict[str, Any]:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


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

    schema = load_release_evidence_plan_schema()
    validator = Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(plan), key=lambda e: list(e.absolute_path)):
        path = ".".join(str(p) for p in err.absolute_path) or "(root)"
        message = f"{path}: {err.message}"
        errors.append(message)
        # Map empty/minLength/required schema failures onto missingFields when useful
        if err.validator in {"required", "minLength", "minItems"}:
            if err.validator == "required":
                for req in err.validator_value:
                    if isinstance(plan, dict) and req not in plan and req not in missing:
                        missing.append(req)
            elif err.absolute_path:
                top = str(err.absolute_path[0])
                if top not in missing and top in REQUIRED_TOP_LEVEL_FIELDS:
                    missing.append(top)

    # Extra invariants beyond Draft schema when object present
    if isinstance(plan.get("candidateVerificationJourney"), dict):
        journey = plan["candidateVerificationJourney"]
        pct = journey.get("candidatePublicTrafficPercent")
        if pct is not None and pct != 0:
            errors.append(
                "candidateVerificationJourney.candidatePublicTrafficPercent must be 0 "
                f"(got {pct!r})"
            )
        api_side = journey.get("apiSideEffectsInScope", True)
        if api_side and journey.get("workersDisabledOnCandidate") is False:
            errors.append(
                "candidateVerificationJourney.workersDisabledOnCandidate must be true "
                "when apiSideEffectsInScope is true"
            )

    migration = plan.get("migrationCompatibility")
    if isinstance(migration, dict):
        if migration.get("destructiveMigrationAllowed") is True:
            errors.append("migrationCompatibility.destructiveMigrationAllowed must be false")
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

    # Deduplicate missing while preserving order
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
