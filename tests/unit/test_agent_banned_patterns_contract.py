"""Contract test: the shared seller-copy banned-pattern source compiles under both
regex dialects it is consumed by, so the Python agent guard and the TypeScript guard
(`packages/contracts/src/seller-copy.ts`) can never silently drift.

ADR-070 decision 6 / issue #990 — this is extraction only: no pattern is added,
removed, or altered. The JSON source of truth is
`packages/contracts/seller-copy-banned-patterns.json`; this test proves every entry in
it compiles under Python's `re` engine (via the new loader) and under JavaScript's
`RegExp` engine (by shelling out to `node`), and that a pattern valid in only one
dialect fails with a message naming it.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from juli_backend.services.agent.sanitize import (
    BANNED_PATTERNS_JSON_PATH,
    BannedPatternEntry,
    load_banned_pattern_entries,
    load_banned_patterns,
)
from juli_backend.services.agent.sanitize.banned_patterns import compile_python_patterns

REPO_ROOT = Path(__file__).resolve().parents[2]
NODE_BIN = shutil.which("node")

# Original hand-written TypeScript array (packages/contracts/src/seller-copy.ts as of
# #990) — (source, flags) pairs. Used to prove the JSON extraction changed nothing.
# Issue #1304: listing_dot pattern narrowed to listing\.(?=[A-Za-z_]) to allow
# sentence-final "listing." while still catching jargon like "listing.title".
_ORIGINAL_TS_PATTERNS: tuple[tuple[str, str], ...] = (
    ("tool_name", "i"),
    ("workflow_key", "i"),
    ("feature_id", "i"),
    (r"\bwebhook\b", "i"),
    (r"\bendpoint\b", "i"),
    (r"\bFBS\b", ""),
    (r"\bFBT\b", ""),
    ("Độ tin cậy:", ""),
    ("Công cụ:", ""),
    ("Khả năng:", ""),
    ("Get Product", "i"),
    (r"Unresolved\/Unfilled", "i"),
    (r"listing\.(?=[A-Za-z_])", ""),
    (r"inventory\.", ""),
    (r"fulfillment\.", ""),
    (r"returns\.", ""),
    (r"promotion\.", ""),
    (r"\bexecutor\b", "i"),
    (r"\bCreate Packages\b", "i"),
    (r"\bship\b", "i"),
    (r"\bsplit\b", "i"),
    (r"\bconfirm\b", "i"),
    (r"\bDeactivate\b", "i"),
    (r"\bparity\b", "i"),
    (r"\bActivity\b", ""),
    ("Get Activity", "i"),
    (r"\bvirus\b", "i"),
    (r"\bviruses\b", "i"),
    ("antivirus", "i"),
    ("malware", "i"),
    (r"\ban toàn\b", "i"),
    ("kiểm tra an toàn", "i"),
    ("tệp an toàn", "i"),
)


def _compile_in_node(entries: list[dict[str, str]]) -> dict:
    """Attempt `new RegExp(source, flags)` for every entry inside a `node` subprocess.

    Returns ``{"ok": bool, "errors": [{"id", "error"}]}``. This is how the contract
    test proves JS-dialect compilability without a JS test runner in this repo's
    Python test path — Node is already a repo-wide dependency (pnpm workspaces).
    """
    assert NODE_BIN, "node binary not found on PATH — required to check the JS regex dialect"
    script = (
        "const entries = JSON.parse(process.argv[1]);"
        "const errors = [];"
        "for (const e of entries) {"
        "  try { new RegExp(e.source, e.flags || ''); }"
        "  catch (err) { errors.push({id: e.id, error: String(err && err.message || err)}); }"
        "}"
        "process.stdout.write(JSON.stringify({ok: errors.length === 0, errors}));"
    )
    proc = subprocess.run(
        [NODE_BIN, "-e", script, json.dumps(entries)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return json.loads(proc.stdout)


def _entries_to_dicts(entries: tuple[BannedPatternEntry, ...]) -> list[dict[str, str]]:
    return [{"id": e.id, "source": e.source, "flags": e.flags} for e in entries]


# ---------------------------------------------------------------------------
# Shared JSON source: existence, shape, uniqueness
# ---------------------------------------------------------------------------


def test_shared_json_source_exists_in_contracts_package():
    assert BANNED_PATTERNS_JSON_PATH == (
        REPO_ROOT / "packages" / "contracts" / "seller-copy-banned-patterns.json"
    )
    assert BANNED_PATTERNS_JSON_PATH.is_file()


def test_pattern_ids_are_unique():
    entries = load_banned_pattern_entries()
    ids = [e.id for e in entries]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Dual-dialect compilation of the real shared source
# ---------------------------------------------------------------------------


def test_every_pattern_compiles_under_python_re():
    compiled = load_banned_patterns()
    entries = load_banned_pattern_entries()
    assert len(compiled) == len(entries) > 0
    for pattern in compiled:
        assert isinstance(pattern, re.Pattern)


def test_every_pattern_compiles_under_javascript_regexp():
    entries = load_banned_pattern_entries()
    result = _compile_in_node(_entries_to_dicts(entries))
    assert result["ok"], result["errors"]


# ---------------------------------------------------------------------------
# Zero behavior change: JSON-derived patterns match the original TS literal exactly
# ---------------------------------------------------------------------------


def test_json_source_matches_original_typescript_literal_exactly():
    """Proves extraction changed nothing: same count, same order, same
    (source, flags) pairs as the hand-written array `seller-copy.ts` held before
    #990 (captured above from git history at the time this test was written).
    """
    entries = load_banned_pattern_entries()
    actual = tuple((e.source, e.flags) for e in entries)
    assert actual == _ORIGINAL_TS_PATTERNS


# ---------------------------------------------------------------------------
# A pattern valid in only one dialect fails with a message naming it
# ---------------------------------------------------------------------------


def test_pattern_invalid_in_python_fails_naming_it():
    """JS's `\\p{L}` unicode property escape needs the `u` flag and errors under
    Python's `re` module (unknown escape `\\p`), demonstrating the JS/Python-common
    subset constraint decision 6 imposes on new patterns.
    """
    bad_entries = (BannedPatternEntry(id="js_only_unicode_property", source=r"\p{L}", flags="u"),)
    with pytest.raises(re.error) as exc_info:
        compile_python_patterns(bad_entries)
    assert "js_only_unicode_property" in str(exc_info.value)


def test_pattern_invalid_in_javascript_fails_naming_it():
    """Python's `(?P<name>...)` named-group syntax is a JS `SyntaxError` (JS spells
    it `(?<name>...)`), demonstrating the same constraint from the other direction.
    """
    bad_entries = [{"id": "python_only_named_group", "source": r"(?P<name>foo)", "flags": ""}]
    result = _compile_in_node(bad_entries)
    assert not result["ok"]
    assert result["errors"][0]["id"] == "python_only_named_group"
