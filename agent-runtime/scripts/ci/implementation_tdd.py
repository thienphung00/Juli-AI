"""Shared helpers for META-3 implementation artifact CI validators."""

from __future__ import annotations

from typing import Any

CODE_CHANGE_PREFIXES = (
    "backend/",
    "apps/",
    "infra/",
    "packages/",
    "agent-runtime/scripts/validate/",
)


def files_trigger_tdd_evidence(files_modified: Any) -> tuple[bool, list[str]]:
    """Return whether TDD evidence is required and which paths matched."""
    if not isinstance(files_modified, list):
        return False, []
    matched = [
        path
        for path in files_modified
        if isinstance(path, str)
        and any(path.replace("\\", "/").startswith(prefix) for prefix in CODE_CHANGE_PREFIXES)
    ]
    return bool(matched), matched


def has_passing_command_evidence(cycles: Any) -> bool:
    if not isinstance(cycles, list):
        return False
    for cycle in cycles:
        if not isinstance(cycle, dict):
            continue
        commands = cycle.get("commands") or []
        if not isinstance(commands, list):
            continue
        for command in commands:
            if isinstance(command, dict) and command.get("exitCode") == 0:
                return True
    return False


def tests_added_or_updated(artifact: dict[str, Any]) -> bool:
    added = artifact.get("testsAdded") or []
    updated = artifact.get("testsUpdated") or []
    return (isinstance(added, list) and len(added) >= 1) or (
        isinstance(updated, list) and len(updated) >= 1
    )
