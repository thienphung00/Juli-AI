"""Format advisory signals per visual_layer.md rendering principles."""

from __future__ import annotations

from juli_backend.services.scoring.types import SignalType


def format_advisory_one_line(
    change_text: str,
    signal_type: SignalType,
    action_hint: str,
) -> str:
    """What changed → Risk/Opportunity → Action (visual_layer.md § Rendering principles)."""
    if signal_type == "unavailable":
        return f"{change_text} · unavailable: {action_hint}"
    return f"{change_text} · {signal_type}: {action_hint}"
