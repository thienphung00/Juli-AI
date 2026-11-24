"""C2 (batch-1123-a): every reader's run outcome is stored as ok / empty / blocked / error +
reason. Synthetic notes in the Connector's own format."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from juli_backend.models.ops import OpsAuditLog
from juli_backend.services.ingest import reader_status as rs
from juli_backend.services.ingest.rate_limit import InMemoryRateGate, set_ingest_rate_gate
from juli_backend.services.shopee_recommendations.connector_state import ACTION_CONNECTOR_TICK
from tests.support.api import client_for
from tests.unit.test_ingest_gateway import _paired_client, _shopee_tenant


@pytest.mark.parametrize(
    ("outcome", "status", "reason"),
    [
        ("done:traffic_overview=posted,shop_traffic=posted", "ok", None),
        ("done:order_lines=empty", "empty", "empty"),
        ("done:item_by_source=ignored", "empty", "empty"),
        ("done:shop_overview=posted,promotion_daily=empty", "ok", None),
        ("done:ads_campaign_daily=rejected", "error", "ads_campaign_daily=rejected"),
        ("done:item_traffic_sources=drift", "error", "item_traffic_sources=drift"),
        ("done:affiliate_partner_period=held", "ok", None),
        ("done", "ok", None),
        ("fresh", "ok", "fresh"),
        ("no_orders", "empty", "no_orders"),
        ("no_campaigns", "empty", "no_campaigns"),
        ("blocked:login", "blocked", "login"),
        ("blocked:no_permission|reader_only", "blocked", "no_permission"),
        ("waiting_budget", "blocked", "budget"),
        (
            "error:order_income:0_rows:no_ids_from_page",
            "error",
            "error:order_income:0_rows:no_ids_from_page",
        ),
        ("timeout", "error", "timeout"),
        ("needs_template:orders/list", "error", "needs_template:orders/list"),
        ("partial:page_cap", "error", "partial:page_cap"),
        # Connector 0.3.32: one reader opened twice in a run, merged worst first
        (
            "timeout|done:ads_campaign_daily:2026-11-02=posted",
            "error",
            "timeout|done:ads_campaign_daily:2026-11-02=posted",
        ),
        ("blocked:login|done:item_traffic_sources=posted", "blocked", "login"),
        ("done:order_lines=empty|done:order_lines=empty", "empty", "done:order_lines=empty"),
    ],
)
def test_each_connector_outcome_folds_into_one_status_and_reason(outcome, status, reason):
    assert rs.status_of(outcome) == {"status": status, "reason": reason}


async def test_the_run_report_stores_a_status_per_reader(session):
    set_ingest_rate_gate(InMemoryRateGate())
    try:
        user, shop = await _shopee_tenant(session)
        app, code = await _paired_client(session, shop, user)
        async with client_for(app) as ext:
            paired = await ext.post("/v1/ingest/pair", json={"code": code, "platform": "shopee"})
            auth = {"Authorization": f"Bearer {paired.json()['token']}"}
            tick = {
                "platform": "shopee",
                "kind": "run",
                "trigger": "daily",
                "result": "finished",
                "day": "2026-11-22",
                "source_version": "0.3.32",
                "outcomes": {
                    "traffic": "done:traffic_overview=posted",
                    "orders": "done:order_lines=empty",
                    "order_income": "error:order_income:0_rows:no_ids_from_page",
                    "item_traffic": "blocked:password_recheck",
                },
            }
            res = await ext.post("/v1/ingest/connector-ticks", headers=auth, json=tick)
        assert res.status_code == 202, res.text
        row = (
            await session.execute(
                select(OpsAuditLog).where(OpsAuditLog.action == ACTION_CONNECTOR_TICK)
            )
        ).scalar_one()
        assert row.after["readers"] == {
            "traffic": {"status": "ok", "reason": None},
            "orders": {"status": "empty", "reason": "empty"},
            "order_income": {
                "status": "error",
                "reason": "error:order_income:0_rows:no_ids_from_page",
            },
            "item_traffic": {"status": "blocked", "reason": "password_recheck"},
        }
        assert row.after["outcomes"]["orders"] == "done:order_lines=empty"
    finally:
        set_ingest_rate_gate(None)


def test_a_refusal_with_its_reason_is_still_an_error() -> None:
    """Connector 0.3.34 names the reason after the head: ``rejected:period_too_long``."""
    status = rs.status_of("done:order_lines=rejected:period_too_long")
    assert status["status"] == "error"
    assert status["reason"] == "order_lines=rejected:period_too_long"
