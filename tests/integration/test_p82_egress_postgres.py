"""P82 on real Postgres, as ``juli_app`` under the shop's scope: the reads that used to ship
JSON blobs pick their few facts in SQL.

- The sandbox reviewer's runs list reads a run's Ngày 0 diagnosis through a jsonpath
  (``jsonb_path_query_array``) -- the same reading :func:`day0_reading` takes from the
  whole ``state`` -- and never selects ``state`` itself.
- The B12 hook reads ``report->>'metrics_source'`` and the end date, not the report.
- The decisions list reads each card's latest run (a window) without ``state``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.models import (
    ActionCard,
    ActionCardApproval,
    Product,
    Shop,
    ToolExecution,
    User,
    WorkflowRun,
)
from juli_backend.models.shop_diagnosis import ShopDiagnosisReport
from juli_backend.repositories import ShopDiagnosisReportsRepo
from juli_backend.services.agent_runs import listing_quality
from juli_backend.services.agent_runs.listing import RunViewer, list_runs
from juli_backend.services.agent_runs.listing_quality import day0_reading
from juli_backend.services.demo_decisions.card_view import load_card_contexts
from tests.support.postgres import juli_app_async_sessionmaker, owner_sync_engine, requires_postgres

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

T0 = datetime(2026, 10, 20, 8, 0, 0)
CODES = [{"code": "TITLE_LESS_THAN_40_CHARACTERS", "label_vi": "Tiêu đề quá ngắn"}]

#: Each state's conversation window, and what the Ngày 0 reading must be.
WINDOWS: list[Any] = [
    # The first readable diagnosis wins; an unavailable one and non-messages are skipped.
    [
        "x",
        {"role": "tool", "tool_name": "get_product_diagnoses", "content": {"unavailable": True}},
        {"role": "tool", "tool_name": "get_product_diagnoses", "content": {"codes": CODES}},
        {"role": "tool", "tool_name": "get_product_diagnoses", "content": {"count": 9}},
    ],
    # No diagnosis step at all.
    [{"role": "assistant", "content": "a" * 20_000}],
    # A window that is not a list, and a content that is not an object.
    {"role": "tool", "tool_name": "get_product_diagnoses", "content": {"count": 3}},
    [{"role": "tool", "tool_name": "get_product_diagnoses", "content": "text"}],
]


def _seed() -> dict[str, Any]:
    owner, reviewer, shop, product = (uuid.uuid4() for _ in range(4))
    runs: list[uuid.UUID] = []
    cards: list[uuid.UUID] = []
    with owner_sync_engine() as engine, Session(engine) as s:
        s.add_all(
            [
                User(id=owner, phone=f"+1582{owner.int % 10**7:07d}"),
                User(id=reviewer, phone=f"+1583{reviewer.int % 10**7:07d}"),
            ]
        )
        s.flush()
        s.add(
            Shop(id=shop, user_id=owner, shop_name="P82", tiktok_shop_id=f"76{shop.int % 10**12}")
        )
        s.flush()
        s.add(
            Product(
                id=product,
                shop_id=shop,
                tiktok_product_id="1730000000000008282",
                name="Áo P82",
                title="Áo P82",
                status="ACTIVATE",
                update_time=T0,
            )  # fmt: skip
        )
        s.flush()
        for n, window in enumerate(WINDOWS):
            card = ActionCard(
                shop_id=shop, workflow_key="optimize_product_2", subject_type="product",
                subject_id=str(product), revision=n + 1, priority=0, severity="medium",
                title="x", description="", recommendation_payload="{}", status="approved",
            )  # fmt: skip
            s.add(card)
            s.flush()
            cards.append(card.id)
            s.add(
                ActionCardApproval(
                    action_card_id=card.id,
                    approved_by_user_id=reviewer,
                    approved_at=T0,
                    card_snapshot={},
                )  # fmt: skip
            )
            for again in (0, 1):  # two runs per card; the newer one is the card's latest
                run = WorkflowRun(
                    shop_id=shop, product_id=product, action_card_id=card.id,
                    subject_ref=f"{product}#{n}.{again}", state={"conversation_window": window},
                    status="completed", stop_reason="final_response", prompt_version="v",
                    prompt_sha256="a" * 64, write_mode="live",
                    created_at=T0 + timedelta(minutes=10 * n + again),
                )  # fmt: skip
                s.add(run)
                s.flush()
                s.add(
                    ToolExecution(
                        shop_id=shop,
                        approval_id=f"a-{n}-{again}",
                        status="succeeded",
                        tool_name="update_product_listing",
                        payload_json="{}",
                        workflow_run_id=run.id,
                        outcome_json='{"ok": true, "title": "t"}',
                    )  # fmt: skip
                )
                runs.append(run.id)
        s.add(
            ShopDiagnosisReport(
                shop_id=shop,
                end_date=date(2026, 10, 31),
                ranking="60d",
                built_at=T0,
                report={"metrics_source": "orders", "daily_products": {"x": [1] * 5_000}},
            )  # fmt: skip
        )
        s.commit()
    return {"shop": shop, "reviewer": reviewer, "runs": runs, "cards": cards}


def _record(session, seen: list[str]):
    def listener(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(session.bind.sync_engine, "before_cursor_execute", listener)
    return listener


async def test_reviewer_day0_reading_comes_from_a_jsonpath_not_the_state(monkeypatch):
    seeded = _seed()

    async def no_reading(session, shop_id, product_ids):
        return {}

    monkeypatch.setattr("juli_backend.services.agent_runs.listing.current_readings", no_reading)
    monkeypatch.setattr("juli_backend.services.agent_runs.listing_quality.MAX_RUNS", 10)
    monkeypatch.setattr("juli_backend.services.agent_runs.listing.MAX_RUNS", 10)
    listing_quality.reset_cache()
    seen: list[str] = []
    async with juli_app_async_sessionmaker() as maker, maker() as session:
        listener = _record(session, seen)
        async with with_shop_scope(session, seeded["shop"]):
            items = await list_runs(
                session, seeded["shop"], limit=100, viewer=RunViewer(seeded["reviewer"], None)
            )
        event.remove(session.bind.sync_engine, "before_cursor_execute", listener)
    by_id = {item.id: item for item in items}
    assert set(by_id) == set(seeded["runs"])
    for n, window in enumerate(WINDOWS):
        expected = day0_reading({"conversation_window": window})
        for run_id in seeded["runs"][2 * n : 2 * n + 2]:
            quality = by_id[run_id].listing_quality
            assert quality is not None
            assert quality.before == expected, (n, quality.before, expected)
    assert by_id[seeded["runs"][0]].listing_quality.before.count == 1
    runs_sql = [sql for sql in seen if "FROM workflow_runs" in sql]
    assert runs_sql and all("jsonb_path_query_array" in sql for sql in runs_sql[:1]), runs_sql
    for sql in runs_sql:
        bare = sql.replace("jsonb_path_query_array(workflow_runs.state", "")
        assert "workflow_runs.state" not in bare, sql


async def test_b12_facts_and_card_contexts_read_columns_not_blobs():
    seeded = _seed()
    seen: list[str] = []
    async with juli_app_async_sessionmaker() as maker, maker() as session:
        listener = _record(session, seen)
        async with with_shop_scope(session, seeded["shop"]):
            facts = await ShopDiagnosisReportsRepo(session).latest_source(seeded["shop"], "60d")
            cards = [await session.get(ActionCard, card_id) for card_id in seeded["cards"]]
            seen.clear()
            contexts = await load_card_contexts(session, seeded["shop"], cards)
        event.remove(session.bind.sync_engine, "before_cursor_execute", listener)
    assert facts == (date(2026, 10, 31), "orders")
    for n, card_id in enumerate(seeded["cards"]):
        assert contexts[card_id].latest_run.id == seeded["runs"][2 * n + 1]
    assert not any("workflow_runs.state" in sql for sql in seen), seen
