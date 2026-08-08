"""Public Demo Decisions read API (#718, B-6) — unauthenticated GET list/detail.

Emission-gated (`ActionCard.surfaced_at`-gated), server-bound reference shop
(same `DEMO_REFERENCE_SHOP_ID` pattern as `GET /v1/demo/analytics` #531 and
`POST /v1/demo/decisions/{id}/approve` #717 B-5). No visitor-supplied
`shop_id` anywhere — no query param, no header, no path segment.

AC1 → contract: only the reference shop's emission-gated active set is
      returned; any other shop_id is rejected or ignored, never a tenant
      pivot.
AC2 → response carries `computed_at` / `surfaced_at` (promotion) freshness
      metadata per card.
AC3 → security: no raw internal identifiers (`workflow_key`, `tool_name`,
      internal uuids) leak into the response body, adversarially proven —
      not just absent from the fields this module chose to map, but absent
      from suppressed/foreign card content that must never be included at
      all.
AC4 → integration: compute -> scoring (persist_scoring_result) -> emission
      filter (apply_emission_budget) -> this GET reflects the gated list
      end-to-end, using the real #715/#716 functions unedited.
AC5 → list ordering/count reflect the emission-gated active set only —
      suppressed candidates never appear as active.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.models.models import ActionCard, Shop, User
from juli_backend.services.action_cards.emission_budget import apply_emission_budget
from juli_backend.services.action_cards.persist import persist_scoring_result
from juli_backend.services.aggregates.types import (
    FeatureAggregateSnapshot,
    HealthDataSource,
    ShopProfile,
)
from juli_backend.services.scoring.types import (
    DailyScoringResult,
    ScoringSignals,
    WorkflowExpectedImpact,
    WorkflowRecommendation,
    WorkflowRecommendations,
)

COMPUTED_AT = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fixtures — same shape as test_api_demo_analytics.py / test_api_demo_execution.py
# ---------------------------------------------------------------------------


@pytest.fixture
def demo_reference_shop_id() -> uuid.UUID:
    return uuid.UUID("c3d4e5f6-a7b8-9012-cdef-123456789012")


@pytest.fixture
def demo_env(monkeypatch, demo_reference_shop_id):
    monkeypatch.setenv("DEMO_REFERENCE_SHOP_ID", str(demo_reference_shop_id))


@pytest_asyncio.fixture
async def reference_shop(session, user_id, demo_reference_shop_id):
    user = User(id=user_id, phone="+849180000718")
    shop = Shop(
        id=demo_reference_shop_id,
        user_id=user_id,
        shop_name="Reference Shop 718",
        tiktok_shop_id="tiktok_ref_718",
    )
    session.add_all([user, shop])
    await session.flush()
    return shop


@pytest_asyncio.fixture
async def other_shop(session):
    other_user = User(id=uuid.uuid4(), phone="+849180099999")
    shop = Shop(
        id=uuid.uuid4(),
        user_id=other_user.id,
        shop_name="Some Other Tenant Shop",
        tiktok_shop_id="tiktok_other_718",
    )
    session.add_all([other_user, shop])
    await session.flush()
    return shop


@pytest_asyncio.fixture
async def demo_client(engine, demo_env):
    from juli_backend.api.app import create_app
    from juli_backend.database import get_session

    factory = async_sessionmaker(engine, expire_on_commit=False)
    application = create_app()

    async def _test_session():
        async with factory() as sess:
            yield sess

    application.dependency_overrides[get_session] = _test_session
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        yield client
    application.dependency_overrides.clear()


def _card(
    shop_id: uuid.UUID,
    *,
    workflow_key: str,
    priority: int = 1,
    status: str = "active",
    surfaced_at: datetime | None = None,
    suppressed_reason: str | None = None,
    computed_at: datetime | None = COMPUTED_AT,
    title: str = "Test Decision",
    description: str = "Test description.",
    recommendation_payload: str | None = None,
) -> ActionCard:
    payload = recommendation_payload or json.dumps(
        {
            "workflow_key": workflow_key,
            "workflow_name": title,
            "priority": priority,
            "rationale": "Test rationale",
            "expected_impact": {"metric": "gmv", "value": 1.0, "confidence": "medium"},
            "preconditions_met": True,
            "user_action_required": True,
            "source_kpi_ids": [],
            "computed_at": (computed_at or COMPUTED_AT).isoformat(),
        }
    )
    return ActionCard(
        id=uuid.uuid4(),
        shop_id=shop_id,
        workflow_key=workflow_key,
        priority=priority,
        severity="warning",
        title=title,
        description=description,
        recommendation_payload=payload,
        status=status,
        surfaced_at=surfaced_at,
        suppressed_reason=suppressed_reason,
        computed_at=computed_at,
    )


def _scoring_result(
    shop_id: uuid.UUID,
    *,
    workflows: list[tuple[str, str, int]],
    computed_at: datetime = COMPUTED_AT,
) -> DailyScoringResult:
    return DailyScoringResult(
        aggregates=FeatureAggregateSnapshot(
            shop_id=shop_id,
            shop_profile=ShopProfile.NEW_SHOP,
            health_data_source=HealthDataSource.PROXY,
            sps_score=None,
            vp_score=None,
            ahr_score=None,
            order_count=10,
            product_count=5,
            return_count=1,
            total_order_value=Decimal("100000"),
            total_product_revenue=Decimal("100000"),
            total_units_sold=10,
            return_rate_proxy=0.1,
            data_sources=["orders", "returns"],
        ),
        signals=ScoringSignals(
            shop_id=shop_id,
            computed_at=computed_at,
            health_data_source=HealthDataSource.PROXY,
            kpis={},
        ),
        recommendations=WorkflowRecommendations(
            shop_profile=ShopProfile.NEW_SHOP,
            recommended_workflows=[
                WorkflowRecommendation(
                    workflow_key=key,
                    workflow_name=name,
                    priority=priority,
                    rationale="Test rationale",
                    expected_impact=WorkflowExpectedImpact(
                        metric="gmv", value=1.0, confidence="medium"
                    ),
                    preconditions_met=True,
                    user_action_required=True,
                    source_kpi_ids=(),
                )
                for key, name, priority in workflows
            ],
        ),
        reasoning_summaries=(),
    )


# ---------------------------------------------------------------------------
# AC1 + AC5 — contract: only the reference shop's emission-gated active set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_returns_only_surfaced_active_cards_for_reference_shop(
    demo_client, session, reference_shop
):
    surfaced_a = _card(
        reference_shop.id,
        workflow_key="wf_a",
        priority=2,
        surfaced_at=COMPUTED_AT,
    )
    surfaced_b = _card(
        reference_shop.id,
        workflow_key="wf_b",
        priority=1,
        surfaced_at=COMPUTED_AT,
    )
    suppressed = _card(
        reference_shop.id,
        workflow_key="wf_suppressed",
        priority=3,
        surfaced_at=None,
        suppressed_reason="active_cap",
    )
    # A card that surfaced in the past but has since been approved — no
    # longer part of the actionable candidate set even though a stale
    # surfaced_at column value may remain (emission_budget only evaluates
    # status == "active" rows; approve never clears surfaced_at).
    approved_stale = _card(
        reference_shop.id,
        workflow_key="wf_approved",
        priority=1,
        status="approved",
        surfaced_at=COMPUTED_AT,
    )
    session.add_all([surfaced_a, surfaced_b, suppressed, approved_stale])
    await session.flush()

    resp = await demo_client.get("/v1/demo/decisions")

    assert resp.status_code == 200
    body = resp.json()
    ids = [item["id"] for item in body["data"]]
    assert ids == [str(surfaced_b.id), str(surfaced_a.id)]  # priority ascending
    assert str(suppressed.id) not in ids
    assert str(approved_stale.id) not in ids
    assert len(body["data"]) == 2


@pytest.mark.asyncio
async def test_list_excludes_another_shops_surfaced_cards(
    demo_client, session, reference_shop, other_shop
):
    own_card = _card(reference_shop.id, workflow_key="wf_own", priority=1, surfaced_at=COMPUTED_AT)
    other_card = _card(other_shop.id, workflow_key="wf_other", priority=1, surfaced_at=COMPUTED_AT)
    session.add_all([own_card, other_card])
    await session.flush()

    resp = await demo_client.get("/v1/demo/decisions")

    assert resp.status_code == 200
    ids = [item["id"] for item in resp.json()["data"]]
    assert ids == [str(own_card.id)]
    assert str(other_card.id) not in ids


@pytest.mark.asyncio
async def test_list_rejects_visitor_supplied_shop_id_query_param(
    demo_client, session, reference_shop, other_shop
):
    resp = await demo_client.get("/v1/demo/decisions", params={"shop_id": str(other_shop.id)})
    assert resp.status_code == 400
    assert "shop_id" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_list_ignores_visitor_supplied_shop_id_header_tenant_pivot_attempt(
    demo_client, session, reference_shop, other_shop
):
    """No X-Shop-Id header — or any header — can redirect this endpoint off
    the server-bound reference shop (PRD security story 21)."""
    own_card = _card(reference_shop.id, workflow_key="wf_own", priority=1, surfaced_at=COMPUTED_AT)
    other_card = _card(
        other_shop.id, workflow_key="wf_other_secret", priority=1, surfaced_at=COMPUTED_AT
    )
    session.add_all([own_card, other_card])
    await session.flush()

    resp = await demo_client.get(
        "/v1/demo/decisions",
        headers={"X-Shop-Id": str(other_shop.id)},
    )

    assert resp.status_code == 200
    ids = [item["id"] for item in resp.json()["data"]]
    assert ids == [str(own_card.id)]
    assert "wf_other_secret" not in resp.text


@pytest.mark.asyncio
async def test_detail_rejects_visitor_supplied_shop_id_query_param(
    demo_client, session, reference_shop, other_shop
):
    own_card = _card(reference_shop.id, workflow_key="wf_own", priority=1, surfaced_at=COMPUTED_AT)
    session.add(own_card)
    await session.flush()

    resp = await demo_client.get(
        f"/v1/demo/decisions/{own_card.id}",
        params={"shop_id": str(other_shop.id)},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_detail_returns_another_shops_surfaced_card_as_404_tenant_pivot_attempt(
    demo_client, session, reference_shop, other_shop
):
    """The core tenant-pivot attempt: a visitor who has (or guesses) another
    shop's action_card_id must not be able to read it through the
    reference-shop-bound endpoint."""
    other_card = _card(
        other_shop.id,
        workflow_key="wf_other_secret",
        priority=1,
        surfaced_at=COMPUTED_AT,
        title="Other tenant's private decision title",
    )
    session.add(other_card)
    await session.flush()

    resp = await demo_client.get(f"/v1/demo/decisions/{other_card.id}")

    assert resp.status_code == 404
    assert "wf_other_secret" not in resp.text
    assert "Other tenant's private decision title" not in resp.text


# ---------------------------------------------------------------------------
# Detail 404 semantics — "safe default": existence is never leaked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_returns_404_for_suppressed_card_not_leaked_as_active(
    demo_client, session, reference_shop
):
    suppressed = _card(
        reference_shop.id,
        workflow_key="wf_suppressed",
        priority=1,
        surfaced_at=None,
        suppressed_reason="cooldown",
    )
    session.add(suppressed)
    await session.flush()

    resp = await demo_client.get(f"/v1/demo/decisions/{suppressed.id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_detail_returns_404_for_nonexistent_card(demo_client, reference_shop):
    resp = await demo_client.get(f"/v1/demo/decisions/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_detail_404_response_shape_identical_for_suppressed_and_nonexistent(
    demo_client, session, reference_shop
):
    """Suppressed-vs-nonexistent must be indistinguishable from the outside —
    otherwise the 404 itself becomes an existence oracle."""
    suppressed = _card(
        reference_shop.id,
        workflow_key="wf_suppressed",
        priority=1,
        surfaced_at=None,
        suppressed_reason="cooldown",
    )
    session.add(suppressed)
    # commit (not flush): this test issues two sequential HTTP requests
    # against a StaticPool sqlite engine, and each request runs in its own
    # session/connection-transaction. A flush()-only row is only reliably
    # visible to the FIRST such request — the first request's session
    # closing without a commit rolls back the shared connection and erases
    # an uncommitted row for every later request. commit() makes the row
    # durably visible to both requests, so this test actually exercises the
    # byte-identical-404 comparison it claims to (#718 Review finding).
    await session.commit()

    resp_suppressed = await demo_client.get(f"/v1/demo/decisions/{suppressed.id}")
    resp_missing = await demo_client.get(f"/v1/demo/decisions/{uuid.uuid4()}")

    assert resp_suppressed.status_code == resp_missing.status_code == 404
    assert resp_suppressed.json() == resp_missing.json()


@pytest.mark.asyncio
async def test_detail_returns_surfaced_card_with_freshness_metadata(
    demo_client, session, reference_shop
):
    surfaced_at = datetime(2026, 8, 8, 9, 30, tzinfo=UTC)
    card = _card(
        reference_shop.id,
        workflow_key="wf_a",
        priority=1,
        surfaced_at=surfaced_at,
        computed_at=COMPUTED_AT,
    )
    session.add(card)
    await session.flush()

    resp = await demo_client.get(f"/v1/demo/decisions/{card.id}")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] == str(card.id)
    # sqlite (test engine) drops tzinfo on round-trip; compare the naive
    # wall-clock value rather than requiring byte-identical isoformat().
    assert data["computed_at"].startswith(COMPUTED_AT.strftime("%Y-%m-%dT%H:%M:%S"))
    assert data["surfaced_at"].startswith(surfaced_at.strftime("%Y-%m-%dT%H:%M:%S"))


# ---------------------------------------------------------------------------
# AC3 — security: no internal identifiers / workflow_key / tool_name leak,
# proven adversarially against both included and excluded card content.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_internal_identifiers_or_leaked_content_in_response_body(
    demo_client, session, reference_shop, other_shop
):
    internal_uuid_marker = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    financial_marker = "987654321.42"

    # Card A: legitimately surfaced for the reference shop — its own
    # workflow_key must not leak even though the card itself IS included.
    included = _card(
        reference_shop.id,
        workflow_key="internal_secret_workflow_734",
        priority=1,
        surfaced_at=COMPUTED_AT,
        recommendation_payload=json.dumps(
            {
                "workflow_key": "internal_secret_workflow_734",
                "workflow_name": "Prevent likely returns",
                "priority": 1,
                "rationale": "Return rate is elevated.",
                "expected_impact": {"metric": "return_rate", "value": 0.02, "confidence": "medium"},
                "preconditions_met": True,
                "user_action_required": True,
                "source_kpi_ids": ["return_request_rate"],
                "computed_at": COMPUTED_AT.isoformat(),
                "tool_name": "tiktok_create_activity_secret",
                "internal_uuid": internal_uuid_marker,
                "raw_balance_vnd": financial_marker,
            }
        ),
    )

    # Card B: suppressed for the reference shop — must never appear at all.
    suppressed_poisoned = _card(
        reference_shop.id,
        workflow_key="SECRET_WORKFLOW_KEY_B",
        priority=1,
        surfaced_at=None,
        suppressed_reason="active_cap",
        title="POISON_TITLE_B tool_name=evil_tool",
        description=f"POISON_DESC_B uuid={internal_uuid_marker} amount={financial_marker}",
        recommendation_payload=json.dumps(
            {
                "workflow_key": "SECRET_WORKFLOW_KEY_B",
                "tool_name": "evil_tool_b",
                "internal_uuid": internal_uuid_marker,
                "raw_balance_vnd": financial_marker,
            }
        ),
    )

    # Card C: surfaced for a DIFFERENT (non-reference) shop — tenant pivot
    # content must never appear either.
    other_shop_poisoned = _card(
        other_shop.id,
        workflow_key="SECRET_WORKFLOW_KEY_C",
        priority=1,
        surfaced_at=COMPUTED_AT,
        title="POISON_TITLE_C tool_name=evil_tool_c",
        description=f"POISON_DESC_C uuid={internal_uuid_marker}",
        recommendation_payload=json.dumps(
            {
                "workflow_key": "SECRET_WORKFLOW_KEY_C",
                "tool_name": "evil_tool_c",
                "internal_uuid": internal_uuid_marker,
            }
        ),
    )

    session.add_all([included, suppressed_poisoned, other_shop_poisoned])
    # commit (not flush): this test issues three sequential HTTP requests
    # (list, detail_b, detail_c) against a StaticPool sqlite engine. A
    # flush()-only row is only reliably visible to the FIRST request — by
    # the time detail_b/detail_c run, an uncommitted row has already been
    # rolled off the shared connection by the first request's session
    # closing, so those two calls would 404 because the DB is empty, not
    # because masking/tenant-isolation correctly excluded the poisoned
    # cards. commit() makes the fixture rows durably visible to every
    # request so the leak assertions on detail_b/detail_c actually test
    # what they claim (#718 Review finding).
    await session.commit()

    list_resp = await demo_client.get("/v1/demo/decisions")
    assert list_resp.status_code == 200
    list_text = list_resp.text

    detail_b = await demo_client.get(f"/v1/demo/decisions/{suppressed_poisoned.id}")
    detail_c = await demo_client.get(f"/v1/demo/decisions/{other_shop_poisoned.id}")

    for forbidden in (
        "internal_secret_workflow_734",  # card A's own workflow_key
        "SECRET_WORKFLOW_KEY_B",
        "SECRET_WORKFLOW_KEY_C",
        "evil_tool",
        "evil_tool_b",
        "evil_tool_c",
        "tool_name",
        "POISON_TITLE_B",
        "POISON_DESC_B",
        "POISON_TITLE_C",
        "POISON_DESC_C",
        internal_uuid_marker,
        financial_marker,
    ):
        assert forbidden not in list_text, f"{forbidden!r} leaked into list response body"
        assert forbidden not in detail_b.text, f"{forbidden!r} leaked into suppressed detail 404"
        assert forbidden not in detail_c.text, f"{forbidden!r} leaked into foreign detail 404"

    # Sanity: the legitimately-included card's safe content IS present, so
    # this isn't a tautological "empty response" pass.
    assert "Prevent likely returns" in list_text


# ---------------------------------------------------------------------------
# AC4 — integration: compute -> scoring -> persisted card -> emission filter
# -> this GET reflects the gated list end-to-end (real #715/#716 functions).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_integration_compute_scoring_persist_emission_filter_get_reflects_gated_list(
    demo_client, session, reference_shop
):
    workflows = [
        (f"wf_integration_{i}", f"Workflow {i}", i) for i in range(1, 8)
    ]  # 7 candidates, default max_active=5
    result = _scoring_result(reference_shop.id, workflows=workflows)

    cards = await persist_scoring_result(session, reference_shop.id, result)
    assert len(cards) == 7
    outcome = await apply_emission_budget(session, reference_shop.id, now=COMPUTED_AT)
    await session.commit()

    assert len(outcome.surfaced) == 5
    assert len(outcome.suppressed["active_cap"]) == 2

    resp = await demo_client.get("/v1/demo/decisions")

    assert resp.status_code == 200
    body = resp.json()
    returned_ids = {item["id"] for item in body["data"]}
    assert returned_ids == {str(card.id) for card in outcome.surfaced}
    assert len(body["data"]) == 5

    suppressed_ids = {card.id for card in outcome.suppressed["active_cap"]}
    for card_id in suppressed_ids:
        detail = await demo_client.get(f"/v1/demo/decisions/{card_id}")
        assert detail.status_code == 404

    # Priority-ascending ranked order, matching apply_emission_budget's own
    # candidate ordering.
    returned_priorities = [item["priority"] for item in body["data"]]
    assert returned_priorities == sorted(returned_priorities)


# ---------------------------------------------------------------------------
# Last-good degradation — a read failure must not invent an empty "truth"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_failure_surfaces_as_error_not_a_silently_invented_empty_list(
    demo_client, session, reference_shop, monkeypatch
):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "juli_backend.api.routes.demo_decisions.list_surfaced_decisions",
        AsyncMock(side_effect=RuntimeError("db unavailable")),
    )

    resp = await demo_client.get("/v1/demo/decisions")

    assert resp.status_code == 500
    assert resp.json() != {"success": True, "data": [], "error": None}


# ---------------------------------------------------------------------------
# Row-level resilience (#718 Review finding 1) — one malformed persisted row
# must not 500 the whole public feed. Pydantic's typed response schema
# rejecting an unexpected shape is the correct security outcome (no leak);
# the bug is that the resulting ValidationError previously escaped the
# route's try/except entirely and took down every other row with it.
# ---------------------------------------------------------------------------


def _malformed_card(
    shop_id: uuid.UUID, *, priority: int = 5, workflow_key: str = "wf_malformed_shape"
) -> ActionCard:
    """A surfaced card whose persisted payload has the *wrong shape* for the
    typed response schema — a list-of-dicts where `list[str]` is expected
    (`source_kpi_ids`). This is not a JSON-parse failure (handled already by
    `mask_decision_payload`'s `json.JSONDecodeError` catch) — the JSON is
    valid, the allowlist copies the key through untouched, and only
    `DemoDecisionItem`'s pydantic schema rejects the shape."""
    payload = json.dumps(
        {
            "workflow_key": workflow_key,
            "workflow_name": "Malformed row",
            "priority": priority,
            "rationale": "x",
            "preconditions_met": True,
            "user_action_required": True,
            # Wrong shape: list[dict] where list[str] is expected. Mirrors
            # the adversarial probe Review used — a list-of-dicts smuggling
            # an internal tool_name/uuid into a field pydantic will reject.
            "source_kpi_ids": [{"tool_name": "evil_tool", "internal_uuid": "aaaa-bbbb-cccc-dddd"}],
        }
    )
    return ActionCard(
        id=uuid.uuid4(),
        shop_id=shop_id,
        workflow_key=workflow_key,
        priority=priority,
        severity="warning",
        title="Malformed row",
        description="This row has a malformed recommendation payload shape.",
        recommendation_payload=payload,
        status="active",
        surfaced_at=COMPUTED_AT,
        computed_at=COMPUTED_AT,
    )


@pytest.mark.asyncio
async def test_list_drops_malformed_row_and_still_serves_remaining_rows(
    demo_client, session, reference_shop, caplog
):
    """The core regression test: one malformed row must not 500 the whole
    feed, must not appear in the response, and must not leak any of its
    own content — the remaining well-formed rows must still be served."""
    good = _card(reference_shop.id, workflow_key="wf_good", priority=1, surfaced_at=COMPUTED_AT)
    bad = _malformed_card(reference_shop.id, priority=2)
    session.add_all([good, bad])
    await session.commit()

    with caplog.at_level("WARNING", logger="juli_backend.api.routes.demo_decisions"):
        resp = await demo_client.get("/v1/demo/decisions")

    # The list must not become empty and must not 500 just because one row
    # is bad.
    assert resp.status_code == 200
    body = resp.json()
    ids = [item["id"] for item in body["data"]]
    assert ids == [str(good.id)]
    assert str(bad.id) not in ids
    assert len(body["data"]) == 1

    # No leak: none of the malformed row's poisoned content reaches the
    # response body, dropped or not.
    assert "evil_tool" not in resp.text
    assert "aaaa-bbbb-cccc-dddd" not in resp.text

    # The drop must be observable — a structured log entry naming the shop
    # and the card's opaque id, with no PII, no raw payload contents, and
    # no workflow_key (same discipline as B-4's emission_budget logging).
    drop_records = [
        r for r in caplog.records if r.message == "demo_decisions_row_dropped_invalid_shape"
    ]
    assert len(drop_records) == 1
    record = drop_records[0]
    assert getattr(record, "reference_shop_id", None) == str(reference_shop.id)
    assert getattr(record, "action_card_id", None) == str(bad.id)
    log_text = str(record.__dict__)
    assert "evil_tool" not in log_text
    assert "wf_malformed_shape" not in log_text
    assert "aaaa-bbbb-cccc-dddd" not in log_text


@pytest.mark.asyncio
async def test_list_with_all_rows_malformed_returns_empty_list_not_500(
    demo_client, session, reference_shop
):
    """Every row bad is still not a 500 — an empty (but valid) list is the
    correct degraded response, distinct from a query failure."""
    bad_a = _malformed_card(reference_shop.id, priority=1, workflow_key="wf_malformed_a")
    bad_b = _malformed_card(reference_shop.id, priority=2, workflow_key="wf_malformed_b")
    session.add_all([bad_a, bad_b])
    await session.commit()

    resp = await demo_client.get("/v1/demo/decisions")

    assert resp.status_code == 200
    assert resp.json()["data"] == []


@pytest.mark.asyncio
async def test_detail_returns_500_for_malformed_persisted_row_not_a_misleading_404(
    demo_client, session, reference_shop, caplog
):
    """Deliberate detail-endpoint decision (#718 Review finding 1): unlike
    the list, a single detail lookup has no partial result to preserve — the
    row the caller asked for genuinely cannot be represented. Degrading it
    to 404 would misrepresent a data-integrity problem as "this Decision
    doesn't exist", which is a worse signal for on-call debugging than an
    honest, logged 500. So detail intentionally does NOT silently drop; it
    surfaces the same 500 contract as any other unexpected read failure on
    this route."""
    bad = _malformed_card(reference_shop.id)
    session.add(bad)
    await session.commit()

    with caplog.at_level("WARNING", logger="juli_backend.api.routes.demo_decisions"):
        resp = await demo_client.get(f"/v1/demo/decisions/{bad.id}")

    assert resp.status_code == 500
    assert "evil_tool" not in resp.text
    assert "wf_malformed_shape" not in resp.text
