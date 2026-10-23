"""P66 (C7): on the sandbox pin a reviewer's run list (Đang thực hiện, Hàng chờ, Đo lường)
holds only the runs the reviewer started and the shop's runs since the reviewer account was
created -- never the team's older verification runs on the same shop. Sellers unchanged."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

from juli_backend.models.models import ActionCard, ActionCardApproval, WorkflowRun
from juli_backend.repositories import utc_now_naive
from tests.support.api import build_app, client_for
from tests.unit import test_reviewer_sandbox_create_product as p64
from tests.unit.test_reviewer_sandbox_create_product import _headers

reviewer_env = p64.reviewer_env
world = p64.world


async def _run(session, ids, *, approved_by, created_at, name: str, revision: int) -> uuid.UUID:
    card = ActionCard(
        id=uuid.uuid4(), shop_id=ids["sandbox"], workflow_key="optimize_product_2",
        subject_type="product", subject_id=str(ids["product"]), revision=revision, priority=0,
        severity="medium", title=name, description="", recommendation_payload=json.dumps({}),
        status="approved",
    )  # fmt: skip
    session.add(card)
    await session.flush()
    session.add(
        ActionCardApproval(
            action_card_id=card.id,
            approved_by_user_id=approved_by,
            approved_at=created_at,
            card_snapshot={},
        )
    )
    run = WorkflowRun(
        shop_id=ids["sandbox"], product_id=ids["product"], action_card_id=card.id,
        workflow_key="optimize_product_2", subject_type="product",
        subject_ref=f"{ids['product']}#{revision}", state={}, status="completed",
        stop_reason="final_response", prompt_version="v", prompt_sha256="a" * 64,
        created_at=created_at,
    )  # fmt: skip
    session.add(run)
    await session.flush()
    return run.id


async def test_the_sandbox_reviewer_sees_only_its_runs_and_newer_ones(session, world):
    ids, reviewer_id = world
    old_team = await _run(
        session, ids, approved_by=ids["owner"], created_at=utc_now_naive() - timedelta(days=60),
        name="W5 verification", revision=11,
    )  # fmt: skip
    newer_team = await _run(
        session, ids, approved_by=ids["owner"], created_at=utc_now_naive() + timedelta(minutes=5),
        name="after the account", revision=12,
    )  # fmt: skip
    mine = await _run(
        session, ids, approved_by=reviewer_id, created_at=utc_now_naive() - timedelta(days=90),
        name="reviewer's own", revision=13,
    )  # fmt: skip
    await session.commit()

    async with client_for(build_app(session)) as client:
        listed = await client.get("/v1/demo/runs", headers=_headers(reviewer_id, ids["sandbox"]))
        seller = await client.get(
            "/v1/demo/runs",
            headers=_headers(ids["owner"], ids["sandbox"], platform=None, email="o@gmail.com"),
        )
    assert listed.status_code == 200, listed.text
    by_id = {item["id"]: item for item in listed.json()["data"]}
    assert set(by_id) == {str(newer_team), str(mine)}
    assert str(old_team) not in by_id
    # (c) Hoàn tác only on the reviewer's own run.
    assert by_id[str(mine)]["started_by_viewer"] is True
    assert by_id[str(newer_team)]["started_by_viewer"] is False
    # A seller sees every run, with no viewer flag.
    seller_items = seller.json()["data"]
    assert {item["id"] for item in seller_items} == {str(old_team), str(newer_team), str(mine)}
    assert all(item["started_by_viewer"] is None for item in seller_items)


async def test_a_create_promotion_run_carries_its_flow(session, world):
    ids, reviewer_id = world
    card_id = uuid.uuid4()
    session.add(
        ActionCard(
            id=card_id,
            shop_id=ids["sandbox"],
            workflow_key="create_promotion",
            subject_type="product",
            subject_id=str(ids["product"]),
            revision=11,
            priority=0,
            severity="medium",
            title="x",
            description="",
            recommendation_payload="{}",
            status="approved",
        )  # fmt: skip
    )
    await session.flush()
    session.add(
        ActionCardApproval(
            action_card_id=card_id,
            approved_by_user_id=reviewer_id,
            approved_at=utc_now_naive(),
            card_snapshot={},
        )  # fmt: skip
    )
    session.add(
        WorkflowRun(
            shop_id=ids["sandbox"],
            product_id=ids["product"],
            action_card_id=card_id,
            workflow_key="create_promotion",
            subject_type="product",
            subject_ref=str(ids["product"]),
            state={},
            status="running",
            prompt_version="v",
            prompt_sha256="a" * 64,
        )  # fmt: skip
    )
    await session.commit()
    async with client_for(build_app(session)) as client:
        listed = await client.get("/v1/demo/runs", headers=_headers(reviewer_id, ids["sandbox"]))
    [item] = listed.json()["data"]
    assert item["run_flow"] == "promotion"
