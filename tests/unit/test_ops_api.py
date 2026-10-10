"""P16 Juli Ops API (/v1/ops/*): roles, Access gate, audit, masking, act gating,
settings overrides, simulation + scenarios, invite / handover (SQLite)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from juli_backend.core.security import get_current_user
from juli_backend.models.models import Shop, User
from juli_backend.models.ops import OpsAuditLog, OpsShopSettings, OpsSimScenario, OpsStaff
from juli_backend.models.run_changes import ShopRule
from juli_backend.models.shop_diagnosis import ShopDiagnosisReport
from juli_backend.services.ops import mailer as ops_mailer
from juli_backend.services.ops import simulation as sim
from tests.support.api import build_app, client_for
from tests.support.builders import make_run_event, make_tenant, make_user, make_workflow_run


@pytest.fixture(autouse=True)
def bypass_access(monkeypatch):
    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")


class FakeMailer:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.sent: list[ops_mailer.InviteMail] = []

    async def send_invite(self, mail):
        self.sent.append(mail)
        return self.ok


@pytest.fixture(autouse=True)
def fake_mailer():
    mailer = FakeMailer()
    ops_mailer.set_mailer(mailer)
    yield mailer
    ops_mailer.set_mailer(None)


async def _staff(session, role: str, email: str | None = None, *, active: bool = True):
    email = email or f"{role}-{uuid.uuid4().hex[:6]}@app-juli.com"
    user = await make_user(session, email=email)
    session.add(OpsStaff(id=uuid.uuid4(), email=email, role=role, active=active))
    await session.flush()
    return user


def _client_as(session, user: User):
    app = build_app(session)

    async def current() -> User:
        await session.refresh(user)  # a route's rollback expires it, like a new request
        return user

    app.dependency_overrides[get_current_user] = current
    return client_for(app)


async def _audit_count(session, action: str | None = None) -> int:
    stmt = select(func.count()).select_from(OpsAuditLog)
    if action:
        stmt = stmt.where(OpsAuditLog.action == action)
    return int((await session.execute(stmt)).scalar_one())


# -- gates -------------------------------------------------------------------------


async def test_non_staff_is_forbidden(session):
    outsider = await make_user(session, email="seller@gmail.com")
    async with _client_as(session, outsider) as client:
        assert (await client.get("/v1/ops/me")).status_code == 403


async def test_inactive_staff_is_forbidden(session):
    user = await _staff(session, "admin", active=False)
    async with _client_as(session, user) as client:
        assert (await client.get("/v1/ops/me")).status_code == 403


async def test_staff_seeded_by_email_binds_user_on_first_sign_in(session):
    user = await _staff(session, "viewer", "new.person@app-juli.com")
    async with _client_as(session, user) as client:
        response = await client.get("/v1/ops/me")
    assert response.status_code == 200
    assert response.json() == {
        "email": "new.person@app-juli.com",
        "role": "viewer",
        "role_label": "Xem",
    }
    row = (await session.execute(select(OpsStaff))).scalars().one()
    assert row.user_id == user.id


async def test_missing_access_header_fails_closed(session, monkeypatch):
    monkeypatch.delenv("OPS_CF_ACCESS_BYPASS")
    user = await _staff(session, "admin")
    async with _client_as(session, user) as client:
        response = await client.get("/v1/ops/overview")
    assert response.status_code == 403


async def test_no_supabase_token_is_401(session):
    app = build_app(session)
    async with client_for(app) as client:
        assert (await client.get("/v1/ops/me")).status_code == 401


@pytest.mark.parametrize(
    ("role", "method", "path_tail", "body", "allowed"),
    [
        ("viewer", "get", "settings", None, True),
        ("viewer", "put", "settings", {"changes": {"stage": "pilot"}}, False),
        ("operator", "put", "settings", {"changes": {"stage": "pilot"}}, True),
        ("viewer", "post", "settings/reset", None, False),
        ("operator", "post", "settings/reset", None, True),
        ("viewer", "post", "invites", {"email": "s@gmail.com"}, False),
        ("operator", "post", "invites", {"email": "s@gmail.com"}, True),
        ("viewer", "post", "scenarios", {"name": "A", "deltas": {}}, False),
        ("operator", "post", "scenarios", {"name": "A", "deltas": {}}, True),
    ],
)
async def test_role_matrix_per_shop(session, role, method, path_tail, body, allowed):
    _, shop = await make_tenant(session)
    user = await _staff(session, role)
    async with _client_as(session, user) as client:
        kwargs = {"json": body} if body is not None else {}
        response = await getattr(client, method)(f"/v1/ops/shops/{shop.id}/{path_tail}", **kwargs)
    assert (response.status_code < 400) is allowed, response.text
    if not allowed:
        assert response.status_code == 403


@pytest.mark.parametrize(
    ("role", "allowed"), [("viewer", False), ("operator", False), ("admin", True)]
)
async def test_staff_admin_is_admin_only(session, role, allowed):
    user = await _staff(session, role)
    async with _client_as(session, user) as client:
        listed = await client.get("/v1/ops/staff")
        put = await client.put("/v1/ops/staff", json={"email": "x@app-juli.com", "role": "viewer"})
    assert (listed.status_code == 200) is allowed
    assert (put.status_code == 200) is allowed


async def test_last_admin_cannot_be_demoted(session):
    user = await _staff(session, "admin", "boss@app-juli.com")
    async with _client_as(session, user) as client:
        response = await client.put(
            "/v1/ops/staff", json={"email": "boss@app-juli.com", "role": "viewer"}
        )
    assert response.status_code == 422


# -- settings ----------------------------------------------------------------------


async def test_settings_put_audits_before_after_and_reset(session):
    _, shop = await make_tenant(session)
    user = await _staff(session, "operator", "op@app-juli.com")
    async with _client_as(session, user) as client:
        first = await client.get(f"/v1/ops/shops/{shop.id}/settings")
        assert first.json()["settings"]["overrides"]["card_daily_limit"] is None
        assert first.json()["settings"]["defaults"]["card_daily_limit"] == 5
        put = await client.put(
            f"/v1/ops/shops/{shop.id}/settings",
            json={
                "changes": {"card_daily_limit": 3, "openai_monthly_cap_usd": 5, "stage": "pilot"}
            },
        )
        assert put.status_code == 200
        body = put.json()["settings"]
        assert body["overrides"]["card_daily_limit"] == 3
        assert body["overrides"]["openai_monthly_cap_usd"] == 5.0
        assert body["stage"] == "pilot"
        reset = await client.post(f"/v1/ops/shops/{shop.id}/settings/reset")
        assert reset.json()["settings"]["overrides"]["card_daily_limit"] is None
        assert reset.json()["settings"]["stage"] == "pilot"
    rows = (await session.execute(select(OpsAuditLog).order_by(OpsAuditLog.at))).scalars().all()
    actions = [r.action for r in rows]
    assert actions.count("settings_update") == 1 and actions.count("settings_reset") == 1
    update = next(r for r in rows if r.action == "settings_update")
    assert update.actor_email == "op@app-juli.com"
    assert update.shop_id == shop.id
    assert update.before == {}
    assert update.after["card_daily_limit"] == 3


@pytest.mark.parametrize(
    "changes",
    [
        {"card_daily_limit": 0},
        {"card_open_limit": "ten"},
        {"enabled_streams": ["tiktok_ads"]},
        {"enabled_actions": ["teleport"]},
        {"openai_model": "gpt-9"},
        {"openai_monthly_cap_usd": -1},
        {"stage": "beta"},
        {"what": 1},
    ],
)
async def test_settings_validation(session, changes):
    _, shop = await make_tenant(session)
    user = await _staff(session, "operator")
    async with _client_as(session, user) as client:
        response = await client.put(f"/v1/ops/shops/{shop.id}/settings", json={"changes": changes})
    assert response.status_code == 422
    assert await _audit_count(session) == 0


async def test_unknown_shop_404(session):
    user = await _staff(session, "viewer")
    async with _client_as(session, user) as client:
        assert (await client.get(f"/v1/ops/shops/{uuid.uuid4()}/settings")).status_code == 404


# -- overview ------------------------------------------------------------------------


async def test_overview_lists_shops_with_totals(session):
    owner, shop = await make_tenant(session)
    owner.email = "seller.long.name@gmail.com"
    from juli_backend.services.shop_rules.openai_cap import set_openai_monthly_cap

    session.add(OpsShopSettings(shop_id=shop.id, stage="self"))
    await set_openai_monthly_cap(session, shop.id, 0, set_by_user_id=None)
    await make_workflow_run(session, shop, status="failed", cost_usd=0.5)
    user = await _staff(session, "viewer")
    async with _client_as(session, user) as client:
        response = await client.get("/v1/ops/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["totals"]["accounts"] >= 1
    row = next(r for r in body["shops"] if r["shop_id"] == str(shop.id))
    assert row["stage"] == "self" and row["stage_label"] == "Tự vận hành"
    assert row["connection"] == "none"
    assert row["failed_runs_30d"] == 1
    assert row["openai_cost_month_usd"] == pytest.approx(0.5)
    assert row["openai_cap_reached"] is True
    # seller e-mail masked
    assert row["owner_email"] == "seller…@…"
    assert body["totals"]["openai_cap_alerts"] == 1


# -- run detail + masking --------------------------------------------------------------


async def test_run_detail_is_read_only_and_masks_buyer_pii(session):
    _, shop = await make_tenant(session)
    run = await make_workflow_run(session, shop, input_tokens=120, output_tokens=40)
    await make_run_event(
        session,
        run.id,
        1,
        event_type="assistant.text",
        payload={
            "text": "Gọi khách 0912 345 678 hoặc mail buyer.person@gmail.com",
            "buyer_name": "Nguyễn Văn A",
        },
    )
    user = await _staff(session, "viewer")
    async with _client_as(session, user) as client:
        response = await client.get(f"/v1/ops/shops/{shop.id}/runs/{run.id}")
        assert (await client.post(f"/v1/ops/shops/{shop.id}/runs/{run.id}")).status_code == 405
    data = response.json()["data"]
    assert data["input_tokens"] == 120 and data["output_tokens"] == 40
    text = data["llm_output"][0]["text"]
    assert "0912" not in text and "buyer.person@gmail.com" not in text
    assert data["timeline"][0]["payload"]["buyer_name"] == "•••"


async def test_run_of_another_shop_is_404(session):
    _, shop_a = await make_tenant(session)
    _, shop_b = await make_tenant(session)
    run = await make_workflow_run(session, shop_b)
    user = await _staff(session, "viewer")
    async with _client_as(session, user) as client:
        assert (await client.get(f"/v1/ops/shops/{shop_a.id}/runs/{run.id}")).status_code == 404


# -- view as / act for seller -------------------------------------------------------------


async def test_view_session_is_logged_and_read_only(session):
    _, shop = await make_tenant(session)
    user = await _staff(session, "admin")
    async with _client_as(session, user) as client:
        view = await client.post(f"/v1/ops/shops/{shop.id}/view-session", json={"mode": "view"})
        assert view.status_code == 200 and view.json()["read_only"] is True
        # there is no act mode any more (D25.3 amended)
        act = await client.post(f"/v1/ops/shops/{shop.id}/view-session", json={"mode": "act"})
        assert act.status_code == 422
    assert await _audit_count(session, "view_as_view") == 1


@pytest.mark.parametrize(
    ("method", "tail"),
    [
        ("post", "decisions/c1/approve"),
        ("post", "decisions/c1/reject"),
        ("put", "rules/max_open_cards"),
        ("delete", "rules/max_open_cards"),
        ("post", "runs/r1/confirmations/call-1"),
        ("patch", "anything"),
        ("post", "decisions"),
    ],
)
async def test_view_as_refuses_every_write_even_for_admin(session, method, tail):
    _, shop = await make_tenant(session)
    user = await _staff(session, "admin")
    async with _client_as(session, user) as client:
        kwargs = {"json": {}} if method != "delete" else {}
        response = await getattr(client, method)(f"/v1/ops/shops/{shop.id}/view/{tail}", **kwargs)
    assert response.status_code == 403
    rules = (await session.execute(select(func.count()).select_from(ShopRule))).scalar_one()
    assert rules == 0


def test_no_act_routes_and_view_is_get_only():
    from juli_backend.api.app import create_app

    paths = create_app().openapi()["paths"]
    assert not [p for p in paths if p.startswith("/v1/ops/") and "/act/" in p]
    for path, ops in paths.items():
        if path.startswith("/v1/ops/shops/{shop_id}/view/"):
            assert set(ops) == {"get"}, path


async def test_view_runs_mirror_the_seller_list(session):
    _, shop = await make_tenant(session)
    await make_workflow_run(session, shop)
    user = await _staff(session, "viewer")
    async with _client_as(session, user) as client:
        response = await client.get(f"/v1/ops/shops/{shop.id}/view/runs")
    assert response.status_code == 200, response.text
    assert len(response.json()["data"]) == 1


async def test_view_analysis_is_the_seller_payload_without_ops_only_keys(session):
    _, shop = await make_tenant(session)
    session.add(
        ShopDiagnosisReport(
            shop_id=shop.id,
            end_date=date(2026, 10, 9),
            ranking="60d",
            report={"shop_name": "X", "daily_products": {"a": 1}, "daily_streams": {}},
            built_at=datetime(2026, 10, 10),
        )
    )
    user = await _staff(session, "viewer")
    async with _client_as(session, user) as client:
        response = await client.get(f"/v1/ops/shops/{shop.id}/view/analysis")
    assert response.status_code == 200
    report = response.json()["report"]
    assert "daily_products" not in report and report["shop_name"] == "X"


# -- simulation + scenarios -----------------------------------------------------------------


def _stored_report(shop: Shop, days: int = 60) -> ShopDiagnosisReport:
    end = date(2026, 10, 9)
    streams = {
        s: {(end - timedelta(days=i)).isoformat(): [1000, 50, 5, 750_000] for i in range(days)}
        for s in sim.STREAMS
    }
    return ShopDiagnosisReport(
        shop_id=shop.id,
        end_date=end,
        ranking="60d",
        report={"daily_streams": streams, "daily_products": {}},
        built_at=datetime(2026, 10, 10),
    )


async def test_simulation_endpoint_windows_and_scenarios(session, monkeypatch):
    monkeypatch.setattr(sim, "HISTORY_DAYS", 100_000)
    _, shop = await make_tenant(session)
    session.add(_stored_report(shop))
    user = await _staff(session, "operator")
    async with _client_as(session, user) as client:
        base = await client.get(f"/v1/ops/shops/{shop.id}/simulation?window=30")
        assert base.status_code == 200
        body = base.json()
        assert body["status"]["comparable"] is True
        assert len(body["streams"]) == 4
        w90 = await client.get(f"/v1/ops/shops/{shop.id}/simulation?window=90")
        assert w90.json()["status"]["baseline_available"] is False
        assert (
            await client.get(f"/v1/ops/shops/{shop.id}/simulation?window=60")
        ).status_code == 422
        computed = await client.post(
            f"/v1/ops/shops/{shop.id}/simulation/compute",
            json={"window": 30, "deltas": {"product_card": {"ctor": 10}}},
        )
        assert computed.json()["result"]["streams"]["product_card"]["delta_pct"] == pytest.approx(
            10
        )
        locked = await client.post(
            f"/v1/ops/shops/{shop.id}/simulation/compute",
            json={"deltas": {"seller_live": {"aov": 5}}},
        )
        assert locked.status_code == 422
        a = await client.post(
            f"/v1/ops/shops/{shop.id}/scenarios",
            json={"name": "Mục tiêu Q4", "deltas": {"product_card": {"ctr": 5}}, "is_target": True},
        )
        b = await client.post(
            f"/v1/ops/shops/{shop.id}/scenarios",
            json={"name": "B", "deltas": {"seller_live": {"ctr": 5}}},
        )
        assert a.status_code == 201 and b.status_code == 201
        target = await client.patch(
            f"/v1/ops/shops/{shop.id}/scenarios/{b.json()['data']['id']}", json={"is_target": True}
        )
        assert target.json()["data"]["is_target"] is True
        listed = await client.get(f"/v1/ops/shops/{shop.id}/simulation?window=30")
        flags = {s["name"]: s["is_target"] for s in listed.json()["scenarios"]}
        assert flags == {"Mục tiêu Q4": False, "B": True}
        assert listed.json()["scenarios"][0]["result"]["delta_pct"] is not None
        deleted = await client.delete(f"/v1/ops/shops/{shop.id}/scenarios/{a.json()['data']['id']}")
        assert deleted.status_code == 204
    assert (
        await session.execute(select(func.count()).select_from(OpsSimScenario))
    ).scalar_one() == 1
    assert await _audit_count(session, "scenario_set_target") == 1


# -- invite / handover (P9-B) -----------------------------------------------------------------


async def test_invite_and_accept_moves_the_shop_and_keeps_ops_access(session, fake_mailer):
    team_owner, shop = await make_tenant(session)
    team_owner.email = "ops@app-juli.com"
    run = await make_workflow_run(session, shop)
    staff_user = await _staff(session, "operator")
    async with _client_as(session, staff_user) as client:
        created = await client.post(
            f"/v1/ops/shops/{shop.id}/invites",
            json={"email": "ThaoNhi@Gmail.com", "keep_ops_access": True},
        )
    assert created.status_code == 201
    assert created.json()["email_sent"] is True
    mail = fake_mailer.sent[0]
    assert mail.to == "thaonhi@gmail.com"
    token = mail.accept_url.split("token=")[1]
    shop_id, run_id = shop.id, run.id

    stranger = await make_user(session, email="other@gmail.com")
    async with _client_as(session, stranger) as client:
        wrong = await client.post(
            "/v1/shop-invites/accept", json={"token": token, "keep_ops_access": True}
        )
    assert wrong.status_code == 403

    seller = await make_user(session, email="thaonhi@gmail.com")
    seller_id = seller.id
    async with _client_as(session, seller) as client:
        preview = await client.get(f"/v1/shop-invites/preview?token={token}")
        assert preview.json()["data"]["keep_ops_access_asked"] is True
        accepted = await client.post(
            "/v1/shop-invites/accept", json={"token": token, "keep_ops_access": True}
        )
        assert accepted.status_code == 200
        again = await client.post("/v1/shop-invites/accept", json={"token": token})
        assert again.status_code == 409
    from juli_backend.models.models import WorkflowRun

    owner_id = (await session.execute(select(Shop.user_id).where(Shop.id == shop_id))).scalar_one()
    assert owner_id == seller_id
    run_shop = (
        await session.execute(select(WorkflowRun.shop_id).where(WorkflowRun.id == run_id))
    ).scalar_one()
    assert run_shop == shop_id  # history kept
    from juli_backend.models.ops import OpsShopInvite

    invite = (await session.execute(select(OpsShopInvite))).scalars().one()
    assert invite.seller_kept_ops_access is True
    assert await _audit_count(session, "invite_create") == 1
    assert await _audit_count(session, "invite_accept") == 1


async def test_seller_can_decline_ops_access_and_expired_invite_fails(session, fake_mailer):
    _, shop = await make_tenant(session)
    fake_mailer.ok = False
    staff_user = await _staff(session, "operator")
    async with _client_as(session, staff_user) as client:
        created = await client.post(
            f"/v1/ops/shops/{shop.id}/invites",
            json={"email": "s@gmail.com", "keep_ops_access": True},
        )
    assert created.json()["email_sent"] is False
    token = created.json()["accept_url"].split("token=")[1]
    seller = await make_user(session, email="s@gmail.com")
    async with _client_as(session, seller) as client:
        ok = await client.post(
            "/v1/shop-invites/accept", json={"token": token, "keep_ops_access": False}
        )
    assert ok.json()["data"]["kept_ops_access"] is False

    async with _client_as(session, staff_user) as client:
        second = await client.post(
            f"/v1/ops/shops/{shop.id}/invites", json={"email": "s@gmail.com"}
        )
    token2 = second.json()["accept_url"].split("token=")[1]
    from juli_backend.models.ops import OpsShopInvite

    row = (
        (await session.execute(select(OpsShopInvite).where(OpsShopInvite.accepted_at.is_(None))))
        .scalars()
        .one()
    )
    row.expires_at = datetime(2020, 1, 1)
    await session.flush()
    async with _client_as(session, seller) as client:
        expired = await client.post("/v1/shop-invites/accept", json={"token": token2})
    assert expired.status_code == 410


# -- Quy tắc in Cài đặt shop (D25.14) ---------------------------------------------------


async def test_staff_set_the_sellers_rules_audited_and_the_seller_sees_them(session):
    owner, shop = await make_tenant(session)
    shop_id = shop.id
    viewer_user = await _staff(session, "viewer")
    async with _client_as(session, viewer_user) as client:
        refused = await client.put(
            f"/v1/ops/shops/{shop_id}/rules/content_tone", json={"value": "x", "set_by": "team"}
        )
    assert refused.status_code == 403
    op = await _staff(session, "operator", "op.rules@app-juli.com")
    async with _client_as(session, op) as client:
        for key, value in (
            ("content_tone", "Thân thiện, xưng mình – bạn"),
            ("banned_terms", ["rẻ nhất", "số 1"]),
            ("max_open_cards", 12),
            ("target_roas", 6),
        ):
            put = await client.put(
                f"/v1/ops/shops/{shop_id}/rules/{key}", json={"value": value, "set_by": "seller"}
            )
            assert put.status_code == 200, put.text
            assert put.json()["data"]["set_by"] == "team"
        bad = await client.put(
            f"/v1/ops/shops/{shop_id}/rules/max_open_cards", json={"value": 40, "set_by": "team"}
        )
        assert bad.status_code == 422
        read = await client.get(f"/v1/ops/shops/{shop_id}/rules")
        assert read.json()["data"]["content_tone"]["value"] == "Thân thiện, xưng mình – bạn"
        gone = await client.delete(f"/v1/ops/shops/{shop_id}/rules/target_roas")
        assert gone.status_code == 204
    entries = (
        (await session.execute(select(OpsAuditLog).where(OpsAuditLog.shop_id == shop_id)))
        .scalars()
        .all()
    )
    actions = sorted(e.action for e in entries)
    assert actions == ["rule_set"] * 4 + ["rule_unset"]
    tone = next(
        e for e in entries if e.action == "rule_set" and e.after["rule_key"] == "content_tone"
    )
    assert tone.before["rule"] is None and tone.actor_email == "op.rules@app-juli.com"
    # the seller's own Quy tắc page reads the same rows and can keep editing them
    from tests.support.api import authenticated_client

    seller_shop = await session.get(Shop, shop_id)
    async with authenticated_client(session, user=owner, shop=seller_shop) as client:
        mine = (await client.get("/v1/demo/rules")).json()["data"]
        assert mine["banned_terms"]["value"] == ["rẻ nhất", "số 1"]
        assert mine["max_open_cards"]["set_by"] == "team"
        assert mine["target_roas"] is None
        edit = await client.put(
            "/v1/demo/rules/content_tone", json={"value": "Lịch sự", "set_by": "seller"}
        )
        assert edit.status_code == 200
