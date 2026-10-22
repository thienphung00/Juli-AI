"""Format advisory signals per visual_layer.md rendering principles."""

from __future__ import annotations

from juli_backend.services.scoring.types import SignalType

#: Seller-facing label per signal type.
_SIGNAL_LABELS_VI: dict[str, str] = {"risk": "Rủi ro", "opportunity": "Cơ hội"}


def format_advisory_one_line(
    change_text: str,
    signal_type: SignalType,
    action_hint: str,
) -> str:
    """What changed → Rủi ro/Cơ hội → Action (visual_layer.md § Rendering principles).

    The line reaches sellers as a card's "Lý do" (``copy_layer._build_why``), so it is
    Vietnamese only (P64, D73.3): no internal ``risk`` / ``opportunity`` / ``unavailable``.
    """
    if signal_type == "unavailable":
        return f"{change_text} · {action_hint}"
    return f"{change_text} · {_SIGNAL_LABELS_VI.get(signal_type, 'Lưu ý')}: {action_hint}"
