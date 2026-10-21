"""P20 shop terms (DECISIONS D28.4 tab Thời hạn, D28.5 payment-ready grant), SQLite.

- expiry states and their boundaries (14 / 0 / -1 / -7 / -8 days, none)
- ``grant_period``: dates, idempotency on (source, reference), stacking, refusals
- enforcement on a read-only shop: card emission, quick scan, seller writes
  (approve / confirmations / revert / redraft / content analysis), drafting,
  agent runs, content analysis -- and NOT in grace, NOT with no term set
- Ops routes ``/v1/ops/terms``, ``/v1/ops/shops/{id}/terms`` (roles, audit), the
  view-as term, and the seller's ``GET /v1/shops/me/term``
- migration 086 shape
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import func, select

from juli_backend.api.routes.ops import get_ops_user
from juli_backend.core.security import get_current_user
from juli_backend.models.models import Shop, User
from juli_backend.models.ops import OpsAuditLog, OpsStaff
from juli_backend.models.subscriptions import ShopSubscriptionPeriod
from juli_backend.services import subscriptions as subs
from juli_backend.services.ops import audit
from juli_backend.services.subscriptions import terms as terms_module
from tests.support.api import authenticated_client, build_app, client_for
from tests.support.builders import make_tenant, make_user

REPO = Path(__file__).resolve().parents[2]
VERSIONS = REPO / "backend/src/juli_backend/database/migrations/versions"
MIGRATION = VERSIONS / "086_ops_cost_and_terms.py"
TODAY = date(2026, 10, 12)


@pytest.fixture(autouse=True)
def bypass_access(monkeypatch):
    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")


@pytest.fixture
def frozen_today(monkeypatch):
    """Every reader without an explicit ``today`` sees 12/10/2026."""
    monkeypatch.setattr(terms_module, "shop_today", lambda now=None: TODAY)
    # The Ops routes call it through the package root (`subscriptions.shop_today`),
    # a separate binding: without this the route tests used the real date and
    # failed from 13/10/2026 (Vietnam time) on.
    monkeypatch.setattr(subs, "shop_today", lambda now=None: TODAY)
    return TODAY


async def _staff(session, role: str) -> User:
    email = f"{role}-{uuid.uuid4().hex[:6]}@app-juli.com"
    user = await make_user(session, email=email)
    session.add(OpsStaff(id=uuid.uuid4(), email=email, role=role, active=True))
    await session.flush()
    return user


def _client_as(session, user: User):
    app = build_app(session)

    async def current() -> User:
        await session.refresh(user)
        return user

    app.dependency_overrides[get_current_user] = current

    app.dependency_overrides[get_ops_user] = current
    return client_for(app)


async def _period(session, shop: Shop, ends_on: date, *, days: int = 30, ref: str | None = None):
    row = ShopSubscriptionPeriod(
        id=uuid.uuid4(),
        shop_id=shop.id,
        plan="month" if days == 30 else "year",
        days=days,
        starts_on=ends_on - timedelta(days=days),
        ends_on=ends_on,
        source="contract",
        reference=ref or f"HĐ-{uuid.uuid4().hex[:6]}",
        actor_email="thien.phung@app-juli.com",
    )
    session.add(row)
    await session.flush()
    return row


async def _shop_with_days_left(session, left: int | None) -> Shop:
    _, shop = await make_tenant(session)
    if left is not None:
        await _period(session, shop, TODAY + timedelta(days=left))
    return shop


async def _count(session, model, **where) -> int:
    stmt = select(func.count()).select_from(model)
    for key, value in where.items():
        stmt = stmt.where(getattr(model, key) == value)
    return int((await session.execute(stmt)).scalar_one())


# -- states and boundaries --------------------------------------------------------------


@pytest.mark.parametrize(
    ("left", "state", "grace_left"),
    [
        (15, "ok", None),
        (14, "soon", None),
        (0, "soon", None),
        (-1, "grace", 6),
        (-7, "grace", 0),
        (-8, "read_only", None),
        (-40, "read_only", None),
    ],
)
def test_term_states_and_boundaries(left, state, grace_left):
    term = subs.term_for(TODAY + timedelta(days=left), TODAY)
    assert term.state == state
    assert term.days_left == left
    assert term.grace_days_left == grace_left
    assert term.read_only is (state == "read_only")


def test_no_period_is_none_and_not_restricted():
    term = subs.term_for(None, TODAY)
    assert term.state == "none" and not term.read_only
    assert term.to_json() == {
        "state": "none",
        "expires_on": None,
        "days_left": None,
        "grace_days_left": None,
    }


def test_shop_today_is_the_vietnam_calendar_day():
    from datetime import UTC, datetime

    assert subs.shop_today(datetime(2026, 10, 11, 17, 0, tzinfo=UTC)) == date(2026, 10, 12)
    assert subs.shop_today(datetime(2026, 10, 11, 16, 59, tzinfo=UTC)) == date(2026, 10, 11)


async def test_shop_term_reads_the_latest_end(session):
    shop = await _shop_with_days_left(session, -20)
    await _period(session, shop, TODAY + timedelta(days=3))
    term = await subs.shop_term(session, shop.id, TODAY)
    assert term.state == "soon" and term.expires_on == TODAY + timedelta(days=3)


@pytest.mark.parametrize(
    ("left", "restricted"), [(None, False), (0, False), (-7, False), (-8, True)]
)
async def test_is_read_only(session, left, restricted):
    shop = await _shop_with_days_left(session, left)
    assert await subs.is_read_only(session, shop.id, TODAY) is restricted


# -- grant_period (D28.4 / D28.5) ---------------------------------------------------------


async def test_first_grant_starts_today(session):
    _, shop = await make_tenant(session)
    grant = await subs.grant_period(
        session,
        shop.id,
        days=30,
        source="contract",
        reference="HĐ-1",
        actor_email="a@app-juli.com",
        today=TODAY,
    )
    assert grant.created and grant.before.state == "none"
    assert (grant.period.starts_on, grant.period.ends_on) == (TODAY, TODAY + timedelta(days=30))
    assert grant.period.plan == "month" and grant.after.days_left == 30


async def test_grant_is_idempotent_on_source_and_reference(session):
    _, shop = await make_tenant(session)
    first = await subs.grant_period(
        session,
        shop.id,
        days=365,
        source="payment",
        reference="pay_123",
        actor_email=None,
        today=TODAY,
    )
    again = await subs.grant_period(
        session,
        shop.id,
        days=365,
        source="payment",
        reference=" pay_123 ",
        actor_email=None,
        today=TODAY + timedelta(days=3),
    )
    assert first.created and not again.created
    assert again.period.id == first.period.id
    assert await _count(session, ShopSubscriptionPeriod, shop_id=shop.id) == 1
    assert first.period.plan == "year" and first.period.ends_on == TODAY + timedelta(days=365)


async def test_same_reference_under_another_source_is_a_new_period(session):
    _, shop = await make_tenant(session)
    await subs.grant_period(
        session, shop.id, days=30, source="contract", reference="X-1", actor_email=None, today=TODAY
    )
    second = await subs.grant_period(
        session, shop.id, days=30, source="payment", reference="X-1", actor_email=None, today=TODAY
    )
    assert second.created


async def test_an_active_shop_stacks_from_its_current_end(session):
    shop = await _shop_with_days_left(session, 5)
    grant = await subs.grant_period(
        session,
        shop.id,
        days=30,
        source="contract",
        reference="HĐ-2",
        actor_email=None,
        today=TODAY,
    )
    assert grant.period.starts_on == TODAY + timedelta(days=5)
    assert grant.after.days_left == 35 and grant.after.state == "ok"


async def test_a_shop_expiring_today_still_stacks(session):
    shop = await _shop_with_days_left(session, 0)
    grant = await subs.grant_period(
        session,
        shop.id,
        days=30,
        source="contract",
        reference="HĐ-3",
        actor_email=None,
        today=TODAY,
    )
    assert grant.period.starts_on == TODAY and grant.after.days_left == 30


@pytest.mark.parametrize("left", [-1, -7, -30])
async def test_an_expired_shop_starts_today(session, left):
    shop = await _shop_with_days_left(session, left)
    grant = await subs.grant_period(
        session,
        shop.id,
        days=30,
        source="contract",
        reference=f"HĐ-{left}",
        actor_email=None,
        today=TODAY,
    )
    assert grant.before.state in ("grace", "read_only")
    assert grant.period.starts_on == TODAY and grant.after.state == "ok"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"days": 31}, "30 or 365"),
        ({"days": True}, "30 or 365"),
        ({"source": "gift"}, "source"),
        ({"reference": "   "}, "reference"),
        ({"reference": "x" * 121}, "120"),
    ],
)
async def test_grant_refusals(session, kwargs, message):
    _, shop = await make_tenant(session)
    args = {"days": 30, "source": "contract", "reference": "HĐ-9", "actor_email": None}
    args.update(kwargs)
    with pytest.raises(subs.GrantError, match=message):
        await subs.grant_period(session, shop.id, today=TODAY, **args)


async def test_a_reference_of_another_shop_is_refused(session):
    _, shop_a = await make_tenant(session)
    _, shop_b = await make_tenant(session)
    await subs.grant_period(
        session,
        shop_a.id,
        days=30,
        source="contract",
        reference="HĐ-A",
        actor_email=None,
        today=TODAY,
    )
    with pytest.raises(subs.GrantError, match="another shop"):
        await subs.grant_period(
            session,
            shop_b.id,
            days=30,
            source="contract",
            reference="HĐ-A",
            actor_email=None,
            today=TODAY,
        )


# -- enforcement --------------------------------------------------------------------------


class _PastTheGate(Exception):
    pass


@pytest.mark.parametrize(("left", "skipped"), [(-8, True), (-3, False), (None, False)])
async def test_card_emission_skips_only_a_read_only_shop(
    session, monkeypatch, frozen_today, left, skipped
):
    from juli_backend.services.action_cards import persist

    shop = await _shop_with_days_left(session, left)

    async def _sentinel(*args, **kwargs):
        raise _PastTheGate

    monkeypatch.setattr(persist, "_plan_optimize_product", _sentinel)

    class _Signals:
        from datetime import UTC, datetime

        computed_at = datetime(2026, 10, 12, 2, 0, tzinfo=UTC)

    class _Result:
        signals = _Signals()

    if skipped:
        report = await persist.emit_scoring_cards(session, shop.id, cast(Any, _Result()))
        assert report.decisions == ()
    else:
        with pytest.raises(_PastTheGate):
            await persist.emit_scoring_cards(session, shop.id, cast(Any, _Result()))


async def test_quick_scan_skips_a_read_only_shop(session, engine, frozen_today):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from juli_backend.services.onboarding.quick_scan import run_quick_scan

    shop = await _shop_with_days_left(session, -8)
    await session.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _no_credential(*args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("a read-only shop must not read TikTok for cards")

    result = await run_quick_scan(
        session_factory=factory,
        shop_id=shop.id,
        app_key="k",
        app_secret="s",
        resolve_credential=_no_credential,
    )
    assert result.skipped_reason == "read_only"


SELLER_WRITES = [
    ("post", "/v1/demo/decisions/{id}/approve", None),
    ("post", "/v1/demo/runs/{id}/confirmations/tc_1", {"decision": "approve"}),
    ("post", "/v1/demo/runs/{id}/revert", {"reason_code": "other"}),
    ("post", "/v1/demo/runs/{id}/content/redraft", None),
    ("post", "/v1/executions", {"approval_id": "a", "tool_name": "t", "payload": {}}),
    (
        "post",
        "/v1/demo/content-analysis",
        {
            "kind": "video",
            "content_ref": "video:1",
            "file_name": "a.mp4",
            "content_type": "video/mp4",
            "size_bytes": 10,
        },
    ),
]


@pytest.mark.parametrize(("method", "path", "body"), SELLER_WRITES)
async def test_read_only_shop_refuses_seller_actions(session, frozen_today, method, path, body):
    user, shop = await make_tenant(session)
    await _period(session, shop, TODAY - timedelta(days=8))
    async with authenticated_client(session, user=user, shop=shop) as client:
        response = await getattr(client, method)(
            path.format(id=uuid.uuid4()), json=body, headers={"X-Shop-Id": str(shop.id)}
        )
    assert response.status_code == 403, response.text
    assert response.json() == {
        "detail": "Shop đang ở chế độ chỉ xem — liên hệ lienhe@app-juli.com để gia hạn."
    }


@pytest.mark.parametrize("left", [-7, None])
async def test_grace_and_no_term_do_not_refuse_an_approve(session, frozen_today, left):
    user, shop = await make_tenant(session)
    if left is not None:
        await _period(session, shop, TODAY + timedelta(days=left))
    async with authenticated_client(session, user=user, shop=shop) as client:
        response = await client.post(
            f"/v1/demo/decisions/{uuid.uuid4()}/approve", headers={"X-Shop-Id": str(shop.id)}
        )
    assert response.status_code == 404  # past the gate: an unknown card


async def test_read_only_shop_gets_no_drafting(session, frozen_today):
    from juli_backend.services.content_cards.driver import draft_gate_for
    from juli_backend.services.content_cards.planner import DraftGate

    shop = await _shop_with_days_left(session, -8)
    gate = await draft_gate_for(session, shop.id)
    assert gate.read_only is True
    refusal = gate.refusal()
    assert refusal is not None
    code, _, text = refusal
    assert code == "shop_read_only" and "chỉ xem" in text
    # Grace: drafting runs.
    grace = await _shop_with_days_left(session, -2)
    assert (await draft_gate_for(session, grace.id)).refusal() is None
    both = DraftGate(read_only=True, system_cap_reached=True).refusal()
    assert both is not None and both[0] == "shop_read_only"


async def test_read_only_drafting_ends_the_content_run_with_the_seller_text(session, monkeypatch):
    from juli_backend.services.agent.events import InMemoryEventSink
    from tests.support.lever_flows import seed_shop
    from tests.unit.test_p14_content_flow import (
        PRODUCT_ID,
        FakeAnalytics,
        FakeDrafter,
        SeoProducts,
        _content_run,
        _leg,
        _reload,
        _resources,
        _video_script,
    )

    shop, product = await seed_shop(session)
    real_today = subs.shop_today()
    await _period(session, shop, real_today - timedelta(days=8))
    await session.commit()
    _, run = await _content_run(session, shop, product)
    drafter = FakeDrafter(_video_script())
    res = _resources(FakeAnalytics(), SeoProducts())
    await (await _leg(session, run.id, res, drafter, InMemoryEventSink())).run(
        run.id, product_ref=PRODUCT_ID
    )
    await session.commit()
    assert drafter.calls == []
    row = await _reload(session, run.id)
    assert row.state["content_run"]["error"] == "shop_read_only"


async def test_read_only_agent_run_makes_no_model_call(session, frozen_today):
    from juli_backend.services.agent.llm.openai_adapter import LLMProviderError
    from juli_backend.services.ops import overrides as ov

    shop = await _shop_with_days_left(session, -8)

    class Inner:
        calls = 0

        async def complete(self, **kwargs):
            Inner.calls += 1

    guarded = await ov.cap_guarded(session, shop.id, Inner())
    with pytest.raises(LLMProviderError, match="shop_read_only"):
        await guarded.complete(messages=[])
    assert Inner.calls == 0
    grace = await _shop_with_days_left(session, -1)
    await (await ov.cap_guarded(session, grace.id, Inner())).complete(messages=[])
    assert Inner.calls == 1


async def test_read_only_shop_gets_no_content_analysis(session, frozen_today):
    from juli_backend.services.content_analysis import costs

    shop = await _shop_with_days_left(session, -8)
    with pytest.raises(costs.CostCapExceeded) as caught:
        await costs.check(session, shop.id)
    assert caught.value.code == "shop_read_only"
    assert "chỉ xem" in caught.value.message_vi
    grace = await _shop_with_days_left(session, -7)
    await costs.check(session, grace.id)  # within the shop's own $5 default


# -- Ops routes ---------------------------------------------------------------------------


async def test_terms_list_every_shop_sorted_by_days_left(session, frozen_today):
    viewer = await _staff(session, "viewer")
    soon = await _shop_with_days_left(session, 5)
    ro = await _shop_with_days_left(session, -12)
    unset = await _shop_with_days_left(session, None)
    ok = await _shop_with_days_left(session, 112)
    async with _client_as(session, viewer) as client:
        response = await client.get("/v1/ops/terms")
    assert response.status_code == 200
    body = response.json()
    assert body["today"] == "2026-10-12"
    order = [r["shop_id"] for r in body["shops"]]
    mine = [s for s in order if s in {str(soon.id), str(ro.id), str(unset.id), str(ok.id)}]
    assert mine == [str(ro.id), str(soon.id), str(ok.id), str(unset.id)]
    by_id = {r["shop_id"]: r for r in body["shops"]}
    assert by_id[str(ro.id)]["state"] == "read_only"
    assert by_id[str(soon.id)]["state"] == "soon" and by_id[str(soon.id)]["days_left"] == 5
    assert by_id[str(unset.id)]["state"] == "none" and by_id[str(unset.id)]["latest_period"] is None
    assert by_id[str(ok.id)]["latest_period"]["source"] == "contract"
    assert by_id[str(ok.id)]["stage_label"] == "Thử nghiệm"


@pytest.mark.parametrize("role", ["viewer", "operator"])
async def test_adding_a_period_is_admin_only(session, frozen_today, role):
    staff = await _staff(session, role)
    _, shop = await make_tenant(session)
    async with _client_as(session, staff) as client:
        response = await client.post(
            f"/v1/ops/shops/{shop.id}/terms", json={"days": 30, "reference": "HĐ-1"}
        )
    assert response.status_code == 403
    assert await _count(session, ShopSubscriptionPeriod, shop_id=shop.id) == 0


async def test_admin_adds_a_period_with_one_audit_row(session, frozen_today):
    admin = await _staff(session, "admin")
    shop = await _shop_with_days_left(session, 5)
    async with _client_as(session, admin) as client:
        response = await client.post(
            f"/v1/ops/shops/{shop.id}/terms", json={"days": 365, "reference": "HĐ-2026-014"}
        )
        again = await client.post(
            f"/v1/ops/shops/{shop.id}/terms", json={"days": 365, "reference": "HĐ-2026-014"}
        )
        history = await client.get(f"/v1/ops/shops/{shop.id}/terms")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created"] is True
    assert body["period"]["starts_on"] == "2026-10-17"
    assert body["period"]["ends_on"] == "2027-10-17"
    assert body["period"]["source"] == "contract" and body["period"]["actor_email"].endswith(
        "@app-juli.com"
    )
    assert body["term"]["days_left"] == 370
    assert again.json()["created"] is False
    rows = (
        (await session.execute(select(OpsAuditLog).where(OpsAuditLog.shop_id == shop.id)))
        .scalars()
        .all()
    )
    assert [r.action for r in rows] == ["subscription_period_added"]
    assert audit.kind_of(rows[0].action) == "config"
    assert rows[0].before["term"]["days_left"] == 5
    assert rows[0].after["period"]["reference"] == "HĐ-2026-014"
    periods = history.json()["periods"]
    assert [p["reference"] for p in periods][0] == "HĐ-2026-014"  # newest first
    assert len(periods) == 2


@pytest.mark.parametrize(
    "body", [{"days": 31, "reference": "HĐ"}, {"days": 30, "reference": "  "}, {"days": 30}]
)
async def test_bad_period_bodies_are_422(session, frozen_today, body):
    admin = await _staff(session, "admin")
    _, shop = await make_tenant(session)
    shop_id = shop.id  # a refused grant rolls the shared session back
    await session.commit()
    async with _client_as(session, admin) as client:
        response = await client.post(f"/v1/ops/shops/{shop_id}/terms", json=body)
    assert response.status_code == 422
    assert await _count(session, OpsAuditLog, shop_id=shop_id) == 0


async def test_unknown_shop_is_404(session):
    admin = await _staff(session, "admin")
    async with _client_as(session, admin) as client:
        response = await client.post(
            f"/v1/ops/shops/{uuid.uuid4()}/terms", json={"days": 30, "reference": "HĐ"}
        )
    assert response.status_code == 404


async def test_view_as_and_seller_read_the_same_term(session, frozen_today):
    viewer = await _staff(session, "viewer")
    user, shop = await make_tenant(session)
    await _period(session, shop, TODAY - timedelta(days=3))
    async with _client_as(session, viewer) as client:
        view = await client.get(f"/v1/ops/shops/{shop.id}/view/term")
    async with authenticated_client(session, user=user, shop=shop) as client:
        seller = await client.get("/v1/shops/me/term", headers={"X-Shop-Id": str(shop.id)})
    assert view.status_code == 200 and seller.status_code == 200
    assert view.json() == seller.json()
    assert seller.json()["data"] == {
        "state": "grace",
        "expires_on": "2026-10-09",
        "days_left": -3,
        "grace_days_left": 4,
    }


async def test_view_as_term_write_is_refused(session):
    viewer = await _staff(session, "admin")
    _, shop = await make_tenant(session)
    async with _client_as(session, viewer) as client:
        response = await client.post(f"/v1/ops/shops/{shop.id}/view/term")
    assert response.status_code == 403


# -- migration 086 ------------------------------------------------------------------------


def test_migration_086_chain_and_shape():
    text = MIGRATION.read_text(encoding="utf-8")
    assert 'revision: str = "086_ops_cost_and_terms"' in text
    assert len("086_ops_cost_and_terms") <= 32
    assert 'down_revision: str | None = "085_ops_daily_precompute"' in text
    deferred = (
        MIGRATION.parents[1] / "deferred" / "074_users_placeholder_phone_cleanup.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision: str | None = "098_processed_events_retention"' in deferred
    # Head: nothing else in versions/ names 085 as its parent.
    children = [
        p.name
        for p in VERSIONS.glob("*.py")
        if 'down_revision: str | None = "085_ops_daily_precompute"' in p.read_text("utf-8")
    ]
    assert children == ["086_ops_cost_and_terms.py"]
    for model in (ShopSubscriptionPeriod,):
        for column in model.__table__.columns.keys():
            assert f'"{column}"' in text, column
    assert 'PERIODS_VERBS = "SELECT, INSERT"' in text  # append-only history
    assert "app_current_shop_id()" in text and "ENABLE ROW LEVEL SECURITY" in text
    assert 'UniqueConstraint("source", "reference"' in text
    assert "days IN (30, 365)" in text and "plan IN ('month', 'year')" in text
    assert "source IN ('contract', 'payment')" in text
    assert "FOR ALL TO {OPS_ROLE}" in text and "FOR SELECT TO {APP_ROLE} USING (true)" in text
    assert 'SYSTEM_APP_VERBS = "SELECT"' in text
    assert "SECURITY DEFINER SET search_path = pg_catalog, public" in text
    assert "openai_spend_since(p_since timestamp)" in text
    assert "REVOKE ALL ON FUNCTION {SPEND_FN} FROM PUBLIC" in text
    assert "GRANT EXECUTE ON FUNCTION {SPEND_FN} TO {APP_ROLE}" in text
    assert "GRANT EXECUTE ON FUNCTION {SPEND_FN} TO {OPS_ROLE}" in text
    for column in ("workflow_runs", "content_analyses", "cost_usd", "created_at >= p_since"):
        assert column in text


def test_migration_086_is_additive():
    import sys

    sys.path.insert(0, str(REPO / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    assert evaluate_migration_paths([MIGRATION]).accepted


def test_new_tables_are_classified():
    from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP

    assert TABLE_CLASSIFICATION_MAP[("public", "shop_subscription_periods")] == "tenant_direct"
    assert TABLE_CLASSIFICATION_MAP[("public", "ops_system_settings")] == "non_tenant"
