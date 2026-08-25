"""Fail-closed banned-pattern chokepoints (ADR-070 decision 6; ADR-068 decision 6(c)).

**Hidden-text stripping (ADR-075 decision 5, issue #1218).** Before the
inbound scan below ever runs, `guard_inbound_tool_result` strips control
characters, zero-width/invisible Unicode, and bidi overrides from every
vendor-tagged text field in the result (`hidden_text.strip_hidden_text_from_vendor_fields`
— see that module for exactly which Unicode categories are removed and why
Vietnamese diacritics/emoji are not touched). **Stripping runs first, the
banned-pattern scan runs second.** This ordering is deliberate, not
incidental: a banned identifier obfuscated with an invisible character
spliced between its letters (e.g. `"web​hook"`) would not match the
scan's `\bwebhook\b`-style patterns if the scan ran first — stripping ahead
of the scan closes that evasion route, so the two protections compose
instead of one silently undermining the other. This module's own
`TestInboundStripsHiddenTextFromVendorTextBeforeScanning` test class is the
regression test for this ordering. The outbound seam is unaffected —
stripping is scoped to vendor *tool-result* text only, never agent-authored
output.

Two seams bracket the agent loop:

- **Inbound** (`guard_inbound_tool_result`) — every tool result before it
  enters the conversation. A hit (or a failure anywhere inside the scanning
  machinery itself — see "Fail closed" below) discards the result entirely
  and returns an internal tool error in the same
  ``{"error": {"category", "message", "retryable"}}`` shape #993's
  `errors.py` established, so the agent loop has one error shape to reason
  about. **The model never sees the leaked value** — only the error
  envelope reaches the conversation; the raw hit goes to server-side logs
  only.
- **Outbound** (`guard_outbound_agent_output`) — all agent-authored output
  before it streams or persists. A hit (or a scanning failure) raises
  `BannedPatternGuardFailure` instead of returning the content.

Both consume the same #990 shared pattern source
(`juli_backend.services.agent.sanitize.banned_patterns`) via
`find_banned_pattern_hits` — there is no second copy of the banned-pattern
list anywhere in this module.

**Fail closed.** `find_banned_pattern_hits` raises `BannedPatternScanError`
if the shared pattern source itself fails to load or compile. Both guard
functions treat that identically to a real hit: the content is blocked, not
passed through. This is the property a swallowing ``try/except`` would
silently defeat — the exact bug this module exists to rule out — so neither
guard has a code path that catches a scanning failure and returns/streams
the original, unscanned content.

**Scope boundary (issue #994).** ADR-070 decision 6(b) also specifies the
outbound seam's *recovery* behavior on a hit: a single repair retry, then a
rules-template fallback (P7). Issue #994 explicitly defers both to the
(user-deferred) structured-output phase. This module builds the seam and
makes it fail closed; it implements **no repair retry and no
rules-template fallback** — `guard_outbound_agent_output` only raises.
Callers own what happens after that.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from juli_backend.services.agent.sanitize.banned_patterns import (
    AGENT_OUTPUT_SCOPE,
    compile_python_patterns,
    load_banned_pattern_entries,
)
from juli_backend.services.agent.sanitize.errors import TranslatedError, to_error_envelope
from juli_backend.services.agent.sanitize.hidden_text import strip_hidden_text_from_vendor_fields
from juli_backend.services.execution.types import ExecutionErrorCategory

logger = logging.getLogger(__name__)

#: Business-language message for an inbound-blocked tool result — mirrors
#: `errors.py`'s `_GUARD_MESSAGE` phrasing for a `TransportGuardError`
#: (also a deterministic internal-safety-check rejection) but names this
#: seam specifically, since the two chokepoints are distinct failure points
#: a server-side reader needs to tell apart.
_INBOUND_GUARD_MESSAGE = (
    "This tool result was blocked by an internal safety check before reaching the conversation."
)

#: Exception message for an outbound guard failure. Never includes the
#: matched banned text or pattern id — those go to `logger.warning` only.
_OUTBOUND_GUARD_MESSAGE = "Agent-authored output was blocked by an internal safety check."


@dataclass(frozen=True)
class BannedPatternHit:
    """One banned-pattern match found while scanning a structure.

    Every field here is for server-side debugging (`logger.warning`) only —
    none is ever placed in model-facing content. ``path`` is a structural
    locator into the scanned value (``$`` for the root, ``$.foo[2]`` for the
    third element of the ``foo`` list, ``$.foo.<key:bar>`` when the hit is
    in a dict *key* rather than a value) so a server-side reader can find
    exactly where the leak was without needing the leaked text itself to
    triangulate it. ``matched_text`` is the literal banned substring found.
    ``match_start`` is the byte offset in the text where the match begins.
    """

    pattern_id: str
    path: str
    matched_text: str
    match_start: int = -1  # Byte offset of the match start; -1 if unknown


class BannedPatternScanError(RuntimeError):
    """The scanning machinery itself failed (e.g. the shared #990 pattern
    source failed to load or compile).

    Both `guard_inbound_tool_result` and `guard_outbound_agent_output`
    treat this identically to a real hit — fail closed, per the module
    docstring — never passing the unscanned content through.
    """


def _iter_strings(value: Any, *, path: str) -> list[tuple[str, str]]:
    """Recurse ``value`` and yield ``(path, text)`` for every string found.

    Recurses dict keys *and* values (a leaked identifier could as easily
    arrive as a dict key as a value) and every list/tuple element. This is
    a whole-structure walk, not a top-level-keys check — a hit nested
    arbitrarily deep is found exactly the same way a top-level hit is.
    """
    found: list[tuple[str, str]] = []
    if isinstance(value, str):
        found.append((path, value))
    elif isinstance(value, Mapping):
        for key, val in value.items():
            key_str = str(key)
            found.append((f"{path}.<key:{key_str}>", key_str))
            found.extend(_iter_strings(val, path=f"{path}.{key_str}"))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.extend(_iter_strings(item, path=f"{path}[{index}]"))
    return found


def _make_masked_snippet(
    text: str, match_start: int, match_end: int, context_width: int = 15
) -> str:
    """Create a redacted snippet around a match for forensics logging.

    Replaces all letters and digits in the surrounding context with 'x',
    preserving punctuation, whitespace, and the matched pattern itself.
    This allows server-side debugging without leaking seller copy.

    Args:
        text: The full text being scanned.
        match_start: Byte offset where the match begins.
        match_end: Byte offset where the match ends.
        context_width: Number of characters to show before and after the match.

    Returns:
        A masked snippet like "xxxxx listing.xxxx"
    """
    # Ensure offsets are within bounds
    snippet_start = max(0, match_start - context_width)
    snippet_end = min(len(text), match_end + context_width)

    before = text[snippet_start:match_start]
    matched = text[match_start:match_end]
    after = text[match_end:snippet_end]

    # Mask all alphanumeric characters in before and after, preserve the match
    def _mask_text(s: str) -> str:
        return "".join("x" if c.isalnum() else c for c in s)

    return _mask_text(before) + matched + _mask_text(after)


def find_banned_pattern_hits(
    value: Any, *, scope: str | None = None
) -> tuple[BannedPatternHit, ...]:
    """Recursively scan ``value`` for banned-pattern hits.

    Uses the shared #990 pattern source directly
    (`load_banned_pattern_entries` + `compile_python_patterns`) — this
    function is the only place either chokepoint touches pattern data, so
    there is exactly one code path from "shared JSON source" to "matched
    against agent content".

    `scope` (#1210) selects which surface's patterns apply; `None` keeps every
    pattern, so any caller that does not opt in is unchanged. Both guards below
    pass `AGENT_OUTPUT_SCOPE`, because several patterns were authored against
    the deterministic copy layer and are ordinary language on the agent
    surface -- a real run reached `final_response` and was killed by its own
    guard on `Độ tin cậy:` / `an toàn`-class matches.

    Each hit includes the byte offset where the match begins, used for
    forensics logging (ADR-070 decision 6, issue #1304).

    Raises `BannedPatternScanError` if the shared source itself fails to
    load or compile. This is a deliberate raise, not a caught-and-ignored
    condition: callers (the two guard functions below) MUST treat it as a
    hit for fail-closed purposes.
    """
    try:
        entries = load_banned_pattern_entries(scope=scope)
        patterns = compile_python_patterns(entries)
    except Exception as exc:  # noqa: BLE001 - deliberately fail-closed, see above
        raise BannedPatternScanError(
            f"failed to load or compile the shared banned-pattern source: {exc}"
        ) from exc

    hits: list[BannedPatternHit] = []
    for path, text in _iter_strings(value, path="$"):
        for entry, pattern in zip(entries, patterns, strict=True):
            match = pattern.search(text)
            if match is not None:
                hits.append(
                    BannedPatternHit(
                        pattern_id=entry.id,
                        path=path,
                        matched_text=match.group(0),
                        match_start=match.start(),
                    )
                )
    return tuple(hits)


def _log_inbound_hits(
    *, tool_name: str, hits: tuple[BannedPatternHit, ...], full_text: str = ""
) -> None:
    """Log inbound banned-pattern hits with forensics (ADR-070, issue #1304).

    Includes redaction-safe context: match offsets, text length, and masked
    snippets (letters replaced, punctuation preserved) so server-side readers
    can classify hits as jargon vs natural language without exposing copy.
    """
    offsets = [hit.match_start for hit in hits if hit.match_start >= 0]
    masked = []
    if full_text:
        for hit in hits:
            if hit.match_start >= 0:
                snippet = _make_masked_snippet(
                    full_text, hit.match_start, hit.match_start + len(hit.matched_text)
                )
                masked.append(snippet)

    logger.warning(
        "agent_inbound_banned_pattern_hit",
        extra={
            "tool_name": tool_name,
            "hit_count": len(hits),
            "pattern_ids": [hit.pattern_id for hit in hits],
            "paths": [hit.path for hit in hits],
            "matched_text": [hit.matched_text for hit in hits],
            "match_offsets": offsets,
            "text_length": len(full_text) if full_text else -1,
            "masked_snippets": masked,
        },
    )


def _inbound_guard_error_envelope() -> dict[str, Any]:
    return to_error_envelope(
        TranslatedError(
            category=ExecutionErrorCategory.VALIDATION,
            message=_INBOUND_GUARD_MESSAGE,
            retryable=False,
        )
    )


def guard_inbound_tool_result(result: Mapping[str, Any], *, tool_name: str) -> Mapping[str, Any]:
    """Fail-closed inbound chokepoint (ADR-070 decision 6(a); ADR-075 decision 5).

    **Strips first, scans second.** Every vendor-tagged text field in
    ``result`` has control characters, zero-width/invisible Unicode, and
    bidi overrides removed (`hidden_text.strip_hidden_text_from_vendor_fields`)
    *before* the banned-pattern scan below ever runs — see the module
    docstring's "Hidden-text stripping" section for why that ordering is
    load-bearing, not cosmetic.

    The stripped result is then scanned for a banned-pattern hit before it
    is allowed into the conversation. On a hit — or on a
    `BannedPatternScanError` from the scanning machinery itself, which this
    function treats identically (fail closed) — the (already-stripped)
    result is discarded in full and replaced with an internal tool error in
    the same ``{"error": {"category", "message", "retryable"}}`` shape
    #993's `errors.py` established, so the agent loop has one error shape
    to reason about regardless of whether the failure was a marketplace
    error or a guard hit.

    ``category`` is `ExecutionErrorCategory.VALIDATION` — the same category
    `errors.py._category_for` assigns a `TransportGuardError`: both are
    deterministic policy rejections by an internal guard, not a marketplace
    outcome. ``retryable`` is always ``False``: the content that tripped
    the guard does not change on a re-call, so a retry would deterministically
    trip the same guard again — ``retryable: True`` here would let the agent
    loop thrash against its own safety check.

    The hit (pattern id, structural path, and the literal matched text) is
    logged server-side via ``logger.warning`` before this function returns
    — enough detail to debug which tool, which pattern, and where in the
    result it was found — but none of that detail is present in, or
    derivable from, the returned error envelope. Forensics (match offset, text
    length, masked snippet) are included for classification without exposing
    seller copy (ADR-070 decision 6, issue #1304).

    On a clean result whose stripping actually changed something, this
    returns the **stripped** value, not the original ``result`` object. On
    a clean result stripping left unchanged (the common case — no hidden
    characters anywhere), this returns ``result`` itself, preserving object
    identity: callers (`runner/core.py`'s `_dispatch_tool_call`) rely on
    ``sanitized is raw_result`` as their clean/blocked telemetry signal, so
    an unmodified result must stay identity-equal to what was passed in.
    """
    stripped_result = strip_hidden_text_from_vendor_fields(result)

    try:
        hits = find_banned_pattern_hits(stripped_result, scope=AGENT_OUTPUT_SCOPE)
    except BannedPatternScanError as exc:
        logger.warning(
            "agent_inbound_banned_pattern_guard_failed",
            extra={"tool_name": tool_name, "reason": str(exc)},
        )
        return _inbound_guard_error_envelope()

    if not hits:
        # Preserve object identity when stripping made no actual change.
        # `WorkflowRunner._dispatch_tool_call` (runner/core.py) computes its
        # `tool.completed` telemetry as `sanitized is raw_result` -- a
        # result with no hidden characters must come back as the exact
        # object it was passed in as, not an equal-but-rebuilt copy, or
        # that pre-existing identity contract silently breaks for every
        # ordinary (no-hidden-text) tool result.
        return result if stripped_result == result else stripped_result

    # For forensics: collect the actual text strings where hits occurred
    # (the hit.path tells us the structure location, but we need the actual
    # text to compute masked snippets)
    hit_texts = {}
    for path, text in _iter_strings(stripped_result, path="$"):
        for hit in hits:
            if hit.path == path:
                hit_texts[hit.path] = text
                break

    # Compute full text by reconstructing from hits (for masked snippet generation)
    # For simplicity, if a hit has a match_start, use the text from its path
    full_text_for_forensics = ""
    if hits and hit_texts:
        # Use the first hit's text for forensics (if multiple hits exist, this is conservative)
        full_text_for_forensics = next(iter(hit_texts.values()), "")

    _log_inbound_hits(tool_name=tool_name, hits=hits, full_text=full_text_for_forensics)
    return _inbound_guard_error_envelope()


class BannedPatternGuardFailure(RuntimeError):
    """Raised by `guard_outbound_agent_output` on a banned-pattern hit, or
    on a `BannedPatternScanError` from the scanning machinery itself (fail
    closed — see module docstring).

    ``str(exc)`` never contains the matched banned text or pattern id —
    those are logged server-side (`logger.warning`) before this is raised,
    never carried on the exception itself.
    """


def guard_outbound_agent_output(output: Any) -> None:
    """Fail-closed outbound chokepoint (ADR-070 decision 6(b)) — seam only.

    Scans agent-authored ``output`` before it is allowed to stream or
    persist. Raises `BannedPatternGuardFailure` on a hit, or on a
    `BannedPatternScanError` from the scanning machinery itself (fail
    closed — treated identically to a real hit). Returns ``None`` — does
    not raise — only when the scan completes cleanly with zero hits.

    **This function only detects and blocks.** ADR-070 decision 6(b) also
    specifies this seam's *recovery* behavior on a hit (a single repair
    retry, then a rules-template fallback), but issue #994 explicitly
    defers both to the structured-output phase, which is user-deferred.
    There is no repair, retry, or fallback path here — a caller that wants
    one builds it on top of this function's `BannedPatternGuardFailure`.

    Forensics (match offset, text length, masked snippet) are logged for
    classification without exposing agent-authored copy (ADR-070 decision 6,
    issue #1304).
    """
    try:
        hits = find_banned_pattern_hits(output, scope=AGENT_OUTPUT_SCOPE)
    except BannedPatternScanError as exc:
        logger.warning("agent_outbound_banned_pattern_guard_failed", extra={"reason": str(exc)})
        raise BannedPatternGuardFailure(_OUTBOUND_GUARD_MESSAGE) from exc

    if not hits:
        return None

    # Collect the actual text strings from the output where hits occurred
    hit_texts = {}
    for path, text in _iter_strings(output, path="$"):
        for hit in hits:
            if hit.path == path:
                hit_texts[hit.path] = text
                break

    # Compute full text for forensics (use first hit's text)
    full_text_for_forensics = ""
    if hits and hit_texts:
        full_text_for_forensics = next(iter(hit_texts.values()), "")

    # Compute masked snippets for forensics
    offsets = [hit.match_start for hit in hits if hit.match_start >= 0]
    masked = []
    if full_text_for_forensics:
        for hit in hits:
            if hit.match_start >= 0:
                match_end = hit.match_start + len(hit.matched_text)
                snippet = _make_masked_snippet(full_text_for_forensics, hit.match_start, match_end)
                masked.append(snippet)

    # The pattern ids are also in the MESSAGE, not only in `extra` (#1210):
    # the celery worker's log format drops `extra`, so production showed just
    # "agent_outbound_banned_pattern_hit" with no reason, and the cause had to
    # be reconstructed from the pattern file. `matched_text` stays out of the
    # message -- it is agent-authored content, and the ids alone identify the
    # rule.
    logger.warning(
        "agent_outbound_banned_pattern_hit: %s",
        ",".join(sorted({hit.pattern_id for hit in hits})),
        extra={
            "hit_count": len(hits),
            "pattern_ids": [hit.pattern_id for hit in hits],
            "paths": [hit.path for hit in hits],
            "matched_text": [hit.matched_text for hit in hits],
            "match_offsets": offsets,
            "text_length": len(full_text_for_forensics) if full_text_for_forensics else -1,
            "masked_snippets": masked,
        },
    )
    raise BannedPatternGuardFailure(_OUTBOUND_GUARD_MESSAGE)


__all__ = [
    "BannedPatternGuardFailure",
    "BannedPatternHit",
    "BannedPatternScanError",
    "find_banned_pattern_hits",
    "guard_inbound_tool_result",
    "guard_outbound_agent_output",
]
