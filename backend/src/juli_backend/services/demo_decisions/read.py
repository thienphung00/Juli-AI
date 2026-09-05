"""Public Demo Decisions read query + masking transform (#718, B-6).

Read-only over persistence already landed in #715 (B-3, ``persist.py``) and
#716 (B-4, ``emission_budget.py``) — this module writes nothing and imports
neither of those two modules' functions, only the ``ActionCard`` model they
both operate on. "Emission-gated" means ``ActionCard.surfaced_at``-gated:
only a candidate the emission budget most recently surfaced is part of the
public active set this module serves.

``mask_decision_payload`` is a strict **allowlist** mapper, not a blocklist —
it copies only known-safe fields out of ``ActionCard.recommendation_payload``
(a JSON blob built by ``services.action_cards.persist._build_payload``, which
always includes ``workflow_key``). This is deliberate defense-in-depth: even
if a future bug ever put an unexpected key into that JSON blob (an internal
identifier, a ``tool_name``, anything else), the allowlist drops it silently
rather than forwarding it into a public, unauthenticated response body.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ActionCard

# Only "active" candidates are ever eligible for the surfaced set — mirrors
# emission_budget._CANDIDATE_STATUS. A card whose status has moved on
# (approved / dismissed / executing) is excluded even if a stale
# ``surfaced_at`` value remains from before that transition, since
# apply_emission_budget stops evaluating a card the moment it leaves
# "active" and never clears surfaced_at on that card's behalf.
_CANDIDATE_STATUS = "active"

_RECOMMENDATION_ALLOWLIST: tuple[str, ...] = (
    "workflow_name",
    "priority",
    "rationale",
    "preconditions_met",
    "user_action_required",
    "source_kpi_ids",
)

_EXPECTED_IMPACT_ALLOWLIST: tuple[str, ...] = ("metric", "value", "confidence")

_REASONING_ALLOWLIST: tuple[str, ...] = (
    "copy_source",
    "why",
    "expected_impact",
    "next_steps",
    "source_kpi_ids",
)


class DecisionNotFound(ValueError):
    """Raised when no emission-gated (surfaced) Decision matches the lookup."""


def _mask_recommendation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Allowlist copy — never forwards ``workflow_key`` or any other key
    outside the known-safe set (see module docstring)."""
    masked: dict[str, Any] = {
        key: payload[key] for key in _RECOMMENDATION_ALLOWLIST if key in payload
    }

    expected_impact = payload.get("expected_impact")
    if isinstance(expected_impact, dict):
        masked["expected_impact"] = {
            key: expected_impact[key]
            for key in _EXPECTED_IMPACT_ALLOWLIST
            if key in expected_impact
        }

    reasoning = payload.get("reasoning")
    if isinstance(reasoning, dict):
        masked["reasoning"] = {
            key: reasoning[key] for key in _REASONING_ALLOWLIST if key in reasoning
        }

    return masked


def mask_decision_payload(card: ActionCard) -> dict[str, Any]:
    """Build the public Demo envelope dict for one surfaced ``ActionCard``.

    Exposes the card's own ``id`` as the stable per-card identifier (opaque
    to a public visitor — never ``workflow_key``, per #718 AC3 and the
    precedent set by ``POST /v1/demo/decisions/{id}/approve``'s response,
    which likewise omits ``workflow_key``). ``title``/``description`` are
    rules-engine-generated Decision copy (``persist._build_payload`` /
    ``WorkflowReasoningCopy``) — legitimate, intended-for-display content,
    not visitor input — and are forwarded as-is, matching the existing
    authenticated ``GET /v1/action-cards`` precedent
    (``api/routes/action_cards.py::_to_item``).

    ADR-084 decision 3: includes an ``is_executable`` discriminator derived
    from the real playbook registry, revealing whether Juli can carry this
    recommendation out itself, without exposing the workflow_key or any
    taxonomy.
    """
    try:
        raw_payload = json.loads(card.recommendation_payload) if card.recommendation_payload else {}
        if not isinstance(raw_payload, dict):
            raw_payload = {}
    except json.JSONDecodeError:
        raw_payload = {}

    from juli_backend.services.agent import playbooks as playbooks_module

    return {
        "id": str(card.id),
        "title": card.title,
        "description": card.description,
        "severity": card.severity,
        "priority": card.priority,
        "computed_at": card.computed_at.isoformat() if card.computed_at else None,
        "surfaced_at": card.surfaced_at.isoformat() if card.surfaced_at else None,
        "is_executable": playbooks_module.is_workflow_executable(card.workflow_key),
        "recommendation": _mask_recommendation_payload(raw_payload),
    }


async def list_surfaced_decisions(session: AsyncSession, shop_id: uuid.UUID) -> list[ActionCard]:
    """Emission-gated active set for *shop_id* — ``surfaced_at IS NOT NULL``.

    Ranked by ``priority`` ascending (mirrors ``apply_emission_budget``'s own
    candidate ordering), ``surfaced_at`` descending, then ``id`` for a fully
    deterministic tiebreak.
    """
    stmt = (
        select(ActionCard)
        .where(
            ActionCard.shop_id == shop_id,
            ActionCard.status == _CANDIDATE_STATUS,
            ActionCard.surfaced_at.isnot(None),
        )
        .order_by(
            ActionCard.priority.asc(),
            ActionCard.surfaced_at.desc(),
            ActionCard.id.asc(),
        )
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_surfaced_decision(
    session: AsyncSession, shop_id: uuid.UUID, action_card_id: uuid.UUID
) -> ActionCard:
    """Single emission-gated Decision, tenant-scoped.

    Raises ``DecisionNotFound`` for a nonexistent id, a card belonging to a
    different shop, or a card that exists but is not currently surfaced
    (suppressed, or status has moved past "active") — the safe default: a
    suppressed or foreign card is indistinguishable from a nonexistent one to
    the caller, so detail lookup never leaks existence.
    """
    stmt = select(ActionCard).where(
        ActionCard.id == action_card_id,
        ActionCard.shop_id == shop_id,
        ActionCard.status == _CANDIDATE_STATUS,
        ActionCard.surfaced_at.isnot(None),
    )
    result = await session.execute(stmt)
    card = result.scalar_one_or_none()
    if card is None:
        raise DecisionNotFound(f"Decision {action_card_id} not found for shop {shop_id}")
    return card
