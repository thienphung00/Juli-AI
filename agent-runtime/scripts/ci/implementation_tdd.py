"""Shared helpers for META-3 implementation artifact CI validators."""

from __future__ import annotations

from typing import Any

# Everything is code — and so requires TDD evidence — unless it appears below.
#
# This was an allowlist of code prefixes, which is fail-open by construction: a
# code directory nobody remembered to enumerate skipped TDD gating in silence.
# That is how `agent-runtime/scripts/ci/` (20+ gate and CI scripts) went ungated
# while its sibling `agent-runtime/scripts/validate/` was covered — the gap was
# invisible precisely because a skipped gate reports PASS.
#
# Measured before inverting: across the last 60 merged commits on origin/main,
# exactly one becomes newly gated, and it already shipped tests.
NON_CODE_PREFIXES = (
    "docs/",
    ".cursor/",
    ".claude/",
    ".github/",
    "agent-runtime/artifacts/",
    "agent-runtime/config/",
    "agent-runtime/docs/",
    "agent-runtime/templates/",
    "reference/",
    "screenshots/",
    "scratch/",
)

NON_CODE_SUFFIXES = (
    ".md",
    ".mdc",
    ".txt",
    ".json",
    ".yml",
    ".yaml",
    ".lock",
    ".toml",
    ".cfg",
    ".ini",
)

_TEST_DIR_MARKERS = ("tests/", "__tests__/")
_TEST_NAME_MARKERS = (".test.", ".spec.")


def _is_test_file(path: str) -> bool:
    """Test files do not require their *own* red→green cycle.

    Backfilling a characterisation test passes against unmodified source by
    design; demanding it go red would make adding missing coverage impossible.
    A change that touches tests *and* code still triggers on the code.
    """
    if any(marker in path for marker in _TEST_DIR_MARKERS):
        return True
    name = path.rsplit("/", 1)[-1]
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    return any(marker in name for marker in _TEST_NAME_MARKERS)


def _is_code_path(path: str) -> bool:
    if path.startswith(NON_CODE_PREFIXES):
        return False
    if path.endswith(NON_CODE_SUFFIXES):
        return False
    if _is_test_file(path):
        return False
    return "/" in path or path.endswith(".py")


def files_trigger_tdd_evidence(files_modified: Any) -> tuple[bool, list[str]]:
    """Return whether TDD evidence is required and which paths matched."""
    if not isinstance(files_modified, list):
        return False, []
    matched = [
        path
        for path in files_modified
        if isinstance(path, str) and _is_code_path(path.replace("\\", "/"))
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
