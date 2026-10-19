"""P20 system OpenAI limit + per-shop caps (DECISIONS D28.3, tab Chi phí), SQLite.

- the system cap (default env, stored value), the month's all-shop spend
- the gate: content analysis / drafting / agent runs refuse ``system_cap_reached``;
  cards keep being emitted
- the 80 % e-mail: once per month, to active Admins only; unsent without SMTP
- ``GET /v1/ops/costs``, ``PUT /v1/ops/costs/system-cap``,
  ``PUT /v1/ops/shops/{id}/openai-cap``: roles, audit rows, the shared shop_rules row
"""

from __future__ import annotations

import importlib
import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from sqlalchemy import select

from juli_backend.api.routes.ops import get_ops_user
from juli_backend.core.security import get_current_user
from juli_backend.models.content_analysis import ContentAnalysis
from juli_backend.models.models import Shop, User
from juli_backend.models.ops import OpsAuditLog, OpsStaff, OpsSystemSetting
from juli_backend.services.ops import system_cap
from juli_backend.services.shop_rules import openai_cap
from tests.support.api import build_app, client_for
from tests.support.builders import make_tenant, make_user, make_workflow_run

#: 12/10/2026 09:00 in Vietnam.
NOW = datetime(2026, 10, 12, 2, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def bypass_access(monkeypatch):
    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv(system_cap.DEFAULT_ENV, raising=False)
    monkeypatch.delenv(openai_cap.DEFAULT_CAP_ENV, raising=False)


async def _staff(session, role: str, *, active: bool = True, email: str | None = None) -> User:
    email = email or f"{role}-{uuid.uuid4().hex[:6]}@app-juli.com"
    user = await make_user(session, email=email)
    session.add(OpsStaff(id=uuid.uuid4(), email=email, role=role, active=active))
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


async def _spend(session, shop: Shop, usd: str, *, at: datetime | None = None, analysis=False):
    created = (at or datetime.now(UTC)).replace(tzinfo=None)
    if analysis:
        session.add(
            ContentAnalysis(
                shop_id=shop.id,
                kind="video",
                content_ref=f"video:{uuid.uuid4().hex[:6]}",
                status="done",
                file_name="a.mp4",
                content_type="video/mp4",
                size_bytes=1,
                upload_expires_at=created,
                cost_usd=Decimal(usd),
                attempts=1,
                created_at=created,
            )
        )
        await session.flush()
        return
    await make_workflow_run(
        session, shop, status="completed", cost_usd=Decimal(usd), created_at=created
    )


async def _set_cap(session, usd: int) -> None:
    session.add(OpsSystemSetting(key=system_cap.SYSTEM_CAP_KEY, value=usd))
    await session.flush()


# -- cap and spend ---------------------------------------------------------------------------


async def test_default_cap_is_50_or_the_env(session, monkeypatch):
    cap = await system_cap.system_cap(session)
    assert cap.usd == Decimal("50") and cap.is_default
    monkeypatch.setenv(system_cap.DEFAULT_ENV, "80")
    assert (await system_cap.system_cap(session)).usd == Decimal("80")
    await _set_cap(session, 120)
    stored = await system_cap.system_cap(session)
    assert stored.usd == Decimal("120") and not stored.is_default


async def test_spend_is_every_shop_this_utc7_month(session):
    _, a = await make_tenant(session)
    _, b = await make_tenant(session)
    await _spend(session, a, "3.25")
    await _spend(session, b, "1.75", analysis=True)
    # Last month (before the UTC+7 month start) does not count.
    await _spend(session, a, "9", at=openai_cap.month_start_utc() - timedelta(seconds=1))
    status = await system_cap.system_status(session)
    assert status.used_usd == Decimal("5.00")
    assert status.cap.usd == Decimal("50") and status.pct == Decimal("0.1")
    assert status.level is None and not status.reached


@pytest.mark.parametrize(
    ("used", "level", "reached"),
    [("39.99", None, False), ("40", 80, False), ("50", 100, True), ("70", 100, True)],
)
async def test_levels(session, used, level, reached):
    _, shop = await make_tenant(session)
    await _spend(session, shop, used)
    status = await system_cap.system_status(session)
    assert status.level == level and status.reached is reached


def test_month_label_follows_the_shop_month():
    assert system_cap.month_label(datetime(2026, 10, 31, 17, 0, tzinfo=UTC)) == "2026-11"
    assert system_cap.month_label(datetime(2026, 10, 31, 16, 59, tzinfo=UTC)) == "2026-10"


# -- the gate (≥ 100 %) ------------------------------------------------------------------------


async def _over_system_cap(session) -> Shop:
    _, big = await make_tenant(session)
    _, small = await make_tenant(session)
    await _set_cap(session, 30)
    await _spend(session, big, "30")
    return small  # its own spend is $0, far under its $5 cap


async def test_content_analysis_refuses_system_cap_reached(session):
    from juli_backend.services.content_analysis import costs

    shop = await _over_system_cap(session)
    with pytest.raises(costs.CostCapExceeded) as caught:
        await costs.check(session, shop.id)
    assert caught.value.code == "system_cap_reached"
    assert caught.value.message_vi == system_cap.SELLER_PAUSED_VI
    # Under the system cap the shop's own cap still applies (code unchanged).
    await _set_cap_value(session, 200)
    await costs.check(session, shop.id)


async def _set_cap_value(session, usd: int) -> None:
    row = await session.get(OpsSystemSetting, system_cap.SYSTEM_CAP_KEY)
    assert row is not None
    row.value = usd
    await session.flush()


async def test_drafting_refuses_with_the_seller_pause_text(session):
    from juli_backend.services.content_cards.driver import draft_gate_for

    shop = await _over_system_cap(session)
    gate = await draft_gate_for(session, shop.id)
    assert gate.system_cap_reached and not gate.cap_reached
    refusal = gate.refusal()
    assert refusal is not None
    code, event, text = refusal
    assert code == "system_cap_reached" and event == "ops_openai_system_cap_reached"
    assert text == (
        "Juli tạm dừng soạn nội dung mới. Thẻ đề xuất và các bước bạn tự làm vẫn dùng bình thường."
    )


async def test_agent_run_refuses_system_cap_reached(session, caplog):
    from juli_backend.services.agent.llm.openai_adapter import LLMProviderError
    from juli_backend.services.ops import overrides as ov

    shop = await _over_system_cap(session)

    class Inner:
        calls = 0

        async def complete(self, **kwargs):
            Inner.calls += 1

    guarded = await ov.cap_guarded(session, shop.id, Inner())
    with caplog.at_level(logging.WARNING), pytest.raises(LLMProviderError, match="system_cap"):
        await guarded.complete(messages=[])
    assert Inner.calls == 0
    assert any(r.message == "ops_openai_system_cap_reached" for r in caplog.records)


async def test_cards_are_still_emitted_over_the_system_cap(session, monkeypatch):
    """Emission has no OpenAI gate: it goes past the term check into planning."""
    from juli_backend.services.action_cards import persist

    shop = await _over_system_cap(session)

    class _Planned(Exception):
        pass

    async def _sentinel(*args, **kwargs):
        raise _Planned

    monkeypatch.setattr(persist, "_plan_optimize_product", _sentinel)

    class _Signals:
        computed_at = NOW

    class _Result:
        signals = _Signals()

    with pytest.raises(_Planned):
        await persist.emit_scoring_cards(session, shop.id, cast(Any, _Result()))


# -- the 80 % e-mail ----------------------------------------------------------------------------


class FakeMailer:
    configured = True

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send_notice(self, *, to: str, subject: str, body: str) -> bool:
        self.sent.append((to, subject, body))
        return True


async def test_alert_goes_once_a_month_to_active_admins(session):
    _, shop = await make_tenant(session)
    await _staff(session, "admin", email="boss@app-juli.com")
    await _staff(session, "admin", active=False, email="gone@app-juli.com")
    await _staff(session, "operator", email="op@app-juli.com")
    mailer = FakeMailer()
    await _spend(session, shop, "39")
    assert await system_cap.check_alert(session, mailer=mailer) is False  # 78 %
    await _spend(session, shop, "2")
    assert await system_cap.check_alert(session, mailer=mailer) is True  # 82 %
    assert [to for to, _, _ in mailer.sent] == ["boss@app-juli.com"]
    assert "82 %" in mailer.sent[0][1]
    await _spend(session, shop, "20")  # 122 %: still the same month -> no second e-mail
    assert await system_cap.check_alert(session, mailer=mailer) is False
    assert len(mailer.sent) == 1
    marker = await session.get(OpsSystemSetting, system_cap.ALERT_KEY)
    assert marker is not None and marker.value == {
        "month": system_cap.month_label(),
        "level": 80,
    }
    audit_rows = (
        (
            await session.execute(
                select(OpsAuditLog).where(OpsAuditLog.action == "system_openai_alert_sent")
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1 and audit_rows[0].actor_email == "system"


async def test_a_new_month_alerts_again(session):
    _, shop = await make_tenant(session)
    await _staff(session, "admin")
    session.add(
        OpsSystemSetting(key=system_cap.ALERT_KEY, value={"month": "2026-09", "level": 100})
    )
    await _spend(session, shop, "45")
    mailer = FakeMailer()
    assert await system_cap.check_alert(session, mailer=mailer) is True
    assert len(mailer.sent) == 1


async def test_without_smtp_the_alert_is_logged_unsent_and_not_marked(session, caplog):
    _, shop = await make_tenant(session)
    await _staff(session, "admin")
    await _spend(session, shop, "45")

    class NoSmtp(FakeMailer):
        configured = False

    mailer = NoSmtp()
    with caplog.at_level(logging.WARNING):
        assert await system_cap.check_alert(session, mailer=mailer) is False
    assert mailer.sent == []
    assert any(r.message == "openai_system_alert_unsent" for r in caplog.records)
    assert await session.get(OpsSystemSetting, system_cap.ALERT_KEY) is None


async def test_the_alert_task_is_scheduled_hourly():
    importlib.import_module("juli_backend.workers.tasks")  # registers the tasks
    from juli_backend.workers.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["ops-openai-system-alert"]
    assert entry["task"] == "juli_backend.ops_openai_system_alert"
    assert "juli_backend.ops_openai_system_alert" in celery_app.tasks
    assert entry["schedule"].minute == {19}


async def test_the_alert_task_body_commits(engine, session):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from juli_backend.workers.tasks.ops_openai_alert import run_ops_openai_alert

    _, shop = await make_tenant(session)
    await _staff(session, "admin")
    await _spend(session, shop, "45")
    await session.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    mailer = FakeMailer()
    assert await run_ops_openai_alert(factory, mailer=mailer) is True
    assert await run_ops_openai_alert(factory, mailer=mailer) is False
    assert len(mailer.sent) == 1


# -- Ops routes ---------------------------------------------------------------------------------


async def test_costs_page_lists_system_and_shops(session):
    viewer = await _staff(session, "viewer")
    _, a = await make_tenant(session, shop_name="Fujiwa Vietnam Store")
    _, b = await make_tenant(session, shop_name="Gốm Hà Nam")
    await openai_cap.set_openai_monthly_cap(session, a.id, 10, set_by_user_id=None)
    await _spend(session, a, "12")
    await _spend(session, b, "1")
    async with _client_as(session, viewer) as client:
        response = await client.get("/v1/ops/costs")
    assert response.status_code == 200
    body = response.json()
    assert body["system"]["used_usd"] == pytest.approx(13.0)
    assert body["system"]["cap_usd"] == 50.0 and body["system"]["cap_is_default"] is True
    assert body["system"]["level"] is None
    assert body["warn_pct"] == 0.8 and body["default_shop_cap_usd"] == 5.0
    assert body["seller_paused_text"] == system_cap.SELLER_PAUSED_VI
    rows = {r["shop_name"]: r for r in body["shops"]}
    assert rows["Fujiwa Vietnam Store"] == {
        **rows["Fujiwa Vietnam Store"],
        "used_usd": 12.0,
        "cap_usd": 10.0,
        "is_custom": True,
        "state": "shop_cap",
    }
    assert rows["Gốm Hà Nam"]["is_custom"] is False and rows["Gốm Hà Nam"]["state"] == "ok"
    assert 1 <= body["days_left_in_month"] <= 31


async def test_costs_page_marks_every_shop_when_the_system_cap_is_reached(session):
    viewer = await _staff(session, "viewer")
    await _over_system_cap(session)
    async with _client_as(session, viewer) as client:
        body = (await client.get("/v1/ops/costs")).json()
        banner = (await client.get("/v1/ops/costs/system")).json()
    assert body["system"]["reached"] is True and body["system"]["level"] == 100
    assert {r["state"] for r in body["shops"]} == {"system_cap"}
    assert banner["system"]["level"] == 100 and banner["system"]["alert_sent"] is False
    assert "shops" not in banner


async def test_banner_says_when_the_alert_went_out(session):
    viewer = await _staff(session, "viewer")
    _, shop = await make_tenant(session)
    await _spend(session, shop, "42")
    session.add(
        OpsSystemSetting(
            key=system_cap.ALERT_KEY, value={"month": system_cap.month_label(), "level": 80}
        )
    )
    await session.flush()
    async with _client_as(session, viewer) as client:
        banner = (await client.get("/v1/ops/costs/system")).json()["system"]
    assert banner["level"] == 80 and banner["alert_sent"] is True
    assert banner["pct"] == pytest.approx(0.84)


@pytest.mark.parametrize("role", ["viewer", "operator"])
async def test_cap_writes_are_admin_only(session, role):
    staff = await _staff(session, role)
    _, shop = await make_tenant(session)
    async with _client_as(session, staff) as client:
        system = await client.put("/v1/ops/costs/system-cap", json={"usd": 80})
        per_shop = await client.put(f"/v1/ops/shops/{shop.id}/openai-cap", json={"usd": 20})
    assert system.status_code == 403 and per_shop.status_code == 403
    assert await session.get(OpsSystemSetting, system_cap.SYSTEM_CAP_KEY) is None


async def test_admin_sets_the_system_cap_with_one_audit_row(session):
    admin = await _staff(session, "admin")
    async with _client_as(session, admin) as client:
        response = await client.put("/v1/ops/costs/system-cap", json={"usd": 80})
        bad = await client.put("/v1/ops/costs/system-cap", json={"usd": 0})
    assert response.status_code == 200, response.text
    assert response.json()["system"]["cap_usd"] == 80.0
    assert response.json()["system"]["cap_is_default"] is False
    assert bad.status_code == 422
    cap = await system_cap.system_cap(session)
    assert cap.usd == Decimal("80") and cap.updated_by and cap.updated_by.endswith("@app-juli.com")
    rows = (
        (
            await session.execute(
                select(OpsAuditLog).where(OpsAuditLog.action == "openai_system_cap_set")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].before == {"openai_system_cap_usd": 50.0, "default": True}
    assert rows[0].after == {"openai_system_cap_usd": 80.0}
    assert rows[0].shop_id is None


async def test_admin_sets_a_shop_cap_through_the_shared_rules_row(session):
    admin = await _staff(session, "admin")
    _, shop = await make_tenant(session)
    shop_id = shop.id  # the 422 below rolls the shared session back
    async with _client_as(session, admin) as client:
        response = await client.put(f"/v1/ops/shops/{shop_id}/openai-cap", json={"usd": 20})
    assert response.status_code == 200, response.text
    assert response.json() == {"shop_id": str(shop.id), "cap_usd": 20.0, "is_custom": True}
    # P15 / P16 read the same shop_rules row.
    cap = await openai_cap.openai_monthly_cap_usd(session, shop.id)
    assert cap.usd == Decimal("20.00") and not cap.is_default
    rows = (
        (await session.execute(select(OpsAuditLog).where(OpsAuditLog.shop_id == shop.id)))
        .scalars()
        .all()
    )
    assert [(r.action, r.field) for r in rows] == [
        ("openai_shop_cap_set", "openai_monthly_cap_usd")
    ]
    assert rows[0].before == {"openai_monthly_cap_usd": None}
    assert rows[0].after == {"openai_monthly_cap_usd": 20.0}

    async with _client_as(session, admin) as client:
        back = await client.put(f"/v1/ops/shops/{shop_id}/openai-cap", json={"usd": None})
        bad = await client.put(f"/v1/ops/shops/{shop_id}/openai-cap", json={"usd": 5000})
    assert back.json() == {"shop_id": str(shop_id), "cap_usd": 5.0, "is_custom": False}
    assert bad.status_code == 422
    assert (await openai_cap.openai_monthly_cap_usd(session, shop_id)).is_default


async def test_shop_cap_for_unknown_shop_is_404(session):
    admin = await _staff(session, "admin")
    async with _client_as(session, admin) as client:
        response = await client.put(f"/v1/ops/shops/{uuid.uuid4()}/openai-cap", json={"usd": 10})
    assert response.status_code == 404
