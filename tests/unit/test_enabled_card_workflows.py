"""Only Tối ưu sản phẩm and content cards reach Quyết định (owner, 2026-10-11)."""

from __future__ import annotations

import pytest

from juli_backend.services.action_cards.persist import enabled_card_workflows


def test_default_allows_only_optimize_product_and_content(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CDP_ENABLED_WORKFLOWS", raising=False)
    enabled = enabled_card_workflows()
    assert enabled is not None
    assert enabled == {"optimize_product_2", "content_video", "content_live", "campaign_plan"}
    for legacy in (
        "replenish_inventory",
        "process_orders",
        "handle_returns",
        "clear_excess_inventory",
    ):
        assert legacy not in enabled


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CDP_ENABLED_WORKFLOWS", " optimize_product_2 , content_video ")
    assert enabled_card_workflows() == {"optimize_product_2", "content_video"}


def test_star_enables_every_workflow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CDP_ENABLED_WORKFLOWS", "*")
    assert enabled_card_workflows() is None
