"""P67 (D75 Q2): on the sandbox pin each listed run carries what it wrote on TikTok.

Đo lường lists every run of the reviewer whose TikTok write TikTok confirmed (ledger
``succeeded``): create product, create discount, listing edit -- with the TikTok id and
the confirmation time. A refused write (``ok: false``) is not one. Sellers unchanged:
``confirmed_write`` is null for them.
"""

from __future__ import annotations

import json
import uuid

from juli_backend.models.models import ActionCard, ActionCardApproval, ToolExecution, WorkflowRun
from juli_backend.repositories import utc_now_naive
from tests.support.api import build_app, client_for
from tests.unit import test_reviewer_sandbox_create_product as p64
from tests.unit.test_reviewer_sandbox_create_product import _headers

reviewer_env = p64.reviewer_env
world = p64.world


async def _run_with_write(
    session, ids, reviewer_id, *, workflow: str, tool: str, outcome: dict, n: int
) -> uuid.UUID:
    card = ActionCard(
        id=uuid.uuid4(), shop_id=ids["sandbox"], workflow_key=workflow, subject_type="product",
        subject_id=str(ids["product"]), revision=20 + n, priority=0, severity="medium",
        title="x", description="", recommendation_payload="{}", status="approved",
    )  # fmt: skip
    session.add(card)
    await session.flush()
    session.add(
        ActionCardApproval(
            action_card_id=card.id,
            approved_by_user_id=reviewer_id,
            approved_at=utc_now_naive(),
            card_snapshot={},
        )  # fmt: skip
    )
    run = WorkflowRun(
        shop_id=ids["sandbox"], product_id=ids["product"], action_card_id=card.id,
        workflow_key=workflow, subject_type="product", subject_ref=f"{ids['product']}#{n}",
        state={}, status="completed", stop_reason="final_response", prompt_version="v",
        prompt_sha256="a" * 64,
    )  # fmt: skip
    session.add(run)
    await session.flush()
    session.add(
        ToolExecution(
            shop_id=ids["sandbox"],
            approval_id=f"a-{n}",
            tool_name=tool,
            payload_json="{}",
            status="succeeded",
            workflow_run_id=run.id,
            tool_call_id=f"c-{n}",
            operation=tool,
            outcome_json=json.dumps(outcome),
        )  # fmt: skip
    )
    await session.flush()
    return run.id


async def test_each_reviewer_run_carries_its_confirmed_tiktok_write(session, world):
    ids, reviewer_id = world
    create = await _run_with_write(
        session, ids, reviewer_id, workflow="create_product", tool="create_product",
        outcome={"ok": True, "tiktok_product_id": "1738157559581542019",
                 "confirmed_at": "2026-10-23T05:40:00Z"},
        n=1,
    )  # fmt: skip
    promo = await _run_with_write(
        session, ids, reviewer_id, workflow="create_promotion", tool="create_product_discount",
        outcome={"ok": True, "activity_id": "7699734374178817800", "discount_pct": 12,
                 "confirmed_at": "2026-10-23T05:43:00Z"},
        n=2,
    )  # fmt: skip
    edit = await _run_with_write(
        session, ids, reviewer_id, workflow="optimize_product_2", tool="update_product_listing",
        outcome={"title": "Tiêu đề mới", "description": None, "image_attached": False},
        n=3,
    )  # fmt: skip
    refused = await _run_with_write(
        session, ids, reviewer_id, workflow="create_product", tool="create_product",
        outcome={"ok": False, "error_code": "tiktok_refused"}, n=4,
    )  # fmt: skip
    await session.commit()

    async with client_for(build_app(session)) as client:
        listed = await client.get("/v1/demo/runs", headers=_headers(reviewer_id, ids["sandbox"]))
        seller = await client.get(
            "/v1/demo/runs",
            headers=_headers(ids["owner"], ids["sandbox"], platform=None, email="o@gmail.com"),
        )
    assert listed.status_code == 200, listed.text
    by_id = {item["id"]: item["confirmed_write"] for item in listed.json()["data"]}
    assert by_id[str(create)] == {
        "kind": "create_product", "tiktok_id": "1738157559581542019",
        "confirmed_at": "2026-10-23T05:40:00Z", "discount_pct": None, "fields": [],
    }  # fmt: skip
    assert by_id[str(promo)]["kind"] == "create_promotion"
    assert by_id[str(promo)]["tiktok_id"] == "7699734374178817800"
    assert by_id[str(promo)]["discount_pct"] == 12
    assert by_id[str(edit)]["kind"] == "listing_edit"
    assert by_id[str(edit)]["fields"] == ["title"]
    assert by_id[str(edit)]["tiktok_id"] and by_id[str(edit)]["confirmed_at"]
    assert by_id[str(refused)] is None, "a write TikTok refused is not a confirmed write"
    # Sellers unchanged: no confirmed_write on their list.
    assert all(item["confirmed_write"] is None for item in seller.json()["data"])
