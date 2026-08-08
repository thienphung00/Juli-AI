"""Unit tests for the public Demo Decisions read masking transform (#718, B-6).

`services.demo_decisions.read.mask_decision_payload` is an allowlist mapper
over a persisted `ActionCard` row — it must never forward the raw
`recommendation_payload` JSON dict verbatim (that dict always carries
`workflow_key`, per `services.action_cards.persist._build_payload`), and it
must never introduce `tool_name` (an internal `ToolExecution` concept this
module never touches).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from juli_backend.models.models import ActionCard
from juli_backend.services.demo_decisions.read import mask_decision_payload


def _card(**overrides) -> ActionCard:
    defaults = dict(
        id=uuid.uuid4(),
        shop_id=uuid.uuid4(),
        workflow_key="prevent_return_8b",
        priority=1,
        severity="warning",
        title="Prevent likely returns",
        description="Returns are trending up for this SKU.",
        recommendation_payload=json.dumps(
            {
                "workflow_key": "prevent_return_8b",
                "workflow_name": "Prevent likely returns",
                "priority": 1,
                "rationale": "Return rate is elevated.",
                "expected_impact": {"metric": "return_rate", "value": 0.02, "confidence": "medium"},
                "preconditions_met": True,
                "user_action_required": True,
                "source_kpi_ids": ["return_request_rate"],
                "computed_at": "2026-08-08T08:00:00+00:00",
                "reasoning": {
                    "copy_source": "rules",
                    "why": "Returns are trending up.",
                    "expected_impact": "Lower return rate.",
                    "next_steps": ["Review packaging"],
                    "source_kpi_ids": ["return_request_rate"],
                },
            }
        ),
        status="active",
        computed_at=datetime(2026, 8, 8, 8, 0, tzinfo=UTC),
        surfaced_at=datetime(2026, 8, 8, 8, 5, tzinfo=UTC),
        suppressed_reason=None,
    )
    defaults.update(overrides)
    return ActionCard(**defaults)


def test_mask_decision_payload_never_forwards_workflow_key() -> None:
    card = _card()
    masked = mask_decision_payload(card)

    assert json.dumps(masked).count("workflow_key") == 0
    assert masked["recommendation"]["workflow_name"] == "Prevent likely returns"


def test_mask_decision_payload_exposes_opaque_card_id_not_workflow_key() -> None:
    card = _card()
    masked = mask_decision_payload(card)

    assert masked["id"] == str(card.id)


def test_mask_decision_payload_never_introduces_tool_name() -> None:
    card = _card()
    masked = mask_decision_payload(card)

    assert "tool_name" not in json.dumps(masked)


def test_mask_decision_payload_carries_freshness_metadata() -> None:
    card = _card()
    masked = mask_decision_payload(card)

    assert masked["computed_at"] == "2026-08-08T08:00:00+00:00"
    assert masked["surfaced_at"] == "2026-08-08T08:05:00+00:00"


def test_mask_decision_payload_allowlist_drops_unexpected_recommendation_keys() -> None:
    """Defense-in-depth: even if recommendation_payload somehow carried extra
    internal keys (a future bug upstream), the allowlist mapper must not
    forward anything outside its known-safe field set."""
    poisoned_payload = json.dumps(
        {
            "workflow_key": "internal_wf_secret_734",
            "workflow_name": "Prevent likely returns",
            "priority": 1,
            "rationale": "Return rate is elevated.",
            "expected_impact": {"metric": "return_rate", "value": 0.02, "confidence": "medium"},
            "preconditions_met": True,
            "user_action_required": True,
            "source_kpi_ids": ["return_request_rate"],
            "computed_at": "2026-08-08T08:00:00+00:00",
            "tool_name": "tiktok_create_activity",
            "internal_shop_uuid": "11111111-2222-3333-4444-555555555555",
            "raw_balance_vnd": 987654321.99,
        }
    )
    card = _card(recommendation_payload=poisoned_payload)
    masked = mask_decision_payload(card)
    serialized = json.dumps(masked)

    assert "internal_wf_secret_734" not in serialized
    assert "tool_name" not in serialized
    assert "tiktok_create_activity" not in serialized
    assert "11111111-2222-3333-4444-555555555555" not in serialized
    assert "987654321.99" not in serialized


def test_mask_decision_payload_handles_malformed_recommendation_payload_gracefully() -> None:
    card = _card(recommendation_payload="not-json")
    masked = mask_decision_payload(card)

    assert masked["recommendation"] == {}
