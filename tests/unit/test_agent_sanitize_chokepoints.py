"""Tests for the two fail-closed banned-pattern chokepoints (ADR-070 decision 6;
ADR-068 decision 6(c)).

Issue #994 — inbound (every tool result before it enters the conversation) and
outbound (all agent-authored output before it streams or persists) both consume
the shared #990 pattern source and fail closed: a hit, or a failure inside the
scanning machinery itself, blocks the content rather than passing it through.

Scope boundary asserted here too: ADR-070 decision 6(b) also specifies the
outbound seam's *recovery* behavior (a single repair retry, then a
rules-template fallback). Issue #994 explicitly defers both to the
(user-deferred) structured-output phase — this module must implement neither.
"""

from __future__ import annotations

import logging

import pytest

import juli_backend.services.agent.sanitize.chokepoints as chokepoints_module
from juli_backend.services.agent.sanitize.banned_patterns import BannedPatternEntry
from juli_backend.services.agent.sanitize.chokepoints import (
    BannedPatternGuardFailure,
    BannedPatternHit,
    BannedPatternScanError,
    find_banned_pattern_hits,
    guard_inbound_tool_result,
    guard_outbound_agent_output,
)

_CHOKEPOINTS_LOGGER = "juli_backend.services.agent.sanitize.chokepoints"

# "webhook" is a real entry in the shared #990 source
# (packages/contracts/seller-copy-banned-patterns.json, id "webhook",
# `\bwebhook\b` case-insensitive) — using it (rather than a made-up string)
# proves these chokepoints consult the real shared source, not a fixture.
_BANNED_VALUE = "webhook"
_BANNED_SENTENCE = f"Please retry the {_BANNED_VALUE} delivery for this order."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _walk_strings(value: object) -> list[str]:
    """Recurse an arbitrarily nested structure and collect every string found
    (keys and values). Mirrors `test_agent_sanitize_errors.py`'s helper — used
    for the adversarial no-leak assertions: a flat top-level key check is not
    enough, so acceptance criterion 1 recurses the whole returned structure.
    """
    found: list[str] = []
    if isinstance(value, str):
        found.append(value)
    elif isinstance(value, dict):
        for key, val in value.items():
            found.append(str(key))
            found.extend(_walk_strings(val))
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            found.extend(_walk_strings(item))
    else:
        found.append(repr(value))
    return found


def _deeply_nested_tool_result(*, banned_value: str) -> dict:
    """A tool result shaped like a real ADR-070 sanitized payload, with the
    banned value planted three levels deep — not at the top level — so a
    check that only inspects top-level keys would miss it.
    """
    return {
        "product": {
            "id_ref": "P1",
            "reviews": [
                {"source": "vendor", "text": "Great quality!"},
                {"source": "vendor", "text": f"Nested note: {banned_value}."},
            ],
        },
        "meta": {"page": 1},
    }


# ---------------------------------------------------------------------------
# Acceptance criterion 1: inbound hit -> internal tool error, banned value
# never reaches the conversation content. Recursed, not top-level-only.
# ---------------------------------------------------------------------------


def test_inbound_hit_is_replaced_with_internal_tool_error_and_never_reaches_content():
    planted = _deeply_nested_tool_result(banned_value=_BANNED_VALUE)

    result = guard_inbound_tool_result(planted, tool_name="get_product_reviews")

    # The banned value appears nowhere in what the model would see, however
    # deeply it was nested in the original.
    haystack = "\n".join(_walk_strings(result))
    assert _BANNED_VALUE not in haystack.lower()

    # And it is the #993 error envelope shape, not a bespoke second shape.
    assert set(result) == {"error"}
    assert set(result["error"]) == {"category", "message", "retryable"}
    assert result["error"]["category"] == "validation"
    assert result["error"]["retryable"] is False
    assert isinstance(result["error"]["message"], str) and result["error"]["message"]


def test_inbound_clean_result_passes_through_unchanged():
    clean = _deeply_nested_tool_result(banned_value="a completely unrelated value")

    result = guard_inbound_tool_result(clean, tool_name="get_product_reviews")

    assert result == clean


def test_inbound_hit_found_regardless_of_nesting_depth():
    """Acceptance criterion 1, stated directly: a hit buried in a list inside
    a dict inside a dict is still caught — this is a whole-structure walk,
    not a top-level-keys check."""
    planted = {"a": {"b": [{"c": {"d": [f"x {_BANNED_VALUE} y"]}}]}}

    result = guard_inbound_tool_result(planted, tool_name="deep_tool")

    assert "error" in result
    assert _BANNED_VALUE not in "\n".join(_walk_strings(result)).lower()


# ---------------------------------------------------------------------------
# Acceptance criterion 2: the inbound hit is logged with enough server-side
# detail to debug. Self-sufficient — sets its own caplog level and pins the
# logger name, independent of any global logging config.
# ---------------------------------------------------------------------------


def test_inbound_hit_is_logged_with_server_side_debug_detail(caplog):
    planted = _deeply_nested_tool_result(banned_value=_BANNED_VALUE)

    with caplog.at_level(logging.WARNING, logger=_CHOKEPOINTS_LOGGER):
        guard_inbound_tool_result(planted, tool_name="get_product_reviews")

    records = [r for r in caplog.records if r.name == _CHOKEPOINTS_LOGGER]
    assert records, "expected the inbound hit to be logged"
    record = records[0]
    assert record.tool_name == "get_product_reviews"
    assert record.hit_count >= 1
    assert "webhook" in record.pattern_ids
    # Enough detail to actually debug: the structural path and the literal
    # matched text are both present server-side (never in the returned
    # envelope — see the previous test).
    assert any(_BANNED_VALUE in text.lower() for text in record.matched_text)
    assert any("reviews" in path for path in record.paths)


def test_inbound_clean_result_logs_nothing_at_warning(caplog):
    clean = _deeply_nested_tool_result(banned_value="nothing suspicious here")

    with caplog.at_level(logging.WARNING, logger=_CHOKEPOINTS_LOGGER):
        guard_inbound_tool_result(clean, tool_name="get_product_reviews")

    records = [r for r in caplog.records if r.name == _CHOKEPOINTS_LOGGER]
    assert records == []


# ---------------------------------------------------------------------------
# category/retryable justification: VALIDATION + not-retryable, the same
# pairing errors.py gives a TransportGuardError (a deterministic internal
# policy rejection, not a marketplace outcome) — a re-call would
# deterministically trip the same guard again.
# ---------------------------------------------------------------------------


def test_inbound_guard_error_category_and_retryable_are_a_deterministic_policy_rejection():
    from juli_backend.services.execution.types import ExecutionErrorCategory

    result = guard_inbound_tool_result({"text": _BANNED_SENTENCE}, tool_name="any_tool")

    assert result["error"]["category"] == ExecutionErrorCategory.VALIDATION.value
    assert result["error"]["retryable"] is False


# ---------------------------------------------------------------------------
# Acceptance criterion 3: banned value in agent-authored output triggers a
# guard failure at the outbound seam.
# ---------------------------------------------------------------------------


def test_outbound_hit_raises_guard_failure():
    with pytest.raises(BannedPatternGuardFailure) as exc_info:
        guard_outbound_agent_output({"copy": _BANNED_SENTENCE})

    # The exception message itself never carries the matched banned text —
    # only the server-side log (asserted below) does.
    assert _BANNED_VALUE not in str(exc_info.value).lower()


def test_outbound_hit_nested_in_structured_output_still_raises():
    output = {
        "findings": [{"severity": "info", "message": "ok"}],
        "reasoning_copy": {"headline": "All good", "detail": _BANNED_SENTENCE},
    }

    with pytest.raises(BannedPatternGuardFailure):
        guard_outbound_agent_output(output)


def test_outbound_clean_output_does_not_raise_and_returns_none():
    assert guard_outbound_agent_output({"copy": "Everything looks healthy."}) is None
    assert guard_outbound_agent_output("Plain clean string output.") is None


def test_outbound_hit_is_logged_with_server_side_debug_detail(caplog):
    with caplog.at_level(logging.WARNING, logger=_CHOKEPOINTS_LOGGER):
        with pytest.raises(BannedPatternGuardFailure):
            guard_outbound_agent_output(_BANNED_SENTENCE)

    records = [r for r in caplog.records if r.name == _CHOKEPOINTS_LOGGER]
    assert records, "expected the outbound hit to be logged"
    record = records[0]
    assert "webhook" in record.pattern_ids
    assert any(_BANNED_VALUE in text.lower() for text in record.matched_text)


# ---------------------------------------------------------------------------
# Acceptance criterion 4: BOTH checkpoints fail closed. An error raised
# inside the guard's own machinery blocks the content rather than passing it
# through — proven by making the pattern loader itself raise, on otherwise
# perfectly clean content.
# ---------------------------------------------------------------------------


def test_scan_raises_scan_error_when_pattern_loader_fails(monkeypatch):
    def _boom():
        raise RuntimeError("shared pattern source is unavailable")

    monkeypatch.setattr(chokepoints_module, "load_banned_pattern_entries", _boom)

    with pytest.raises(BannedPatternScanError):
        find_banned_pattern_hits({"text": "perfectly clean"})


def test_inbound_fails_closed_when_guard_machinery_raises(monkeypatch):
    """The critical fail-closed assertion: even though the *content* has no
    banned value in it at all, a failure inside the scanning machinery
    itself must still block it. A `try/except` that swallowed this and
    returned the original clean-looking content would pass this test's
    negative case but fail this one — exactly the bug this guards against.
    """

    def _boom():
        raise RuntimeError("shared pattern source is unavailable")

    monkeypatch.setattr(chokepoints_module, "load_banned_pattern_entries", _boom)

    clean_content = {"text": "nothing banned in here at all"}
    result = guard_inbound_tool_result(clean_content, tool_name="any_tool")

    # Blocked, not passed through: the original clean content must NOT be
    # what comes back.
    assert result != clean_content
    assert set(result) == {"error"}
    assert result["error"]["retryable"] is False


def test_outbound_fails_closed_when_guard_machinery_raises(monkeypatch):
    def _boom():
        raise RuntimeError("shared pattern source is unavailable")

    monkeypatch.setattr(chokepoints_module, "load_banned_pattern_entries", _boom)

    # Perfectly clean content — the guard must still block it because its
    # own machinery failed, not because anything was actually found.
    with pytest.raises(BannedPatternGuardFailure):
        guard_outbound_agent_output({"text": "nothing banned in here at all"})


def test_inbound_fail_closed_error_is_also_logged(monkeypatch, caplog):
    def _boom():
        raise RuntimeError("shared pattern source is unavailable")

    monkeypatch.setattr(chokepoints_module, "load_banned_pattern_entries", _boom)

    with caplog.at_level(logging.WARNING, logger=_CHOKEPOINTS_LOGGER):
        guard_inbound_tool_result({"text": "clean"}, tool_name="any_tool")

    records = [r for r in caplog.records if r.name == _CHOKEPOINTS_LOGGER]
    assert records, "a guard-machinery failure must still be logged server-side"


# ---------------------------------------------------------------------------
# Acceptance criterion 5: both chokepoints use the shared #990 pattern
# source — no second copy of the list lives in this module.
# ---------------------------------------------------------------------------


def test_scanning_defers_entirely_to_the_shared_loader_no_baked_in_copy(monkeypatch):
    """If this module had its own baked-in copy of the pattern list, this
    monkeypatch (which replaces the *only* pattern source the loop is
    allowed to consult) would have no effect and "webhook" would still be
    found. Because it has no such copy, a real banned word goes undetected
    once the shared loader reports zero patterns, and a sentinel pattern the
    loader alone knows about IS detected — proving detection is driven
    solely by whatever `load_banned_pattern_entries` returns.
    """
    monkeypatch.setattr(chokepoints_module, "load_banned_pattern_entries", lambda scope=None: ())

    hits = find_banned_pattern_hits({"text": _BANNED_SENTENCE})
    assert hits == ()

    sentinel_entries = (
        BannedPatternEntry(id="sentinel_only", source="zzz-sentinel-zzz", flags=""),
    )
    monkeypatch.setattr(
        chokepoints_module, "load_banned_pattern_entries", lambda scope=None: sentinel_entries
    )

    hits = find_banned_pattern_hits({"text": "contains zzz-sentinel-zzz here"})
    assert len(hits) == 1
    assert hits[0].pattern_id == "sentinel_only"
    assert isinstance(hits[0], BannedPatternHit)


def test_chokepoints_module_imports_pattern_loader_from_shared_source_module():
    """Static confirmation alongside the behavioral one above: the loader
    function objects this module scans with are literally the ones exported
    by `banned_patterns.py` (#990), not reimplementations."""
    from juli_backend.services.agent.sanitize import banned_patterns

    assert (
        chokepoints_module.load_banned_pattern_entries
        is banned_patterns.load_banned_pattern_entries
    )
    assert chokepoints_module.compile_python_patterns is banned_patterns.compile_python_patterns


def test_real_shared_source_is_used_by_default():
    """Without any monkeypatching, scanning for the real shared pattern
    "webhook" against the real JSON source succeeds end to end."""
    hits = find_banned_pattern_hits({"text": _BANNED_SENTENCE})
    assert any(hit.pattern_id == "webhook" for hit in hits)


# ---------------------------------------------------------------------------
# Acceptance criterion 6: no repair-retry and no rules-template fallback are
# implemented at the outbound seam.
# ---------------------------------------------------------------------------


def test_module_defines_no_repair_retry_or_fallback_machinery():
    forbidden_substrings = ("repair", "retry", "fallback", "template")
    names = [name for name in vars(chokepoints_module) if not name.startswith("_")]
    offenders = [name for name in names if any(bad in name.lower() for bad in forbidden_substrings)]
    assert offenders == [], f"found deferred recovery machinery: {offenders}"


def test_outbound_guard_only_raises_never_repairs_or_substitutes_content():
    """Calling the outbound guard on the same banned content twice raises
    both times, identically — proving there is no silent repair path that
    would make a second call succeed."""
    output = {"copy": _BANNED_SENTENCE}

    with pytest.raises(BannedPatternGuardFailure):
        guard_outbound_agent_output(output)
    with pytest.raises(BannedPatternGuardFailure):
        guard_outbound_agent_output(output)

    # And the caller's own object was never mutated into something "fixed".
    assert output == {"copy": _BANNED_SENTENCE}


def test_guard_outbound_agent_output_signature_has_no_retry_or_fallback_parameters():
    import inspect

    params = inspect.signature(guard_outbound_agent_output).parameters
    assert set(params) == {"output"}


# ---------------------------------------------------------------------------
# Hidden-text stripping (ADR-070/075 decision 5, issue #1218) — ordering.
# ---------------------------------------------------------------------------


class TestInboundStripsHiddenTextFromVendorTextBeforeScanning:
    """Ordering matters: `guard_inbound_tool_result` must strip hidden text
    from vendor fields *before* running `find_banned_pattern_hits`, not
    after. A banned word split by an invisible character would evade the
    banned-pattern regex if the scan ran first — stripping first closes
    that evasion route, and is the reason this module's stripping runs
    ahead of the pre-existing scan-and-block gate rather than behind it.
    """

    def test_zero_width_obfuscated_banned_word_is_still_caught(self):
        # "web​hook" would not match `\bwebhook\b` if scanned before
        # the zero-width space is removed — this proves strip-then-scan.
        obfuscated = "web​hook"
        planted = {"description": {"source": "vendor", "text": f"Contact us via {obfuscated}."}}

        result = guard_inbound_tool_result(planted, tool_name="get_product_information")

        assert set(result) == {"error"}

    def test_hidden_characters_are_stripped_from_an_otherwise_clean_vendor_result(self):
        planted = {"description": {"source": "vendor", "text": "Nice product​​today"}}

        result = guard_inbound_tool_result(planted, tool_name="get_product_information")

        assert result == {"description": {"source": "vendor", "text": "Nice producttoday"}}

    def test_seller_text_is_not_stripped(self):
        planted = {"note": {"source": "seller", "text": "keep​this"}}

        result = guard_inbound_tool_result(planted, tool_name="get_product_information")

        assert result == {"note": {"source": "seller", "text": "keep​this"}}

    def test_vietnamese_diacritics_and_emoji_in_vendor_text_survive_the_guard(self):
        text = "Giao hàng nhanh 🚚 chất lượng tốt 👍"
        planted = {"description": {"source": "vendor", "text": text}}

        result = guard_inbound_tool_result(planted, tool_name="get_product_information")

        assert result == {"description": {"source": "vendor", "text": text}}

    def test_clean_result_with_nothing_to_strip_preserves_object_identity(self):
        """`WorkflowRunner._dispatch_tool_call` (runner/core.py) computes its
        `tool.completed` telemetry as `sanitized is raw_result` — this is
        the regression this module's stripping must never break: a result
        with no hidden characters (and no banned-pattern hit) must come
        back as the exact same object, not an equal-but-rebuilt copy.
        """
        clean = _deeply_nested_tool_result(banned_value="a completely unrelated value")

        result = guard_inbound_tool_result(clean, tool_name="get_product_reviews")

        assert result is clean
