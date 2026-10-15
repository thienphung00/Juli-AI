"""P33-F (D43, AC-33.11) on real Postgres: ``trial_signups`` is ops-only.

- RLS on, the only policy ``TO juli_ops``; ``juli_app``, ``anon`` and
  ``authenticated`` hold no privilege on it;
- a ``juli_app`` session -- under tenant A's scope, tenant B's, or none --
  cannot SELECT / INSERT / UPDATE / DELETE it;
- the real app, running as ``juli_app``: the public ``POST /v1/trial-signups``
  stores the row through ``SET LOCAL ROLE juli_ops`` and is back to ``juli_app``
  afterwards; the Ops list and status change work for a Vận hành staff member
  and write one audit row; a Xem staff member is refused.
"""

from __future__ import annotations

import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from juli_backend.api.routes.ops import get_ops_user
from juli_backend.database import get_session
from juli_backend.services.ops import mailer as ops_mailer
from juli_backend.services.ops import staff as ops_staff
from tests.integration.two_tenant import RUNTIME_ROLE, juli_app_session

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

TABLE = "public.trial_signups"
BODY = {
    "full_name": "Trần Văn Bình",
    "phone": "0987 654 321",
    "email": "binh.tran@example.vn",
    "shop": "binhshop.official",
    "role": "agency",
    "consent": True,
}


class FakeMailer:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_invite(self, mail):  # pragma: no cover
        return False

    async def send_notice(self, *, to: str, subject: str, body: str) -> bool:
        self.sent.append(to)
        return True


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("TRIAL_SIGNUP_NOTIFY_TO", "sales@app-juli.com")
    fake = FakeMailer()
    ops_mailer.set_mailer(fake)
    yield fake
    ops_mailer.set_mailer(None)


def test_table_is_ops_only(owner_engine):
    with owner_engine.connect() as conn:
        rls = conn.execute(
            text("SELECT relrowsecurity FROM pg_class WHERE relname = 'trial_signups'")
        ).scalar_one()
        assert rls is True
        policies = conn.execute(
            text(
                "SELECT policyname, roles::text FROM pg_policies "
                "WHERE schemaname = 'public' AND tablename = 'trial_signups'"
            )
        ).all()
        assert [(p, r) for p, r in policies] == [("trial_signups_ops_only", "{juli_ops}")]
        for role in (RUNTIME_ROLE, "anon", "authenticated"):
            for verb in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                allowed = conn.execute(
                    text("SELECT has_table_privilege(:r, :t, :v)"),
                    {"r": role, "t": TABLE, "v": verb},
                ).scalar_one()
                assert allowed is False, (role, verb)
        for verb in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert conn.execute(
                text("SELECT has_table_privilege('juli_ops', :t, :v)"), {"t": TABLE, "v": verb}
            ).scalar_one(), verb


@pytest.mark.parametrize(
    "statement",
    [
        f"SELECT * FROM {TABLE}",  # nosec B608 - fixed test constant
        f"INSERT INTO {TABLE} (id, full_name, phone, email, shop, role, consent_at) "  # nosec B608
        "VALUES (gen_random_uuid(), 'x', '0912345678', 'x@example.vn', 's', 'seller', now())",
        f"UPDATE {TABLE} SET status = 'spam'",  # nosec B608
        f"DELETE FROM {TABLE}",  # nosec B608
    ],
)
@pytest.mark.parametrize("scope", ["a", "b", None])
async def test_juli_app_cannot_touch_trial_signups(two_tenants, statement, scope):
    tenant_a, tenant_b = two_tenants
    shop_id = {"a": tenant_a.shop_id, "b": tenant_b.shop_id, None: None}[scope]
    async with juli_app_session(shop_id) as session:
        with pytest.raises(Exception, match="permission denied"):
            await session.execute(text(statement))
        await session.rollback()


def _app(session):
    from juli_backend.api.app import create_app

    app = create_app()

    async def _session():
        yield session

    app.dependency_overrides[get_session] = _session
    return app


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_public_post_and_ops_flow_as_juli_app(owner_engine, two_tenants, env):
    tenant_a, _ = two_tenants
    marker = uuid.uuid4().hex[:8]
    body = {**BODY, "email": f"binh-{marker}@example.vn"}

    # 1. The public endpoint, the app's session being juli_app (no shop scope).
    async with juli_app_session() as session:
        async with _client(_app(session)) as client:
            response = await client.post("/v1/trial-signups", json=body)
        assert response.status_code == 201, response.text
        who = (await session.execute(text("SELECT current_user"))).scalar_one()
        assert who == RUNTIME_ROLE  # the ops block restored the role
    assert env.sent == ["sales@app-juli.com"]
    with owner_engine.connect() as conn:
        row = conn.execute(
            text(f"SELECT id, phone, status, ip_hash FROM {TABLE} WHERE email = :e"),  # nosec B608
            {"e": body["email"]},
        ).one()
    signup_id, phone, status, ip_hash = row
    assert phone == "0987654321" and status == "new" and ip_hash is not None

    # 2. Staff: one Vận hành, one Xem (seeded as the owner, set-up only).
    ids = {}
    with owner_engine.begin() as conn:
        for role in ("operator", "viewer"):
            user_id = uuid.uuid4()
            email = f"{role}-{marker}@app-juli.com"
            conn.execute(
                text(
                    "INSERT INTO public.ops_staff (id, email, role, user_id, active) "
                    "VALUES (gen_random_uuid(), :e, :r, :u, true)"
                ),
                {"e": email, "r": role, "u": user_id},
            )
            ids[role] = ops_staff.OpsUser(id=user_id, email=email)

    for role, list_code in (("viewer", 403), ("operator", 200)):
        async with juli_app_session(tenant_a.shop_id) as session:
            app = _app(session)
            app.dependency_overrides[get_ops_user] = lambda r=role: ids[r]
            async with _client(app) as client:
                listed = await client.get("/v1/ops/trial-signups?limit=1000")
                changed = await client.patch(
                    f"/v1/ops/trial-signups/{signup_id}", json={"status": "contacted"}
                )
        assert listed.status_code == list_code, (role, listed.text)
        assert changed.status_code == list_code, (role, changed.text)
    assert str(signup_id) in {r["id"] for r in listed.json()["data"]}
    assert changed.json()["data"]["handled_by"] == ids["operator"].email

    with owner_engine.connect() as conn:
        status, handled_by = conn.execute(
            text(f"SELECT status, handled_by FROM {TABLE} WHERE id = :i"),  # nosec B608
            {"i": signup_id},
        ).one()
        audits = conn.execute(
            text(
                "SELECT actor_email, before, after FROM public.ops_audit_log "
                "WHERE action = 'trial_signup_status' AND field = :f"
            ),
            {"f": f"trial_signup:{signup_id}"},
        ).all()
    assert (status, handled_by) == ("contacted", ids["operator"].email)
    assert [(a, b, c) for a, b, c in audits] == [
        (ids["operator"].email, {"status": "new"}, {"status": "contacted"})
    ]
