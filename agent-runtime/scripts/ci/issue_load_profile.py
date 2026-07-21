"""Derived issueLoadProfile rules for issue context caches."""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import sys

_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from build_runtime import load_simple_yaml  # noqa: E402


AC_HEADING_RE = re.compile(r"^##\s+Acceptance criteria\s*$", re.IGNORECASE)
HEADING_RE = re.compile(r"^##\s+")
CHECKBOX_RE = re.compile(r"^[-*]\s+(?:\[[ xX]\]\s*)?(?P<text>.+?)\s*$")

SLICE_ROUTING_CONFIG = (
    Path(__file__).resolve().parents[2] / "config" / "slice-routing.yml"
)


def load_slice_routing_rules(config_path: Path | None = None) -> dict[str, dict[str, Any]]:
    path = config_path or SLICE_ROUTING_CONFIG
    rules = load_simple_yaml(path)
    if not isinstance(rules, dict):
        raise ValueError(f"slice-routing config must be a mapping: {path}")
    return rules


def parse_acceptance_criteria(issue_body: str) -> list[str]:
    """Extract bullet text under the issue's Acceptance criteria heading."""
    lines = issue_body.splitlines()
    in_section = False
    criteria: list[str] = []
    for line in lines:
        stripped = line.strip()
        if AC_HEADING_RE.match(stripped):
            in_section = True
            continue
        if in_section and HEADING_RE.match(stripped):
            break
        if not in_section:
            continue
        match = CHECKBOX_RE.match(stripped)
        if match:
            criteria.append(match.group("text").replace("`", "").strip())
    return criteria


def _dedupe(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for path in paths:
        if path not in seen:
            result.append(path)
            seen.add(path)
    return result


def _render_paths(paths: list[str], *, handoff_path: str) -> list[str]:
    rendered: list[str] = []
    for path in paths:
        if not path:
            continue
        if path == "{handoffPath}" and not handoff_path:
            continue
        rendered.append(path.replace("{handoffPath}", handoff_path))
    return _dedupe(rendered)


def derive_issue_load_profile(
    *,
    slice_id: str,
    issue_body: str,
    handoff_path: str,
    rules: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Derive the child load profile from Focus slice routing plus issue AC."""
    slice_rules = rules or load_slice_routing_rules()
    if slice_id not in slice_rules:
        known = ", ".join(sorted(slice_rules))
        raise ValueError(
            f"No issueLoadProfile derivation rule for sliceId {slice_id!r}; known: {known}"
        )

    rule = deepcopy(slice_rules[slice_id])
    return {
        "executorDomain": rule["executorDomain"],
        "requiredDocs": _render_paths(rule.get("requiredDocs", []), handoff_path=handoff_path),
        "requiredModules": _render_paths(
            rule.get("requiredModules", []), handoff_path=handoff_path
        ),
        "acceptanceCriteria": parse_acceptance_criteria(issue_body),
        "loadWhenNeeded": _render_paths(
            rule.get("loadWhenNeeded", []), handoff_path=handoff_path
        ),
        "doNotLoad": _render_paths(rule.get("doNotLoad", []), handoff_path=handoff_path),
    }


def _as_list(profile: dict[str, Any], field: str) -> list[str]:
    values = profile.get(field) or []
    return [str(value) for value in values]


def compare_issue_load_profile(
    cached_profile: dict[str, Any],
    derived_profile: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return cache drift between a cached profile and the derived profile."""
    problems: list[dict[str, Any]] = []

    if cached_profile.get("executorDomain") != derived_profile.get("executorDomain"):
        problems.append(
            {
                "field": "executorDomain",
                "type": "value_mismatch",
                "expected": derived_profile.get("executorDomain"),
                "actual": cached_profile.get("executorDomain"),
            }
        )

    for field in ("requiredDocs", "requiredModules", "acceptanceCriteria", "loadWhenNeeded"):
        cached = set(_as_list(cached_profile, field))
        derived = set(_as_list(derived_profile, field))
        for missing in sorted(derived - cached):
            problems.append({"field": field, "type": "missing_required", "path": missing})
        for extra in sorted(cached - derived):
            problems.append({"field": field, "type": "undeclared_path", "path": extra})

    return problems
