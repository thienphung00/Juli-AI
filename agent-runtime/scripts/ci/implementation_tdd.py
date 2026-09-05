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


# --- #1603: witnessed / reconstructed / unavailable must not collapse ------
#
# The predecessor gate above (cycle count + one passing exitCode + non-empty
# testsAdded) gave the identical PASS to a fabricated claim, an honestly
# disclosed reconstruction, and a real witnessed observation — nothing in the
# artifact recorded which one it was. ``evidenceState`` is that missing field,
# read per cycle rather than trusted as a single artifact-wide flag, because a
# multi-cycle change can legitimately mix a witnessed cycle with a
# reconstructed one and the gate must report both, not average them away.

EVIDENCE_STATE_WITNESSED = "witnessed"
EVIDENCE_STATE_RECONSTRUCTED = "reconstructed"
EVIDENCE_STATE_UNAVAILABLE = "unavailable"
# Not a declared value — see EVIDENCE_STATE_OMITTED below.
EVIDENCE_STATES = frozenset(
    {EVIDENCE_STATE_WITNESSED, EVIDENCE_STATE_RECONSTRUCTED, EVIDENCE_STATE_UNAVAILABLE}
)

# A fourth bucket, deliberately not a member of EVIDENCE_STATES: it is never a
# value ``evidenceState`` can hold, only the tally key for a cycle that has no
# ``evidenceState`` key at all. Folding "omitted" into "unavailable" (the
# original #1603 design) made every artifact written before this field
# existed fail the gate outright — the mutants clean-record fixture and the
# public-release e2e matrices among them — which is reading absence as a
# claim of no evidence. An artifact that predates the field asserted nothing;
# one that explicitly writes ``evidenceState: "unavailable"`` asserts it has
# none. Those are different states and must not share a bucket: "could not
# determine" collapsing into "no" is exactly the failure class ADR-093
# records.
EVIDENCE_STATE_OMITTED = "omitted"


def evidence_state_counts(cycles: Any) -> dict[str, int]:
    """Tally each cycle's declared ``evidenceState`` — plus a fourth bucket.

    ``omitted`` counts a cycle with no ``evidenceState`` key: it predates this
    contract (the field is optional for backward compatibility) and has
    claimed nothing, so it is kept apart from ``unavailable``, which is an
    explicit assertion of no evidence. An unrecognised string is folded into
    ``unavailable`` rather than ``omitted`` — a made-up state is a (malformed)
    claim, not silence.
    """
    counts = {
        EVIDENCE_STATE_WITNESSED: 0,
        EVIDENCE_STATE_RECONSTRUCTED: 0,
        EVIDENCE_STATE_UNAVAILABLE: 0,
        EVIDENCE_STATE_OMITTED: 0,
    }
    if not isinstance(cycles, list):
        return counts
    for cycle in cycles:
        if not isinstance(cycle, dict):
            continue
        if "evidenceState" not in cycle:
            counts[EVIDENCE_STATE_OMITTED] += 1
            continue
        state = cycle.get("evidenceState")
        if state not in EVIDENCE_STATES:
            state = EVIDENCE_STATE_UNAVAILABLE
        counts[state] += 1
    return counts


def has_witnessed_or_reconstructed_evidence(cycles: Any) -> bool:
    """Whether at least one cycle declares real evidence of either kind.

    ``unavailable``/``omitted`` cycles do not count — "no evidence either way"
    (declared or by silence) must not be able to carry this on its own,
    however many of them there are.
    """
    counts = evidence_state_counts(cycles)
    return counts[EVIDENCE_STATE_WITNESSED] > 0 or counts[EVIDENCE_STATE_RECONSTRUCTED] > 0


def every_cycle_explicitly_unavailable(cycles: Any) -> bool:
    """Whether every cycle explicitly declares ``unavailable`` — not silence.

    This is the one shape the gate still fails on with no witnessed or
    reconstructed evidence present: a cycle that predates ``evidenceState``
    (``omitted``) is legacy and tolerated, but a cycle that explicitly writes
    ``evidenceState: "unavailable"`` has asserted it has no evidence, and a
    record built entirely of such assertions has proven nothing on purpose.
    Requires at least one cycle total; an empty list is not "every cycle".
    """
    counts = evidence_state_counts(cycles)
    return (
        counts[EVIDENCE_STATE_UNAVAILABLE] > 0
        and counts[EVIDENCE_STATE_WITNESSED] == 0
        and counts[EVIDENCE_STATE_RECONSTRUCTED] == 0
        and counts[EVIDENCE_STATE_OMITTED] == 0
    )


def tests_added_or_updated(artifact: dict[str, Any]) -> bool:
    added = artifact.get("testsAdded") or []
    updated = artifact.get("testsUpdated") or []
    return (isinstance(added, list) and len(added) >= 1) or (
        isinstance(updated, list) and len(updated) >= 1
    )
