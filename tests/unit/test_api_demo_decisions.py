"""Demo Decisions read API (#1283, AGT-W5A) — authenticated GET list/detail,
scoped to the caller's own shop via `X-Shop-Id`.

**Posture changed here.** These two routes used to be unauthenticated and
resolve a server-bound `DEMO_REFERENCE_SHOP_ID` (#718, B-6) — on the deployed
host that reference shop was a real merchant's production shop, so the
routes served a live seller's recommendations to anyone who could reach the
URL (#1283). They also ignored `X-Shop-Id` entirely while `POST /v1/demo/
decisions/{id}/approve` honoured it via `get_active_shop`, so a card a
caller could *see* was not necessarily a card that caller could *approve*.

Both problems close the same way ADR-075 decision 3 already closed them for
every route that can create/watch/steer/confirm a run: `get_current_user` +
`get_active_shop`, exactly like `POST /v1/demo/decisions/{id}/approve`
(`api/routes/demo_execution.py`) already does. These two read routes were
the deliberate "P-UI's call" exception ADR-075 decision 3 left open; this is
that call. `get_demo_reference_shop_id` /
`DEMO_REFERENCE_SHOP_ID` are no longer involved on this surface at all —
`GET /v1/demo/analytics` (out of scope for #1283) is the remaining caller.

AC1 → contract: only the *authenticated caller's own shop's* emission-gated
      active set is returned, resolved from `X-Shop-Id` — never a
      server-bound reference shop, never another shop's cards, even when
      that other shop is the one with data (the #1283 exposure defect).
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
AC6 (#1283) → 401 without a valid JWT on both routes.
AC7 (#1283) → a caller scoped to a shop with zero cards gets an empty list,
      never another shop's cards — the exposure defect, asserted explicitly.
AC8 (#1283) → a card that appears in the list is approvable by the same
      caller — proven by listing, then approving the listed id, with one
      set of credentials.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.models.models import ActionCard, Product, Shop, User
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

pytestmark = pytest.mark.asyncio


def _naive_utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Fixtures — authenticated caller + owned shop, mirroring
# test_api_demo_execution.py's pattern (the approve route this listing/
# approving split is being closed against).
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def user(session):
    u = User(phone=f"+1555{uuid.uuid4().int % 10_000_000:07d}")
    session.add(u)
    await session.flush()
    return u


@pytest_asyncio.fixture
async def shop(session, user):
    s = Shop(user_id=user.id, shop_name="AGT-1283 HTTP Shop")
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def other_shop(session):
    other_user = User(phone=f"+1555{uuid.uuid4().int % 10_000_000:07d}")
    session.add(other_user)
    await session.flush()
    s = Shop(user_id=other_user.id, shop_name="AGT-1283 Other HTTP Shop")
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def demo_client(engine, user, shop):
    """Authenticated as ``user``, scoped to ``shop`` — mirrors
    `test_api_demo_execution.py`'s `_client_for` pattern: auth is exercised
    via `dependency_overrides` (real JWT parsing / `X-Shop-Id` header
    resolution is `get_active_shop`'s own concern, covered by
    `test_agent_runs_require_auth.py`'s 401-without-JWT tests for this
    surface), so no header needs to be threaded through every call here."""
    from juli_backend.api.app import create_app
    from juli_backend.api.dependencies import get_active_shop
    from juli_backend.core.security import get_current_user
    from juli_backend.database import get_session

    factory = async_sessionmaker(engine, expire_on_commit=False)
    application = create_app()

    async def _test_session():
        async with factory() as sess:
            yield sess

    application.dependency_overrides[get_session] = _test_session
    application.dependency_overrides[get_current_user] = lambda: user
    application.dependency_overrides[get_active_shop] = lambda: shop
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        yield client
    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def app(engine, session):
    """Shared-session app for tests that need to see rows written through
    the same session they assert against (mirrors test_api_demo_execution.py,
    needed for the AC8 list-then-approve test which spans two routers)."""
    from juli_backend.api.app import create_app
    from juli_backend.database import get_session

    application = create_app()

    async def _test_session():
        yield session

    application.dependency_overrides[get_session] = _test_session
    yield application
    application.dependency_overrides.clear()


def _client_for(client_app, caller: User, caller_shop: Shop) -> AsyncClient:
    from juli_backend.api.dependencies import get_active_shop
    from juli_backend.core.security import get_current_user

    client_app.dependency_overrides[get_current_user] = lambda: caller
    client_app.dependency_overrides[get_active_shop] = lambda: caller_shop
    return AsyncClient(transport=ASGITransport(app=client_app), base_url="http://test")


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
# AC1 + AC5 — contract: only the authenticated caller's own emission-gated
# active set, resolved from X-Shop-Id
# ---------------------------------------------------------------------------


async def test_list_returns_only_surfaced_active_cards_for_callers_shop(
    demo_client, session, user, shop
):
    surfaced_a = _card(shop.id, workflow_key="wf_a", priority=2, surfaced_at=COMPUTED_AT)
    surfaced_b = _card(shop.id, workflow_key="wf_b", priority=1, surfaced_at=COMPUTED_AT)
    suppressed = _card(
        shop.id,
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
        shop.id, workflow_key="wf_approved", priority=1, status="approved", surfaced_at=COMPUTED_AT
    )
    session.add_all([surfaced_a, surfaced_b, suppressed, approved_stale])
    await session.commit()

    resp = await demo_client.get("/v1/demo/decisions")

    assert resp.status_code == 200
    body = resp.json()
    ids = [item["id"] for item in body["data"]]
    assert ids == [str(surfaced_b.id), str(surfaced_a.id)]  # priority ascending
    assert str(suppressed.id) not in ids
    assert str(approved_stale.id) not in ids
    assert len(body["data"]) == 2


async def test_list_excludes_another_shops_surfaced_cards(demo_client, session, shop, other_shop):
    own_card = _card(shop.id, workflow_key="wf_own", priority=1, surfaced_at=COMPUTED_AT)
    other_card = _card(other_shop.id, workflow_key="wf_other", priority=1, surfaced_at=COMPUTED_AT)
    session.add_all([own_card, other_card])
    await session.commit()

    resp = await demo_client.get("/v1/demo/decisions")

    assert resp.status_code == 200
    ids = [item["id"] for item in resp.json()["data"]]
    assert ids == [str(own_card.id)]
    assert str(other_card.id) not in ids


async def test_list_for_shop_with_no_cards_returns_empty_not_another_shops_cards(
    demo_client, session, shop, other_shop
):
    """The core #1283 exposure defect, asserted explicitly: a caller scoped
    to a shop with zero action cards must see an empty list — never another
    shop's cards, even when that other shop is the only one with data (the
    exact shape of the Fujiwa-production-shop exposure)."""
    other_card = _card(
        other_shop.id, workflow_key="wf_other_only", priority=1, surfaced_at=COMPUTED_AT
    )
    session.add(other_card)
    await session.commit()

    resp = await demo_client.get("/v1/demo/decisions")

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == []
    assert "wf_other_only" not in resp.text


async def test_list_query_param_shop_id_has_no_effect_x_shop_id_header_is_authoritative(
    demo_client, session, shop, other_shop
):
    """Shop scope now comes exclusively from the authenticated `X-Shop-Id`
    header (via `get_active_shop`), the same channel every other
    authenticated route uses — a `shop_id` query param is simply not part of
    this route's contract any more (it used to be explicitly rejected while
    the route was unauthenticated and server-bound; #1283)."""
    own_card = _card(shop.id, workflow_key="wf_own", priority=1, surfaced_at=COMPUTED_AT)
    session.add(own_card)
    await session.commit()

    resp = await demo_client.get(
        "/v1/demo/decisions",
        params={"shop_id": str(other_shop.id)},
    )

    assert resp.status_code == 200
    ids = [item["id"] for item in resp.json()["data"]]
    assert ids == [str(own_card.id)]


async def test_detail_query_param_shop_id_has_no_effect(demo_client, session, shop, other_shop):
    own_card = _card(shop.id, workflow_key="wf_own", priority=1, surfaced_at=COMPUTED_AT)
    session.add(own_card)
    await session.commit()

    resp = await demo_client.get(
        f"/v1/demo/decisions/{own_card.id}",
        params={"shop_id": str(other_shop.id)},
    )
    assert resp.status_code == 200


async def test_detail_returns_another_shops_surfaced_card_as_404_tenant_pivot_attempt(
    demo_client, session, shop, other_shop
):
    """The core tenant-pivot attempt: a caller who has (or guesses) another
    shop's action_card_id must not be able to read it while scoped to their
    own shop."""
    other_card = _card(
        other_shop.id,
        workflow_key="wf_other_secret",
        priority=1,
        surfaced_at=COMPUTED_AT,
        title="Other tenant's private decision title",
    )
    session.add(other_card)
    await session.commit()

    resp = await demo_client.get(f"/v1/demo/decisions/{other_card.id}")

    assert resp.status_code == 404
    assert "wf_other_secret" not in resp.text
    assert "Other tenant's private decision title" not in resp.text


# ---------------------------------------------------------------------------
# Detail 404 semantics — "safe default": existence is never leaked
# ---------------------------------------------------------------------------


async def test_detail_returns_404_for_suppressed_card_not_leaked_as_active(
    demo_client, session, shop
):
    suppressed = _card(
        shop.id,
        workflow_key="wf_suppressed",
        priority=1,
        surfaced_at=None,
        suppressed_reason="cooldown",
    )
    session.add(suppressed)
    await session.commit()

    resp = await demo_client.get(f"/v1/demo/decisions/{suppressed.id}")
    assert resp.status_code == 404


async def test_detail_returns_404_for_nonexistent_card(demo_client, shop):
    resp = await demo_client.get(f"/v1/demo/decisions/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_detail_404_response_shape_identical_for_suppressed_and_nonexistent(
    demo_client, session, shop
):
    """Suppressed-vs-nonexistent must be indistinguishable from the outside —
    otherwise the 404 itself becomes an existence oracle."""
    suppressed = _card(
        shop.id,
        workflow_key="wf_suppressed",
        priority=1,
        surfaced_at=None,
        suppressed_reason="cooldown",
    )
    session.add(suppressed)
    await session.commit()

    resp_suppressed = await demo_client.get(f"/v1/demo/decisions/{suppressed.id}")
    resp_missing = await demo_client.get(f"/v1/demo/decisions/{uuid.uuid4()}")

    assert resp_suppressed.status_code == resp_missing.status_code == 404
    assert resp_suppressed.json() == resp_missing.json()


async def test_detail_returns_surfaced_card_with_freshness_metadata(demo_client, session, shop):
    surfaced_at = datetime(2026, 8, 8, 9, 30, tzinfo=UTC)
    card = _card(
        shop.id, workflow_key="wf_a", priority=1, surfaced_at=surfaced_at, computed_at=COMPUTED_AT
    )
    session.add(card)
    await session.commit()

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


async def test_no_internal_identifiers_or_leaked_content_in_response_body(
    demo_client, session, shop, other_shop
):
    internal_uuid_marker = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    financial_marker = "987654321.42"

    # Card A: legitimately surfaced for the caller's shop — its own
    # workflow_key must not leak even though the card itself IS included.
    included = _card(
        shop.id,
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

    # Card B: suppressed for the caller's shop — must never appear at all.
    suppressed_poisoned = _card(
        shop.id,
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

    # Card C: surfaced for a DIFFERENT (non-caller) shop — tenant pivot
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


async def test_integration_compute_scoring_persist_emission_filter_get_reflects_gated_list(
    demo_client, session, shop
):
    workflows = [
        (f"wf_integration_{i}", f"Workflow {i}", i) for i in range(1, 8)
    ]  # 7 candidates, default max_active=5
    result = _scoring_result(shop.id, workflows=workflows)

    cards = await persist_scoring_result(session, shop.id, result)
    assert len(cards) == 7
    outcome = await apply_emission_budget(session, shop.id, now=COMPUTED_AT)
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


async def test_list_failure_surfaces_as_error_not_a_silently_invented_empty_list(
    demo_client, session, shop, monkeypatch
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
# must not 500 the whole feed. Pydantic's typed response schema rejecting an
# unexpected shape is the correct security outcome (no leak); the bug is
# that the resulting ValidationError previously escaped the route's
# try/except entirely and took down every other row with it.
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


async def test_list_drops_malformed_row_and_still_serves_remaining_rows(
    demo_client, session, shop, caplog
):
    """The core regression test: one malformed row must not 500 the whole
    feed, must not appear in the response, and must not leak any of its
    own content — the remaining well-formed rows must still be served."""
    good = _card(shop.id, workflow_key="wf_good", priority=1, surfaced_at=COMPUTED_AT)
    bad = _malformed_card(shop.id, priority=2)
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
    assert getattr(record, "shop_id", None) == str(shop.id)
    assert getattr(record, "action_card_id", None) == str(bad.id)
    log_text = str(record.__dict__)
    assert "evil_tool" not in log_text
    assert "wf_malformed_shape" not in log_text
    assert "aaaa-bbbb-cccc-dddd" not in log_text


async def test_list_with_all_rows_malformed_returns_empty_list_not_500(demo_client, session, shop):
    """Every row bad is still not a 500 — an empty (but valid) list is the
    correct degraded response, distinct from a query failure."""
    bad_a = _malformed_card(shop.id, priority=1, workflow_key="wf_malformed_a")
    bad_b = _malformed_card(shop.id, priority=2, workflow_key="wf_malformed_b")
    session.add_all([bad_a, bad_b])
    await session.commit()

    resp = await demo_client.get("/v1/demo/decisions")

    assert resp.status_code == 200
    assert resp.json()["data"] == []


async def test_detail_returns_500_for_malformed_persisted_row_not_a_misleading_404(
    demo_client, session, shop, caplog
):
    """Deliberate detail-endpoint decision (#718 Review finding 1): unlike
    the list, a single detail lookup has no partial result to preserve — the
    row the caller asked for genuinely cannot be represented. Degrading it
    to 404 would misrepresent a data-integrity problem as "this Decision
    doesn't exist", which is a worse signal for on-call debugging than an
    honest, logged 500. So detail intentionally does NOT silently drop; it
    surfaces the same 500 contract as any other unexpected read failure on
    this route."""
    bad = _malformed_card(shop.id)
    session.add(bad)
    await session.commit()

    with caplog.at_level("WARNING", logger="juli_backend.api.routes.demo_decisions"):
        resp = await demo_client.get(f"/v1/demo/decisions/{bad.id}")

    assert resp.status_code == 500
    assert "evil_tool" not in resp.text
    assert "wf_malformed_shape" not in resp.text


# ---------------------------------------------------------------------------
# AC8 (#1283) — the listing/approving split: a card that appears in the list
# is approvable by the same caller. Same session/app fixture as
# test_api_demo_execution.py so both routers see the same rows.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def product(session, shop):
    p = Product(
        shop_id=shop.id,
        tiktok_product_id=f"agt-1283-{uuid.uuid4()}",
        name="Test Widget",
        status="active",
        revenue=Decimal("100.00"),
        update_time=_naive_utc_now(),
    )
    session.add(p)
    await session.flush()
    await session.commit()
    return p


@pytest_asyncio.fixture
async def surfaced_card(session, shop):
    c = _card(shop.id, workflow_key="optimize_product_2", priority=1, surfaced_at=COMPUTED_AT)
    session.add(c)
    await session.commit()
    return c


async def test_a_card_that_appears_in_the_list_is_approvable_by_the_same_caller(
    app, session, user, shop, product, surfaced_card
):
    """Proves the listing/approving split (#1283) is closed: the same
    credentials that can list a card can also approve exactly that listed
    id — no separate scope resolution, no cross-tenant 404 surprise."""
    mock_task = MagicMock()
    mock_async_result = MagicMock()
    mock_async_result.id = "celery-task-id-1283"
    mock_task.delay.return_value = mock_async_result

    with patch("juli_backend.workers.tasks.agent_workflow.run_agent_workflow", mock_task):
        async with _client_for(app, user, shop) as client:
            list_resp = await client.get("/v1/demo/decisions")
            assert list_resp.status_code == 200
            listed_ids = [item["id"] for item in list_resp.json()["data"]]
            assert str(surfaced_card.id) in listed_ids

            approve_resp = await client.post(
                f"/v1/demo/decisions/{surfaced_card.id}/approve",
            )

    assert approve_resp.status_code == 202, approve_resp.text
    assert approve_resp.json()["data"]["action_card_id"] == str(surfaced_card.id)
