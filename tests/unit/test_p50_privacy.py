"""P50-B privacy API (DECISIONS D68, contract ``fasttrack/contracts/p50-privacy.md``), SQLite.

- ``GET`` / ``PATCH /v1/me/privacy`` (unknown key → 422)
- ``POST /v1/me/consents`` (409 stale date, 422 liability not accepted, 200)
- ``GET /v1/me/export`` (headers, own shops only, no tokens / secrets / staff rows)
- ``POST`` / ``DELETE /v1/me/deletion`` (+30 days, idempotent, cancel)
- a pending deletion makes the seller's shops read-only and stops shop sync
- the nightly purge task (selection, per-account isolation, counts-only log)
- migration 094 shape (grants, functions, re-parented deferred step)
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import Depends

from juli_backend.api.dependencies import require_writable_shop
from juli_backend.core.security import get_current_user
from juli_backend.models.models import Shop, User
from juli_backend.services import privacy
from juli_backend.services.privacy.terms import LEGAL_TERMS_DATE
from juli_backend.workers.services.polling.ingestion import enumerate_pollable_shops
from tests.support.api import build_app, client_for
from tests.support.builders import make_credential, make_product, make_tenant

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "backend/src/juli_backend/database/migrations"
MIGRATION = MIGRATIONS / "versions/094_user_privacy_and_consent.py"
DEFERRED = MIGRATIONS / "deferred/074_users_placeholder_phone_cleanup.py"


def _client_as(session, user: User):
    app = build_app(session)

    async def current() -> User:
        await session.refresh(user)
        return user

    app.dependency_overrides[get_current_user] = current
    return client_for(app)


def test_the_legal_terms_date_is_pinned():
    """Bumped together with ``apps/demo/src/lib/privacy/legal.ts`` (contract §Current)."""
    assert LEGAL_TERMS_DATE == date(2026, 10, 18)


# -- GET / PATCH /v1/me/privacy -----------------------------------------------------------


async def test_get_privacy_defaults(session):
    user, _ = await make_tenant(session)
    async with _client_as(session, user) as client:
        resp = await client.get("/v1/me/privacy")
    assert resp.status_code == 200
    assert resp.json() == {
        "marketing_opt_out": False,
        "ad_measurement_opt_out": False,
        "case_study_opt_in": False,
        "terms_date_accepted": None,
        "terms_accepted_at": None,
        "liability_clause_accepted_at": None,
        "current_terms_date": "2026-10-18",
        "needs_terms_acceptance": True,
        "deletion_scheduled_for": None,
    }


async def test_patch_privacy_changes_only_the_given_keys(session):
    user, _ = await make_tenant(session)
    async with _client_as(session, user) as client:
        resp = await client.patch("/v1/me/privacy", json={"ad_measurement_opt_out": True})
        assert resp.status_code == 200
        assert resp.json()["ad_measurement_opt_out"] is True
        assert resp.json()["marketing_opt_out"] is False
        resp = await client.patch(
            "/v1/me/privacy", json={"marketing_opt_out": True, "case_study_opt_in": True}
        )
        body = (await client.get("/v1/me/privacy")).json()
    assert resp.status_code == 200
    assert body["marketing_opt_out"] is True
    assert body["case_study_opt_in"] is True
    assert body["ad_measurement_opt_out"] is True


@pytest.mark.parametrize(
    "payload",
    [
        {"deletion_scheduled_for": None},
        {"marketing_opt_out": True, "email": "x@example.com"},
        {"terms_date_accepted": "2026-10-18"},
        {"marketing_opt_out": "yes"},
        {"marketing_opt_out": None},
    ],
)
async def test_patch_privacy_refuses_unknown_or_bad_keys(session, payload):
    user, _ = await make_tenant(session)
    async with _client_as(session, user) as client:
        resp = await client.patch("/v1/me/privacy", json=payload)
        body = (await client.get("/v1/me/privacy")).json()
    assert resp.status_code == 422
    assert body["marketing_opt_out"] is False


async def test_privacy_is_scoped_to_the_caller(session):
    user_a, _ = await make_tenant(session)
    user_b, _ = await make_tenant(session)
    async with _client_as(session, user_a) as client:
        await client.patch("/v1/me/privacy", json={"marketing_opt_out": True})
    async with _client_as(session, user_b) as client:
        body = (await client.get("/v1/me/privacy")).json()
    assert body["marketing_opt_out"] is False


# -- POST /v1/me/consents -----------------------------------------------------------------


async def test_consent_with_a_stale_terms_date_is_409(session):
    user, _ = await make_tenant(session)
    async with _client_as(session, user) as client:
        resp = await client.post(
            "/v1/me/consents", json={"terms_date": "2026-10-01", "liability_clause": True}
        )
        body = (await client.get("/v1/me/privacy")).json()
    assert resp.status_code == 409
    assert body["terms_date_accepted"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"terms_date": "2026-10-18", "liability_clause": False},
        {"terms_date": "2026-10-18"},
        {"terms_date": "2026-10-18", "liability_clause": True, "extra": 1},
    ],
)
async def test_consent_without_the_liability_clause_is_422(session, payload):
    user, _ = await make_tenant(session)
    async with _client_as(session, user) as client:
        resp = await client.post("/v1/me/consents", json=payload)
        body = (await client.get("/v1/me/privacy")).json()
    assert resp.status_code == 422
    assert body["liability_clause_accepted_at"] is None
    assert body["needs_terms_acceptance"] is True


async def test_consent_records_the_date_and_both_stamps(session):
    user, _ = await make_tenant(session)
    before = datetime.now(UTC) - timedelta(seconds=5)
    async with _client_as(session, user) as client:
        resp = await client.post(
            "/v1/me/consents", json={"terms_date": "2026-10-18", "liability_clause": True}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["terms_date_accepted"] == "2026-10-18"
    assert body["needs_terms_acceptance"] is False
    accepted = datetime.fromisoformat(body["terms_accepted_at"].replace("Z", "+00:00"))
    assert accepted >= before
    assert body["liability_clause_accepted_at"] == body["terms_accepted_at"]


# -- GET /v1/me/export --------------------------------------------------------------------


async def test_export_is_an_attachment_with_the_sellers_own_data(session):
    user, shop = await make_tenant(session, shop_name="Shop Của Tôi")
    user.email = "seller@example.com"
    await make_product(session, shop, title="Áo thun")
    await make_credential(session, shop)
    other_user, other_shop = await make_tenant(session, shop_name="Shop Người Khác")
    await make_product(session, other_shop, title="Không phải của tôi")
    await session.flush()

    async with _client_as(session, user) as client:
        resp = await client.get("/v1/me/export")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    disposition = resp.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="juli-du-lieu-')
    assert disposition.endswith('.json"')
    body = resp.json()
    assert body["account"]["id"] == str(user.id)
    assert body["account"]["email"] == "seller@example.com"
    assert body["privacy"]["current_terms_date"] == "2026-10-18"
    assert [s["name"] for s in body["shops"]] == ["Shop Của Tôi"]
    assert body["shops"][0]["platform"] == "tiktok"
    assert body["shops"][0]["connected_at"]
    titles = [p["title"] for p in body["shops"][0]["data"]["products"]["rows"]]
    assert titles == ["Áo thun"]
    raw = resp.text
    assert "Không phải của tôi" not in raw
    assert str(other_user.id) not in raw
    # No credential, staff, audit or Ops row: tokens, secrets and staff e-mails never appear.
    for forbidden in ("access-token", "refresh-token", "access_token", "secret", "audit", "ops_"):
        assert forbidden not in raw.lower(), forbidden
    assert "credentials" not in raw and "actor_email" not in raw


# -- POST / DELETE /v1/me/deletion --------------------------------------------------------


async def test_deletion_request_is_thirty_days_out_and_idempotent(session):
    user, _ = await make_tenant(session)
    before = datetime.now(UTC)
    async with _client_as(session, user) as client:
        first = await client.post("/v1/me/deletion")
        second = await client.post("/v1/me/deletion")
    assert first.status_code == 200 and second.status_code == 200
    scheduled = first.json()["deletion_scheduled_for"]
    assert second.json()["deletion_scheduled_for"] == scheduled
    when = datetime.fromisoformat(scheduled.replace("Z", "+00:00"))
    assert (
        timedelta(days=30) - timedelta(seconds=5) <= when - before <= timedelta(days=30, seconds=5)
    )


async def test_deletion_cancel_clears_the_date_and_is_idempotent(session):
    user, _ = await make_tenant(session)
    async with _client_as(session, user) as client:
        await client.post("/v1/me/deletion")
        resp = await client.delete("/v1/me/deletion")
        again = await client.delete("/v1/me/deletion")
    assert resp.status_code == 200 and again.status_code == 200
    assert resp.json()["deletion_scheduled_for"] is None


async def test_a_pending_deletion_makes_the_sellers_shops_read_only(session):
    user, shop = await make_tenant(session)
    app = build_app(session)

    async def current() -> User:
        await session.refresh(user)
        return user

    app.dependency_overrides[get_current_user] = current

    @app.post("/__probe_write")
    async def probe(_shop: Shop = Depends(require_writable_shop)) -> dict:
        return {"ok": True}

    headers = {"X-Shop-Id": str(shop.id)}
    async with client_for(app) as client:
        assert (await client.post("/__probe_write", headers=headers)).status_code == 200
        await client.post("/v1/me/deletion")
        refused = await client.post("/__probe_write", headers=headers)
        assert (await client.get("/v1/me/export")).status_code == 200
        await client.delete("/v1/me/deletion")
        allowed = await client.post("/__probe_write", headers=headers)
    assert refused.status_code == 403
    assert allowed.status_code == 200


# -- shop sync stops ----------------------------------------------------------------------


async def test_shop_sync_skips_shops_whose_owner_has_a_pending_deletion(session):
    keep_user, keep_shop = await make_tenant(session)
    gone_user, gone_shop = await make_tenant(session)
    for shop in (keep_shop, gone_shop):
        await make_credential(
            session,
            shop,
            capability="production_read",
            merchant_authorization_id=f"m-{shop.id.hex[:8]}",
            status="active",
        )
    await privacy.request_deletion(session, gone_user.id)
    await session.flush()

    listed = {s.shop_id for s in await enumerate_pollable_shops(session)}

    assert keep_shop.id in listed
    assert gone_shop.id not in listed
    await privacy.cancel_deletion(session, gone_user.id)
    await session.flush()
    assert gone_shop.id in {s.shop_id for s in await enumerate_pollable_shops(session)}


def test_the_postgres_enumeration_filters_pending_deletions():
    body = MIGRATION.read_text("utf-8")
    assert "CREATE OR REPLACE FUNCTION public.enumerate_pollable_shops(" in body
    assert "u.deletion_scheduled_for IS NOT NULL" in body


# -- the nightly purge task ---------------------------------------------------------------


class _FakeSession:
    def __init__(self, log: list[str]):
        self.log = log

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def commit(self):
        self.log.append("commit")

    async def rollback(self):
        self.log.append("rollback")


async def test_purge_task_purges_each_due_account_in_its_own_transaction(monkeypatch, caplog):
    from juli_backend.workers.tasks import privacy_account_purge as task

    ok_id, bad_id = uuid.uuid4(), uuid.uuid4()
    log: list[str] = []

    async def due(_session, *, now):
        return [ok_id, bad_id]

    async def purge(_session, user_id):
        if user_id == bad_id:
            raise RuntimeError("boom")
        log.append(f"purge:{user_id}")
        return privacy.PurgeCounts(shops=2, rows=40, kept_periods=1)

    monkeypatch.setattr(task, "due_account_ids", due)
    monkeypatch.setattr(task, "purge_account", purge)
    caplog.set_level(logging.INFO)

    summary = await task.run_privacy_account_purge(lambda: _FakeSession(log))

    assert summary == {
        "due": 2,
        "purged": 1,
        "failed": 1,
        "shops": 2,
        "rows": 40,
        "kept_periods": 1,
        "auth_users_pending": 1,
    }
    assert log == ["commit", f"purge:{ok_id}", "commit", "rollback"]
    text = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert str(ok_id) not in text and str(bad_id) not in text


def test_purge_task_is_scheduled_nightly():
    from juli_backend.workers.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["privacy-account-purge"]
    assert entry["task"] == "juli_backend.privacy_account_purge"


async def test_due_accounts_on_sqlite_selects_passed_dates_only(session):
    due_user, _ = await make_tenant(session)
    later_user, _ = await make_tenant(session)
    never_user, _ = await make_tenant(session)
    now = datetime(2026, 11, 20, tzinfo=UTC)
    due_user.deletion_scheduled_for = now - timedelta(minutes=1)
    later_user.deletion_scheduled_for = now + timedelta(days=1)
    await session.flush()

    ids = await privacy.due_account_ids(session, now=now)

    assert due_user.id in ids
    assert later_user.id not in ids and never_user.id not in ids


# -- migration 094 shape ------------------------------------------------------------------


def test_migration_grants_only_the_privacy_columns_and_ops_only_functions():
    body = MIGRATION.read_text("utf-8")
    assert 'down_revision: str | None = "093_ops_group_lift_draws"' in body
    assert "UPDATE ({columns}) ON public.users {preposition} {APP_ROLE}" in body
    for fn in ("privacy_due_accounts", "privacy_purge_account"):
        assert f"public.{fn}(" in body
    assert "SECURITY DEFINER" in body and "REVOKE ALL ON FUNCTION" in body
    assert "GRANT EXECUTE ON FUNCTION {fn} TO {OPS_ROLE}" in body
    assert "TO {APP_ROLE}'" not in body.replace("{preposition} {APP_ROLE}'", "")
    assert 'down_revision: str | None = "097_production_write_shops"' in DEFERRED.read_text("utf-8")


def test_migration_passes_the_additive_gate():
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "infra/scripts/migration_additive_gate.py"),
            "--migration-file",
            str(MIGRATION),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_export_json_is_serialisable_shape():
    """The export is plain JSON (no Decimal / datetime objects leak to the encoder)."""
    sample = privacy.export_json_default(datetime(2026, 10, 18, 3, tzinfo=UTC))
    assert sample == "2026-10-18T03:00:00Z"
    assert json.dumps({"d": privacy.export_json_default(date(2026, 10, 18))})
