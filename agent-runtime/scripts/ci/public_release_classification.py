"""Classify whether an issue is a public-release change (ADR-035 / #500).

Path matches are authoritative and cannot be waived by docs-only prose.
"""

from __future__ import annotations

import re
from typing import Any

# Path prefixes / exact workflow files from PRD #500.
_PATH_PREFIX_REASONS: list[tuple[str, str]] = [
    ("apps/demo", "path:apps/demo"),
    ("apps/dashboard", "path:apps/dashboard"),
    ("apps/landing", "path:apps/landing"),
    ("infra/nginx", "path:infra/nginx"),
    ("infra/systemd", "path:infra/systemd"),
    ("infra/ecs", "path:infra/ecs"),
    ("infra/terraform", "path:infra/terraform"),
    ("infra/cdk", "path:infra/cdk"),
]

_PATH_GLOB_REASONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^infra/scripts/deploy"), "path:infra/scripts/deploy"),
    (re.compile(r"^infra/scripts/smoke"), "path:infra/scripts/smoke"),
    (re.compile(r"^infra/scripts/build-"), "path:infra/scripts/build-"),
    (re.compile(r"^\.github/workflows/release\.yml$"), "path:.github/workflows/release.yml"),
    (re.compile(r"^\.github/workflows/rollback\.yml$"), "path:.github/workflows/rollback.yml"),
    (re.compile(r"^\.github/workflows/uptime\.yml$"), "path:.github/workflows/uptime.yml"),
]

_HOST_SURFACES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bdemo\.app-juli\.com\b", re.I), "surface:demo.app-juli.com"),
    (re.compile(r"\bapi\.app-juli\.com\b", re.I), "surface:api.app-juli.com"),
    (re.compile(r"(?<![\w.])app-juli\.com\b", re.I), "surface:app-juli.com"),
]

# Body shipping signals — not bare product-name mentions or Meta-gate documentation alone.
_BODY_SIGNAL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bcandidate\s+verification\b", re.I), "body:candidate_verification"),
    (re.compile(r"\bpublic\s+surface\b", re.I), "body:public_surface"),
    (re.compile(r"\bpublic\s+release\b.*\b(cutover|deploy|ship|promote)\b", re.I), "body:public_release"),
    (re.compile(r"\b(cutover|deploy|ship|promote)\b.*\bpublic\s+release\b", re.I), "body:public_release"),
    (re.compile(r"\brollback\b", re.I), "body:rollback"),
    (re.compile(r"\bdeploy\b", re.I), "body:deploy"),
    (re.compile(r"\bsmoke\b", re.I), "body:smoke"),
    (
        re.compile(
            r"\bruntime\s+config\b.*\b(public\s+host|demo\.app-juli|api\.app-juli|app-juli\.com)\b",
            re.I,
        ),
        "body:runtime_config",
    ),
]

_LABEL_REASONS: dict[str, str] = {
    "public-release": "label:public-release",
    "public-surface": "label:public-surface",
    "release": "label:release",
    "deploy": "label:deploy",
    "rollback": "label:rollback",
    "smoke": "label:smoke",
    "candidate-verification": "label:candidate-verification",
}

_RUNTIME_BODY = re.compile(
    r"\b(systemd|alb|listener|ecr|image\s+start|next\.js\s+production|"
    r"secret\s+contract|env(?:ironment)?\s+contract)\b",
    re.I,
)


def _normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _path_reasons(paths: list[str]) -> list[str]:
    reasons: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        path = _normalize_path(raw)
        for prefix, reason in _PATH_PREFIX_REASONS:
            if path == prefix or path.startswith(prefix + "/"):
                if reason not in seen:
                    reasons.append(reason)
                    seen.add(reason)
                break
        for pattern, reason in _PATH_GLOB_REASONS:
            if pattern.search(path) and reason not in seen:
                reasons.append(reason)
                seen.add(reason)
    return reasons


def _surface_reasons(text: str) -> list[str]:
    reasons: list[str] = []
    for pattern, reason in _HOST_SURFACES:
        if pattern.search(text) and reason not in reasons:
            reasons.append(reason)
    return reasons


def _body_reasons(issue_body: str) -> list[str]:
    reasons: list[str] = []
    for pattern, reason in _BODY_SIGNAL_PATTERNS:
        if pattern.search(issue_body) and reason not in reasons:
            reasons.append(reason)
    if _RUNTIME_BODY.search(issue_body) and any(
        host.search(issue_body) for host, _ in _HOST_SURFACES
    ):
        reason = "runtime:public_host_config"
        if reason not in reasons:
            reasons.append(reason)
    return reasons


def _label_reasons(labels: list[str]) -> list[str]:
    reasons: list[str] = []
    for label in labels:
        key = label.strip().lower()
        reason = _LABEL_REASONS.get(key)
        if reason and reason not in reasons:
            reasons.append(reason)
    return reasons


def paths_from_issue_load_profile(profile: dict[str, Any] | None) -> list[str]:
    """Paths Meta uses for public-release classification (docs + modules + optional)."""
    profile = profile or {}
    paths: list[str] = []
    for field in ("requiredDocs", "requiredModules", "loadWhenNeeded"):
        paths.extend(str(p) for p in (profile.get(field) or []))
    return paths


def classify_public_release(
    *,
    paths: list[str] | None = None,
    issue_body: str = "",
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Return ``{publicRelease, publicReleaseReasons}`` for Meta cache persistence.

    Docs-only prose never clears a path-based match.
    """
    path_list = list(paths or [])
    label_list = list(labels or [])
    reasons = (
        _path_reasons(path_list)
        + _surface_reasons(issue_body)
        + _body_reasons(issue_body)
        + _label_reasons(label_list)
    )
    # Deduplicate while preserving order
    ordered: list[str] = []
    seen: set[str] = set()
    for reason in reasons:
        if reason not in seen:
            ordered.append(reason)
            seen.add(reason)
    return {
        "publicRelease": bool(ordered),
        "publicReleaseReasons": ordered,
    }
