"""Tests for Phase 2.10 Mock-mode hourly Analytics reconciler (#533)."""

from __future__ import annotations

import uuid

import pytest

from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks import mock_analytics_reconcile


@pytest.fixture
def reference_shop_id() -> uuid.UUID:
    return uuid.uuid4()


def test_celery_beat_hourly_entrypoint_recomputes_reference_shop():
    schedule = celery_app.conf.beat_schedule["mock-analytics-hourly-reconcile"]
    assert schedule["task"] == "juli_backend.mock_analytics_hourly_reconcile"
    assert schedule["schedule"].minute == {0}


def test_mock_reconcile_invokes_precompute_for_configured_shop_id_only(
    monkeypatch,
    reference_shop_id: uuid.UUID,
):
    calls: list[str] = []

    def fake_precompute(shop_key: str) -> None:
        calls.append(shop_key)

    monkeypatch.setenv("DEMO_REFERENCE_SHOP_ID", str(reference_shop_id))
    monkeypatch.setattr(
        mock_analytics_reconcile,
        "_lookup_tiktok_shop_key",
        lambda _shop_id: "tiktok-reference-shop",
    )

    mock_analytics_reconcile.run_mock_analytics_reconcile_sync(precompute_fn=fake_precompute)

    assert calls == ["tiktok-reference-shop"]


def test_mock_reconcile_does_not_fan_out_to_all_shops(
    monkeypatch,
    reference_shop_id: uuid.UUID,
):
    calls: list[str] = []

    def fake_precompute(shop_key: str) -> None:
        calls.append(shop_key)

    monkeypatch.setenv("DEMO_REFERENCE_SHOP_ID", str(reference_shop_id))
    monkeypatch.setattr(
        mock_analytics_reconcile,
        "_lookup_tiktok_shop_key",
        lambda _shop_id: "only-reference-shop",
    )

    mock_analytics_reconcile.run_mock_analytics_reconcile_sync(precompute_fn=fake_precompute)

    assert len(calls) == 1
    assert calls[0] == "only-reference-shop"


def test_mock_reconcile_skips_when_demo_reference_shop_id_unset(monkeypatch):
    calls: list[str] = []

    def fake_precompute(shop_key: str) -> None:
        calls.append(shop_key)

    monkeypatch.delenv("DEMO_REFERENCE_SHOP_ID", raising=False)

    mock_analytics_reconcile.run_mock_analytics_reconcile_sync(precompute_fn=fake_precompute)

    assert calls == []


def test_mock_reconcile_uses_material_precompute_path(monkeypatch, reference_shop_id: uuid.UUID):
    """Idempotent upsert path shared with material-webhook compute (#532)."""
    calls: list[str] = []

    def fake_precompute(shop_key: str) -> None:
        calls.append(shop_key)

    monkeypatch.setenv("DEMO_REFERENCE_SHOP_ID", str(reference_shop_id))
    monkeypatch.setattr(
        mock_analytics_reconcile,
        "_lookup_tiktok_shop_key",
        lambda _shop_id: "shared-upsert-shop",
    )
    monkeypatch.setattr(
        mock_analytics_reconcile,
        "material_analytics_precompute_sync",
        fake_precompute,
    )

    mock_analytics_reconcile.run_mock_analytics_reconcile_sync()

    assert calls == ["shared-upsert-shop"]
