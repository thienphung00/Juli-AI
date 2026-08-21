"""Vietnamese `phase_narration` copy — issue #1140.

`services/agent/narration_copy.py` holds the VI-locale text for
`workflow.status`'s `phase_narration` field (ADR-074 decision 2;
`events/payloads.py::WorkflowStatusPayload`'s own docstring). These tests
prove two mechanical things: the numbers stay dynamic (never a literal in
the produced sentence beyond what the caller passed in), and the produced
copy passes the *real* shared seller-copy banned-pattern gate on the
`AGENT_OUTPUT_SCOPE` surface — not a hand-copied pattern list.

**What these tests do NOT and cannot prove**: that the Vietnamese reads
naturally, uses the correct register, or matches `dictionary.md` voice
rules. That is a human judgment call (#1071's precedent: mechanical gates
cannot judge Vietnamese voice) and is still outstanding for this string —
see the module docstring and the #1140 PR description.
"""

from __future__ import annotations

import pytest

from juli_backend.services.agent.narration_copy import extension_grant_phase_narration
from juli_backend.services.agent.sanitize.banned_patterns import AGENT_OUTPUT_SCOPE
from juli_backend.services.agent.sanitize.chokepoints import find_banned_pattern_hits


class TestExtensionGrantPhaseNarrationNumbers:
    """Every number in the sentence must be exactly what was passed in --
    this module defines no policy constant of its own."""

    @pytest.mark.parametrize(
        ("extension_iterations", "granted", "max_extensions"),
        [
            (2, 1, 1),
            (9, 2, 5),
            (1, 3, 3),
        ],
    )
    def test_every_input_number_appears_verbatim(
        self, extension_iterations: int, granted: int, max_extensions: int
    ) -> None:
        text = extension_grant_phase_narration(
            extension_iterations=extension_iterations,
            extensions_granted_after_grant=granted,
            max_extensions=max_extensions,
        )
        assert str(extension_iterations) in text
        assert f"{granted}/{max_extensions}" in text

    def test_text_is_vietnamese(self) -> None:
        text = extension_grant_phase_narration(
            extension_iterations=2,
            extensions_granted_after_grant=1,
            max_extensions=1,
        )
        assert "gia hạn" in text
        assert "Continuing" not in text


class TestExtensionGrantPhaseNarrationPassesTheSharedBannedPatternGate:
    """Calls the real shared loader (`AGENT_OUTPUT_SCOPE`) — never a
    hand-copied pattern list — the same gate `guard_outbound_agent_output`
    enforces on every other agent-authored output."""

    @pytest.mark.parametrize(
        ("extension_iterations", "granted", "max_extensions"),
        [
            (2, 1, 1),
            (9, 2, 5),
            (1, 3, 3),
            (10, 10, 10),
        ],
    )
    def test_no_banned_pattern_hits(
        self, extension_iterations: int, granted: int, max_extensions: int
    ) -> None:
        text = extension_grant_phase_narration(
            extension_iterations=extension_iterations,
            extensions_granted_after_grant=granted,
            max_extensions=max_extensions,
        )
        assert find_banned_pattern_hits(text, scope=AGENT_OUTPUT_SCOPE) == ()
