"""Loader for the shared seller-copy banned-pattern source (ADR-070 decision 6).

Reads `packages/contracts/seller-copy-banned-patterns.json` — the single
language-neutral pattern source also consumed by the TypeScript guard
(`packages/contracts/src/seller-copy.ts`) — and exposes compiled `re.Pattern`
objects. Extraction only: no pattern is added, removed, or altered here (#990);
`tests/unit/test_agent_banned_patterns_contract.py` proves both regex engines
accept every entry, so the two guards can never silently drift.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# This file lives at
# backend/src/juli_backend/services/agent/sanitize/banned_patterns.py — six
# parents up is the repo root (same monorepo-relative convention as
# `juli_backend.core.config.runtime._repo_root`).
_REPO_ROOT = Path(__file__).resolve().parents[6]

BANNED_PATTERNS_JSON_PATH = (
    _REPO_ROOT / "packages" / "contracts" / "seller-copy-banned-patterns.json"
)

# JS RegExp flags this loader knows how to translate to Python `re` flags. ADR-070
# decision 6 deliberately constrains new patterns to the JS/Python-common subset —
# an unrecognized flag fails loudly rather than being silently dropped.
_JS_FLAG_TO_PYTHON: dict[str, int] = {"i": re.IGNORECASE}


@dataclass(frozen=True)
class BannedPatternEntry:
    """One banned-pattern record exactly as stored in the shared JSON source."""

    id: str
    source: str
    flags: str = ""


def _translate_flags(entry_id: str, flags: str) -> int:
    python_flags = 0
    for flag in flags:
        if flag not in _JS_FLAG_TO_PYTHON:
            raise ValueError(
                f"pattern {entry_id!r} uses flag {flag!r}, which is not in the "
                "JS/Python-common subset supported by this loader"
            )
        python_flags |= _JS_FLAG_TO_PYTHON[flag]
    return python_flags


#: The two surfaces these patterns guard (#1210). `copy_layer` is the
#: deterministic seller-copy output they were authored for; `agent_output` is
#: the LLM-authored surface `chokepoints.py` brackets the run with.
COPY_LAYER_SCOPE = "copy_layer"
AGENT_OUTPUT_SCOPE = "agent_output"


def load_banned_pattern_entries(
    path: Path | None = None,
    *,
    scope: str | None = None,
) -> tuple[BannedPatternEntry, ...]:
    """Read the shared JSON source and return the raw pattern entries, in file order.

    `scope` filters to the patterns enforced on one surface (#1210). A pattern
    with no `scopes` key counts as BOTH -- so a newly added pattern is never
    silently narrower than its author intended, and omitting the field keeps
    the old, stricter behaviour.

    Why the filter exists: several patterns were written against the
    deterministic copy layer, where `Độ tin cậy:` or `Công cụ:` is a debug label
    escaping into seller copy. Enforced verbatim on agent prose, the same
    strings are ordinary Vietnamese, and `\bconfirm\b` / `\bship\b` /
    `\ban toàn\b` are unavoidable words. A real run reached `final_response`
    and was killed by its own guard on exactly this.
    """
    json_path = path if path is not None else BANNED_PATTERNS_JSON_PATH
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    return tuple(
        BannedPatternEntry(
            id=entry["id"],
            source=entry["source"],
            flags=entry.get("flags", ""),
        )
        for entry in raw["patterns"]
        if scope is None or scope in entry.get("scopes", [COPY_LAYER_SCOPE, AGENT_OUTPUT_SCOPE])
    )


def compile_python_patterns(
    entries: Iterable[BannedPatternEntry],
) -> tuple[re.Pattern[str], ...]:
    """Compile pattern entries under Python's `re` engine.

    Raises `re.error` naming the offending pattern id if any entry fails to
    compile or uses a flag outside the JS/Python-common subset — this is what
    the dual-dialect contract test asserts on both a real bad entry and the
    real shared source.
    """
    compiled: list[re.Pattern[str]] = []
    for entry in entries:
        try:
            python_flags = _translate_flags(entry.id, entry.flags)
            compiled.append(re.compile(entry.source, python_flags))
        except ValueError as exc:
            raise re.error(str(exc)) from exc
        except re.error as exc:
            raise re.error(
                f"pattern {entry.id!r} failed to compile under Python re: {exc}"
            ) from exc
    return tuple(compiled)


@lru_cache(maxsize=4)
def load_banned_patterns(scope: str | None = None) -> tuple[re.Pattern[str], ...]:
    """Load the shared source and compile every entry under Python's `re` engine.

    Default (`scope=None`) keeps every pattern, so existing callers -- the copy
    layer and its governance tests -- are unchanged by #1210.
    """
    return compile_python_patterns(load_banned_pattern_entries(scope=scope))
