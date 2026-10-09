"""P10 integration: the Quyết định UI wired to the merged P10-A / P10-B backend.

Two halves:

- **Routes** -- "Không thực hiện" at the photo / Seller Center wait ends the run
  (the RunPhoto / RunManual artboards offer it before any consent exists), and
  runs carry ``decision_id`` so the UI joins a run to its card by id.
- **Python <-> TypeScript** -- the demo app's P10 wire types
  (``apps/demo/src/lib/quyet-dinh/p10-types.ts``, ``reasons.ts``) and the runs
  list mirror (``packages/contracts/src/agent-runs.ts``) name exactly the fields
  and codes the FastAPI models send. Interfaces are erased at runtime, so the TS
  side is read as source text (field names only; types are checked by tsc).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from juli_backend.api.routes.agent_runs import WorkflowRunListItem
from juli_backend.api.routes.demo_decisions import DemoDecisionCard, DemoDecisionCardKpi
from juli_backend.api.routes.demo_execution import DecisionRejectResponse
from juli_backend.api.routes.demo_run_changes import RunDeclineResponse
from juli_backend.api.routes.demo_run_flows import (
    InstructionsResponse,
    PhotoCheckItem,
    RunDetail,
)
from juli_backend.models.decision_reasons import (
    ACTION_DECLINE,
    ACTION_REJECT,
    ACTION_REVERT,
    DecisionReason,
)
from juli_backend.models.models import ActionCard, WorkflowRunEvent
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.services import lever_flows
from juli_backend.services.decision_reasons.reasons import REASON_LABELS_VI
from juli_backend.services.lever_flows.flows import AWAITING_VALUES
from tests.support.lever_flows import api_client, seed_run, seed_shop

ROOT = Path(__file__).resolve().parents[2]
P10_TYPES = ROOT / "apps/demo/src/lib/quyet-dinh/p10-types.ts"
REASONS_TS = ROOT / "apps/demo/src/lib/quyet-dinh/reasons.ts"
AGENT_RUNS_TS = ROOT / "packages/contracts/src/agent-runs.ts"


# --- "Không thực hiện" while Juli waits for the seller ------------------------------------


async def _waiting(session, label: str, *, lever: str, kind: str, awaiting: str):
    shop, product = await seed_shop(session, label)
    run = await seed_run(
        session,
        shop,
        product,
        lever=lever,
        flow_kind=kind,
        status="waiting_external",
        external_wait_reason=awaiting,
        waiting_since=datetime(2026, 10, 9, 3, 0, tzinfo=UTC),
    )
    await session.commit()
    return shop, product, run


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lever", "kind", "awaiting", "reason_code"),
    [
        ("product_discount", "promotion", "seller_action", "changed_mind"),
        ("cover_image", "photo", "photo", "other"),
    ],
)
async def test_decline_at_the_seller_wait_ends_the_run_and_cools_the_lever(
    engine, session, lever, kind, awaiting, reason_code
):
    shop, product, run = await _waiting(session, "a", lever=lever, kind=kind, awaiting=awaiting)
    async with api_client(engine, shop) as client:
        resp = await client.post(
            f"/v1/demo/runs/{run.id}/decline", json={"reason_code": reason_code}
        )
        again = await client.post(
            f"/v1/demo/runs/{run.id}/decline", json={"reason_code": reason_code}
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "declined" and resp.json()["cooldown_until"]
    row = await session.get(WorkflowRunRow, run.id, populate_existing=True)
    assert (row.status, row.stop_reason) == ("cancelled", "cancelled_by_seller")
    assert row.completed_at is not None
    assert lever_flows.awaiting_of(row) is None
    events = (
        (
            await session.execute(
                select(WorkflowRunEvent).where(WorkflowRunEvent.workflow_run_id == run.id)
            )
        )
        .scalars()
        .all()
    )
    assert [(e.event_type, e.payload) for e in events] == [
        ("workflow.failed", {"status": "cancelled", "stop_reason": "cancelled_by_seller"})
    ]
    (reason,) = (await session.execute(select(DecisionReason))).scalars().all()
    assert (reason.action, reason.reason_code, reason.lever_code) == (
        "decline",
        reason_code,
        lever,
    )
    assert (reason.workflow_run_id, reason.product_id) == (run.id, product.id)
    card = await session.get(ActionCard, row.action_card_id, populate_existing=True)
    assert card.status == "dismissed"
    # Nothing waits any more: the second "Không thực hiện" is refused, not re-recorded.
    assert again.status_code in (404, 409)
    assert len((await session.execute(select(DecisionReason))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_decline_at_the_seller_wait_is_tenant_scoped(engine, session):
    _shop_a, _product, run_a = await _waiting(
        session, "a", lever="flash_sale", kind="promotion", awaiting="seller_action"
    )
    shop_b, _ = await seed_shop(session, "b")
    await session.commit()
    async with api_client(engine, shop_b) as client:
        resp = await client.post(
            f"/v1/demo/runs/{run_a.id}/decline", json={"reason_code": "changed_mind"}
        )
    assert resp.status_code == 404
    fresh = await session.get(WorkflowRunRow, run_a.id, populate_existing=True)
    assert fresh.status == "waiting_external"
    assert (await session.execute(select(DecisionReason))).scalars().all() == []


@pytest.mark.asyncio
async def test_end_wait_refuses_a_run_that_already_resumed(session):
    shop, product = await seed_shop(session)
    run = await seed_run(
        session,
        shop,
        product,
        lever="cover_image",
        flow_kind="photo",
        status="running",
        external_wait_reason="photo",
    )
    with pytest.raises(lever_flows.NotAwaitingSeller):
        await lever_flows.end_wait_by_seller(session, run)
    assert run.status == "running"


# --- runs carry their card -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_runs_list_and_detail_carry_the_decision_id(engine, session):
    shop, _product, run = await _waiting(
        session, "a", lever="cover_image", kind="photo", awaiting="photo"
    )
    async with api_client(engine, shop) as client:
        listed = await client.get("/v1/demo/runs")
        detail = await client.get(f"/v1/demo/runs/{run.id}")

    (item,) = listed.json()["data"]
    assert item["decision_id"] == str(run.action_card_id)
    assert item["awaiting"] == "photo"
    data = detail.json()["data"]
    assert data["decision_id"] == str(run.action_card_id)
    assert data["lever"] == {"code": "cover_image", "kind": "photo"}


# --- Python <-> TypeScript ------------------------------------------------------------------


def _ts_fields(path: Path, name: str) -> set[str]:
    """Top-level property names of ``export interface <name> { ... }`` in ``path``."""
    source = path.read_text(encoding="utf-8")
    match = re.search(rf"export interface {name}\b[^{{]*\{{", source)
    assert match, f"interface {name} not found in {path.name}"
    depth, index, fields = 1, match.end(), set()
    line_start = True
    while depth and index < len(source):
        char = source[index]
        if char in "{(":
            depth += 1
        elif char in "})":
            depth -= 1
        elif depth == 1 and line_start:
            prop = re.match(r"\s*(?:readonly\s+)?([a-z_][a-z0-9_]*)\??\s*:", source[index:])
            if prop:
                fields.add(prop.group(1))
        line_start = char == "\n" or (line_start and char.isspace())
        index += 1
    return fields


def _ts_union(path: Path, name: str) -> set[str]:
    source = path.read_text(encoding="utf-8")
    match = re.search(rf"export type {name}\s*=([^;]+);", source)
    assert match, f"type {name} not found in {path.name}"
    return set(re.findall(r'"([a-z_]+)"', match.group(1)))


def _ts_reason_codes(const: str) -> list[str]:
    source = REASONS_TS.read_text(encoding="utf-8")
    match = re.search(rf"export const {const}[^=]*=\s*\[(.*?)\];", source, re.S)
    assert match, const
    return re.findall(r'code:\s*"([a-z_]+)"', match.group(1))


@pytest.mark.parametrize(
    ("const", "action"),
    [
        ("REJECT_REASONS", ACTION_REJECT),
        ("DECLINE_REASONS", ACTION_DECLINE),
        ("REVERT_REASONS", ACTION_REVERT),
    ],
)
def test_reason_codes_match_the_backend_in_order(const, action):
    assert _ts_reason_codes(const) == list(REASON_LABELS_VI[action])


def test_card_payload_fields_match():
    assert _ts_fields(P10_TYPES, "RecommendationCardPayload") == set(DemoDecisionCard.model_fields)
    assert _ts_fields(P10_TYPES, "CardKpi") == set(DemoDecisionCardKpi.model_fields)


def test_photo_check_and_instructions_fields_match():
    assert _ts_fields(P10_TYPES, "PhotoCheck") == set(PhotoCheckItem.model_fields)
    assert _ts_fields(P10_TYPES, "SellerInstructions") == set(InstructionsResponse.model_fields)


def test_run_detail_fields_the_ui_reads_are_sent():
    assert _ts_fields(P10_TYPES, "RunDetail") <= set(RunDetail.model_fields)


def test_runs_list_mirror_matches():
    assert _ts_fields(AGENT_RUNS_TS, "WorkflowRunListItem") == set(WorkflowRunListItem.model_fields)


def test_awaiting_values_match():
    assert _ts_union(P10_TYPES, "RunAwaiting") == set(AWAITING_VALUES)


def test_reason_responses_carry_status_and_cooldown():
    expected = {"status", "cooldown_until"}
    assert set(DecisionRejectResponse.model_fields) == expected
    assert set(RunDeclineResponse.model_fields) == expected
    source = (ROOT / "apps/demo/src/lib/quyet-dinh/api-client.ts").read_text(encoding="utf-8")
    assert source.count("{ status: string; cooldown_until: string | null }") == 2


def test_helpers_read_nested_interfaces_only_at_top_level():
    # Guards the parser itself: RunDetail.photo's nested fields are not top-level.
    fields = _ts_fields(P10_TYPES, "RunDetail")
    assert "photo" in fields and "before_url" not in fields
