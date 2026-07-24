"""Detect hardcoded release deployment success flags without step evidence."""

from __future__ import annotations

from typing import Any

SMOKE_EVIDENCE_KEYS = (
    "smokeTestResults",
    "smokeTestEvidence",
    "smokeTestSteps",
)
HEALTH_EVIDENCE_KEYS = (
    "healthCheckResults",
    "healthCheckEvidence",
    "healthCheckSteps",
)


def _has_step_evidence(metadata: dict[str, Any], keys: tuple[str, ...]) -> bool:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, list) and len(value) >= 1:
            return True
        if isinstance(value, dict) and value:
            return True
        if isinstance(value, str) and value.strip():
            return True
    return False


def release_metadata_problems(deployment_metadata: Any) -> list[str]:
    """Return honesty violations for deploymentMetadata."""
    if not isinstance(deployment_metadata, dict):
        return []

    problems: list[str] = []
    if deployment_metadata.get("smokeTestsPassed") is True and not _has_step_evidence(
        deployment_metadata, SMOKE_EVIDENCE_KEYS
    ):
        problems.append(
            "smokeTestsPassed=true without smoke test step evidence "
            f"(expected one of {list(SMOKE_EVIDENCE_KEYS)})"
        )

    if deployment_metadata.get("healthChecksPassed") is True and not _has_step_evidence(
        deployment_metadata, HEALTH_EVIDENCE_KEYS
    ):
        problems.append(
            "healthChecksPassed=true without health check step evidence "
            f"(expected one of {list(HEALTH_EVIDENCE_KEYS)})"
        )

    return problems


def release_artifact_covers_issue(artifact: dict[str, Any], issue: int) -> bool:
    for bucket in ("featuresShipped", "bugsFixed"):
        entries = artifact.get(bucket) or []
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and entry.get("id") == issue:
                return True
    return False
