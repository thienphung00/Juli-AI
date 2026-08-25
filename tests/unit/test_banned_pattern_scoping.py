"""Banned patterns are scoped per surface (issue #1210).

A real run on the VPS reached `final_response` and was killed by its own
outbound guard. The patterns it tripped were authored against the
*deterministic copy layer*, where `Độ tin cậy:` is a debug label escaping into
seller copy. Enforced verbatim on agent prose, the same strings are ordinary
Vietnamese — and `\\bconfirm\\b`, `\\bship\\b`, `\\ban toàn\\b` are words no
seller-facing sentence can avoid.

These tests pin three things: the copy layer keeps every pattern, the agent
surface keeps the ones that catch genuine internal leaks, and a missing
`scopes` key still means BOTH so a new pattern is never silently narrower.
"""

from __future__ import annotations

import json

import pytest

from juli_backend.services.agent.sanitize.banned_patterns import (
    AGENT_OUTPUT_SCOPE,
    COPY_LAYER_SCOPE,
    load_banned_pattern_entries,
    load_banned_patterns,
)
from juli_backend.services.agent.sanitize.chokepoints import (
    BannedPatternGuardFailure,
    find_banned_pattern_hits,
    guard_outbound_agent_output,
)

#: Verbatim shapes of what the agent legitimately writes. Every one of these
#: made a real run fatal before scoping.
LEGITIMATE_AGENT_SENTENCES = [
    "Độ tin cậy: cao — ảnh khớp với tiêu đề sản phẩm.",
    "Công cụ: đã kiểm tra ảnh sản phẩm.",
    "Khả năng: có thể cải thiện tiêu đề.",
    "Sản phẩm này an toàn cho người dùng hằng ngày.",
    "Please confirm the price change before we ship the update.",
    "Get Product details showed a 14mL bottle.",
]

#: Genuine internal leaks. These must stay fatal on the agent surface -- the
#: point of #1210 is narrowing to the right patterns, not weakening the guard.
INTERNAL_LEAKS = [
    "tool_name: get_product_information",
    "workflow_key optimize_product_2 failed",
    "the webhook did not fire",
    "check the endpoint response",
    "listing.update_product_listing returned",
    "listing.title cannot be empty",
    "listing.description is required",
    "the executor raised",
]

#: Issue #1304: sentence-final "listing." should pass only on the agent surface.
#: These sentences are legitimate agent output but are scoped to agent_output only.
AGENT_SURFACE_ONLY_SENTENCES = [
    "Optimize your listing.",
    "Tối ưu listing.",
    "Next step is to improve your listing. You should add more details.",
]


class TestTheCopyLayerIsUnchanged:
    """#1210 must not weaken the surface these patterns were written for."""

    def test_default_scope_keeps_every_pattern(self):
        assert len(load_banned_patterns()) == len(load_banned_pattern_entries())

    def test_copy_layer_scope_keeps_every_pattern(self):
        assert len(load_banned_patterns(COPY_LAYER_SCOPE)) == len(load_banned_patterns())

    @pytest.mark.parametrize("text", LEGITIMATE_AGENT_SENTENCES)
    def test_copy_layer_still_rejects_what_it_always_rejected(self, text):
        """The same sentence that is fine from the agent is still a defect from
        the deterministic copy layer -- that asymmetry is the whole design."""
        entries = load_banned_pattern_entries(scope=COPY_LAYER_SCOPE)
        patterns = load_banned_patterns(COPY_LAYER_SCOPE)
        assert any(p.search(text) for p in patterns), (
            f"copy-layer scope no longer catches {text!r}; #1210 was supposed to "
            f"narrow only the agent surface ({len(entries)} entries loaded)"
        )


class TestTheAgentSurfaceAllowsOrdinaryLanguage:
    @pytest.mark.parametrize("text", LEGITIMATE_AGENT_SENTENCES)
    def test_legitimate_seller_prose_is_not_a_hit(self, text):
        assert find_banned_pattern_hits(text, scope=AGENT_OUTPUT_SCOPE) == ()

    @pytest.mark.parametrize("text", LEGITIMATE_AGENT_SENTENCES)
    def test_the_outbound_guard_lets_it_through(self, text):
        guard_outbound_agent_output({"content": text})

    @pytest.mark.parametrize("text", AGENT_SURFACE_ONLY_SENTENCES)
    def test_agent_surface_only_sentences_pass(self, text):
        """Issue #1304: sentence-final 'listing.' passes on agent surface but
        would fail on copy layer (scoped to agent_output only)."""
        assert find_banned_pattern_hits(text, scope=AGENT_OUTPUT_SCOPE) == ()

    @pytest.mark.parametrize("text", AGENT_SURFACE_ONLY_SENTENCES)
    def test_agent_surface_only_outbound_guard_lets_it_through(self, text):
        guard_outbound_agent_output({"content": text})


class TestTheAgentSurfaceStillCatchesRealLeaks:
    """Narrowing must not become weakening."""

    @pytest.mark.parametrize("text", INTERNAL_LEAKS)
    def test_internal_identifiers_still_fail_closed(self, text):
        with pytest.raises(BannedPatternGuardFailure):
            guard_outbound_agent_output({"content": text})

    def test_a_leak_nested_in_structured_output_is_caught(self):
        with pytest.raises(BannedPatternGuardFailure):
            guard_outbound_agent_output(
                {"content": "ok", "structured_output": {"note": "workflow_key leaked"}}
            )


class TestScopesDefaultToBoth:
    """A pattern with no `scopes` key must apply everywhere. Otherwise adding a
    pattern without thinking about scope silently narrows the guard -- the
    failure mode this whole issue is an instance of."""

    def test_missing_scopes_key_counts_as_both(self, tmp_path):
        source = tmp_path / "patterns.json"
        source.write_text(
            json.dumps(
                {"$comment": "t", "patterns": [{"id": "x", "source": "leaky", "flags": ""}]}
            ),
            encoding="utf-8",
        )
        for scope in (None, COPY_LAYER_SCOPE, AGENT_OUTPUT_SCOPE):
            assert len(load_banned_pattern_entries(source, scope=scope)) == 1

    def test_every_shipped_pattern_declares_its_scopes(self):
        """The real file must be explicit -- relying on the default would make
        the intent unreviewable."""
        for entry in json.loads(
            __import__("pathlib")
            .Path("packages/contracts/seller-copy-banned-patterns.json")
            .read_text(encoding="utf-8")
        )["patterns"]:
            assert entry.get("scopes"), f"pattern {entry['id']!r} has no scopes"
            assert set(entry["scopes"]) <= {COPY_LAYER_SCOPE, AGENT_OUTPUT_SCOPE}
