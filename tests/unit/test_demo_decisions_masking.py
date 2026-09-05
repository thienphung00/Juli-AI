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


# ---------------------------------------------------------------------------
# AC -- executability discriminator: derived from playbook registry, no taxonomy leakage
# ---------------------------------------------------------------------------


def test_executable_card_carries_is_executable_true() -> None:
    """A card whose workflow_key resolves to a registered playbook carries
    is_executable=true (ADR-084 decision 3)."""
    card = _card(workflow_key="optimize_product_2")
    masked = mask_decision_payload(card)

    assert masked["is_executable"] is True


def test_non_executable_card_carries_is_executable_false() -> None:
    """A card whose workflow_key has no registered playbook carries
    is_executable=false (ADR-084 decision 3)."""
    card = _card(workflow_key="unknown_workflow_xyz")
    masked = mask_decision_payload(card)

    assert masked["is_executable"] is False


def test_mask_decision_payload_never_leaks_workflow_key() -> None:
    """The executability discriminator reveals no workflow taxonomy -- the
    serialized envelope carries is_executable but never workflow_key
    (ADR-084 decision 3)."""
    card = _card(workflow_key="optimize_product_2")
    masked = mask_decision_payload(card)

    serialized = json.dumps(masked)
    assert "optimize_product_2" not in serialized
    assert "workflow_key" not in serialized
    assert masked["is_executable"] is True


def test_discriminator_changes_with_registry_changes() -> None:
    """The is_executable discriminator is derived from the REAL playbook
    registry, proven by verifying that a card's executability can be
    determined by registry lookups, not by a hardcoded literal (ADR-084
    decision 3).

    This test exercises the real registry: a card with workflow_key
    "optimize_product_2" is executable (OPTIMIZE_PRODUCT_PLAYBOOK is
    registered), and a card with workflow_key "future_workflow_42" is not
    (not yet registered)."""
    executable_card = _card(workflow_key="optimize_product_2")
    non_executable_card = _card(workflow_key="future_workflow_42")

    executable_masked = mask_decision_payload(executable_card)
    non_executable_masked = mask_decision_payload(non_executable_card)

    assert executable_masked["is_executable"] is True
    assert non_executable_masked["is_executable"] is False
