"""Deterministic ``dedup_key`` per event (shared by the live writers and the backfill).

A key names the fact, not the writer: the live path and the backfill derive
the same key for the same stage, so whichever lands first is the only row.
"""

from __future__ import annotations

import uuid


def proposed(card_id: uuid.UUID) -> str:
    return f"proposed:{card_id}"


def shown(card_id: uuid.UUID) -> str:
    return f"shown:{card_id}"


def accepted(approval_id: uuid.UUID) -> str:
    """Per approval: a card put back on the desk by a failed run (D47.5) can be approved again."""
    return f"accepted:{approval_id}"


def dismissed(card_id: uuid.UUID) -> str:
    return f"dismissed:{card_id}"


def expired(card_id: uuid.UUID) -> str:
    return f"expired:{card_id}"


def superseded(card_id: uuid.UUID) -> str:
    return f"superseded:{card_id}"


def run_outcome(run_id: uuid.UUID) -> str:
    """One of ``executed`` / ``not_executed`` per run."""
    return f"run_outcome:{run_id}"


def reverted(revert_run_id: uuid.UUID) -> str:
    return f"reverted:{revert_run_id}"


def impact(event_type: str, run_id: uuid.UUID) -> str:
    """One ``impact_preliminary`` and one ``impact_final`` per run."""
    return f"{event_type}:{run_id}"


def seller_change(external_change_id: uuid.UUID) -> str:
    """One ``seller_change`` per ``external_changes`` row (amendment §8)."""
    return f"seller_change:{external_change_id}"
