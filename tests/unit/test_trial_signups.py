"""P33-F free-trial sign-ups (D43, AC-33.11), SQLite.

- validation (Vietnamese per-field messages, VN phone normalising, consent),
  the honeypot, and the per-IP / per-e-mail / site-wide rate limits;
- ``POST /v1/trial-signups`` stores exactly one row and sends one mail (fake
  mailer); no SMTP / no recipients still succeeds; no PII in any log line;
- the relay key: ``X-Juli-Client-Ip`` is trusted only with the right key;
- Ops ``GET/PATCH /v1/ops/trial-signups``: Vận hành+ only (Xem 403, no staff
  row 403, no Access 403), status changes audited, no-op writes nothing;
- migration 091 shape and the deferred tail.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from juli_backend.api.routes.ops import get_ops_user
from juli_backend.core.security import get_current_user
from juli_backend.database.tenant_scoped_tables import get_ops_only_tables
from juli_backend.models.models import User
from juli_backend.models.ops import OpsAuditLog, OpsStaff
from juli_backend.models.trial_signups import TrialSignup
from juli_backend.repositories._base import utc_now_naive
from juli_backend.services import trial_signups as signups
from juli_backend.services.ops import mailer as ops_mailer
from tests.support.api import build_app, client_for
from tests.support.builders import make_user

REPO = Path(__file__).resolve().parents[2]
MIGRATION = REPO / "backend/src/juli_backend/database/migrations/versions/091_trial_signups.py"
DEFERRED = (
    REPO
    / "backend/src/juli_backend/database/migrations/deferred/074_users_placeholder_phone_cleanup.py"
)

PHONE = "0912 345 678"
EMAIL = "Lan.Nguyen@Example.vn"
NAME = "Nguyễn Thị Lan"

VALID = {
    "full_name": NAME,
    "phone": PHONE,
    "email": EMAIL,
    "shop": "https://www.tiktok.com/@lanshop",
    "role": "seller",
    "note": "Shop mỹ phẩm, 300 đơn/ngày",
    "consent": True,
    "website": "",
    "source": {"utm_source": "tiktok", "utm_campaign": "q4", "referrer": "https://app-juli.com/"},
}


class FakeMailer:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.notices: list[dict[str, str]] = []

    async def send_invite(self, mail):  # pragma: no cover - not used here
        return False

    async def send_notice(self, *, to: str, subject: str, body: str) -> bool:
        self.notices.append({"to": to, "subject": subject, "body": body})
        return self.ok


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("TRIAL_SIGNUP_NOTIFY_TO", "sales@app-juli.com")
    monkeypatch.setenv("TRIAL_SIGNUP_IP_SALT", "unit-test-salt")
    monkeypatch.delenv("TRIAL_SIGNUP_RELAY_KEY", raising=False)


@pytest.fixture
def mailer():
    fake = FakeMailer()
    ops_mailer.set_mailer(fake)
    yield fake
    ops_mailer.set_mailer(None)


async def _count(session, model=TrialSignup) -> int:
    return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


def _public(session):
    return client_for(build_app(session))


# -- validation ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0912345678", "0912345678"),
        ("0912 345 678", "0912345678"),
        ("0912.345.678", "0912345678"),
        ("+84 912 345 678", "0912345678"),
        ("84912345678", "0912345678"),
        ("(+84) 386-123-456", "0386123456"),
        ("0123456789", None),  # old 11-digit era prefix / not a mobile
        ("091234567", None),  # too short
        ("09123456789", None),  # too long
        ("0212345678", None),  # landline prefix
        ("abc", None),
        ("", None),
    ],
)
def test_phone_normalising(raw, expected):
    assert signups.normalize_phone(raw) == expected


def test_valid_body_is_normalised():
    checked = signups.validate(VALID)
    assert checked.errors == {} and not checked.honeypot
    data = checked.data
    assert data is not None
    assert data.phone == "0912345678"
    assert data.email == "lan.nguyen@example.vn"
    assert data.role == "seller"
    assert data.source == {
        "utm_source": "tiktok",
        "utm_campaign": "q4",
        "referrer": "https://app-juli.com/",
    }


def test_every_field_has_a_vietnamese_message_and_values_are_not_echoed():
    bad = {
        "full_name": "A",
        "phone": "12345",
        "email": "not-an-email",
        "shop": "",
        "role": "hacker",
        "note": "x" * 1001,
        "consent": False,
    }
    checked = signups.validate(bad)
    assert checked.data is None
    assert set(checked.errors) == {"full_name", "phone", "email", "shop", "role", "note", "consent"}
    assert checked.errors["phone"] == signups.MSG_PHONE
    assert checked.errors["consent"] == signups.MSG_CONSENT
    joined = " ".join(checked.errors.values())
    assert "12345" not in joined and "not-an-email" not in joined


@pytest.mark.parametrize("consent", [True, "true", "on", "1"])
def test_consent_accepts_form_and_json_truthy(consent):
    assert signups.validate({**VALID, "consent": consent}).data is not None


def test_honeypot_short_circuits_validation():
    checked = signups.validate({"website": "http://spam.example"})
    assert checked.honeypot and checked.data is None and checked.errors == {}


def test_flat_utm_fields_are_read_and_unknown_keys_dropped():
    body = {**VALID, "source": None, "utm_source": "google", "gclid": "x", "utm_medium": " "}
    data = signups.validate(body).data
    assert data is not None and data.source == {"utm_source": "google"}


# -- client IP and relay key --------------------------------------------------------


def test_forwarded_ip_trusted_only_with_the_relay_key(monkeypatch):
    headers = {"x-juli-client-ip": "203.0.113.7", "x-juli-relay-key": "secret"}
    # no key configured: the header is ignored
    assert signups.client_ip(headers, "198.51.100.1") == "198.51.100.1"
    monkeypatch.setenv("TRIAL_SIGNUP_RELAY_KEY", "secret")
    assert signups.client_ip(headers, "198.51.100.1") == "203.0.113.7"
    assert signups.client_ip({**headers, "x-juli-relay-key": "wrong"}, "198.51.100.1") == (
        "198.51.100.1"
    )
    # a junk forwarded value falls back to the peer
    assert signups.client_ip({**headers, "x-juli-client-ip": "nope"}, "198.51.100.1") == (
        "198.51.100.1"
    )


def test_ip_hash_is_keyed_and_never_the_address(monkeypatch):
    digest = signups.ip_hash("203.0.113.7")
    assert digest is not None and len(digest) == 64 and "203.0.113.7" not in digest
    monkeypatch.setenv("TRIAL_SIGNUP_IP_SALT", "other")
    assert signups.ip_hash("203.0.113.7") != digest
    assert signups.ip_hash(None) is None


# -- the public endpoint ------------------------------------------------------------


async def test_post_stores_exactly_one_row_and_sends_one_mail(session, mailer):
    async with _public(session) as client:
        response = await client.post("/v1/trial-signups", json=VALID)
    assert response.status_code == 201
    assert response.json() == {"ok": True}
    assert response.headers["cache-control"] == "no-store"
    assert await _count(session) == 1
    row = (await session.execute(select(TrialSignup))).scalar_one()
    assert row.phone == "0912345678" and row.email == "lan.nguyen@example.vn"
    assert row.status == "new" and row.handled_by is None
    assert row.consent_at is not None
    assert row.ip_hash is not None and len(row.ip_hash) == 64
    assert row.source == VALID["source"]
    assert len(mailer.notices) == 1
    notice = mailer.notices[0]
    assert notice["to"] == "sales@app-juli.com"
    assert "0912345678" in notice["body"] and "lan.nguyen@example.vn" in notice["body"]
    assert "ops.app-juli.com/ops/dang-ky-dung-thu" in notice["body"]
    # the subject (visible in inbox lists / mail logs) carries no contact detail
    assert "0912345678" not in notice["subject"] and "@" not in notice["subject"]


async def test_one_mail_per_recipient(session, mailer, monkeypatch):
    monkeypatch.setenv("TRIAL_SIGNUP_NOTIFY_TO", "a@app-juli.com, b@app-juli.com")
    async with _public(session) as client:
        assert (await client.post("/v1/trial-signups", json=VALID)).status_code == 201
    assert [n["to"] for n in mailer.notices] == ["a@app-juli.com", "b@app-juli.com"]
    assert await _count(session) == 1


async def test_honeypot_answers_201_and_stores_nothing(session, mailer):
    async with _public(session) as client:
        response = await client.post("/v1/trial-signups", json={**VALID, "website": "x.com"})
    assert response.status_code == 201 and response.json() == {"ok": True}
    assert await _count(session) == 0
    assert mailer.notices == []


async def test_invalid_body_is_422_with_field_messages(session, mailer):
    async with _public(session) as client:
        response = await client.post(
            "/v1/trial-signups", json={**VALID, "phone": "123", "consent": False}
        )
        malformed = await client.post(
            "/v1/trial-signups", content=b"{nope", headers={"content-type": "application/json"}
        )
        listed = await client.post("/v1/trial-signups", json=[1, 2])
        huge = await client.post("/v1/trial-signups", json={**VALID, "note": "x" * 20000})
    assert response.status_code == 422
    assert response.json() == {
        "detail": "invalid",
        "errors": {"phone": signups.MSG_PHONE, "consent": signups.MSG_CONSENT},
    }
    assert malformed.status_code == 400 and listed.status_code == 400
    assert huge.status_code == 413
    assert await _count(session) == 0
    assert mailer.notices == []


async def test_rate_limit_per_ip(session, mailer):
    async with _public(session) as client:
        codes = [
            (
                await client.post(
                    "/v1/trial-signups", json={**VALID, "email": f"lan{i}@example.vn"}
                )
            ).status_code
            for i in range(signups.PER_IP_LIMIT + 1)
        ]
    assert codes == [201] * signups.PER_IP_LIMIT + [429]
    assert await _count(session) == signups.PER_IP_LIMIT
    assert len(mailer.notices) == signups.PER_IP_LIMIT


async def test_rate_limit_per_email_across_addresses(session, mailer, monkeypatch):
    monkeypatch.setenv("TRIAL_SIGNUP_RELAY_KEY", "k")
    async with _public(session) as client:
        codes = []
        for i in range(signups.PER_EMAIL_LIMIT + 1):
            response = await client.post(
                "/v1/trial-signups",
                json=VALID,
                headers={"x-juli-relay-key": "k", "x-juli-client-ip": f"203.0.113.{i + 1}"},
            )
            codes.append(response.status_code)
    assert codes == [201] * signups.PER_EMAIL_LIMIT + [429]
    body = response.json()
    assert body == {"detail": signups.MSG_RATE_LIMITED}
    assert await _count(session) == signups.PER_EMAIL_LIMIT
    hashes = (await session.execute(select(TrialSignup.ip_hash))).scalars().all()
    assert len(set(hashes)) == signups.PER_EMAIL_LIMIT  # one per forwarded address


async def test_rate_limit_windows_expire(session):
    data = signups.validate(VALID).data
    assert data is not None
    past = utc_now_naive() - timedelta(days=2)
    for _ in range(signups.PER_EMAIL_LIMIT):
        await signups.create_signup(session, data, ip_digest="a" * 64, now=past)
    await session.flush()
    # two days later both the IP and the e-mail windows are clear again
    await signups.create_signup(session, data, ip_digest="a" * 64)
    with pytest.raises(signups.RateLimited) as exc:
        await signups.create_signup(
            session, data, ip_digest="b" * 64, now=past + timedelta(minutes=1)
        )
    assert exc.value.scope == "email"


async def test_site_wide_limit(session, monkeypatch):
    monkeypatch.setattr(signups, "GLOBAL_LIMIT", 2)
    data = signups.validate(VALID).data
    assert data is not None
    for i in range(2):
        other = signups.SignupInput(**{**data.__dict__, "email": f"x{i}@example.vn"})
        await signups.create_signup(session, other, ip_digest=f"{i}" * 64)
    with pytest.raises(signups.RateLimited) as exc:
        await signups.create_signup(
            session,
            signups.SignupInput(**{**data.__dict__, "email": "z@example.vn"}),
            ip_digest="f" * 64,
        )
    assert exc.value.scope == "global"


async def test_without_recipients_or_smtp_it_still_succeeds(session, monkeypatch, caplog):
    # Real SmtpMailer, no OPS_SMTP_HOST: nothing is sent, the sign-up stands.
    monkeypatch.delenv("OPS_SMTP_HOST", raising=False)
    ops_mailer.set_mailer(None)
    caplog.set_level(logging.INFO)
    async with _public(session) as client:
        assert (await client.post("/v1/trial-signups", json=VALID)).status_code == 201
        monkeypatch.delenv("TRIAL_SIGNUP_NOTIFY_TO")
        other = {**VALID, "email": "b@example.vn"}
        assert (await client.post("/v1/trial-signups", json=other)).status_code == 201
    ops_mailer.set_mailer(None)
    assert await _count(session) == 2
    messages = [r.getMessage() for r in caplog.records]
    assert "ops_notice_mail_not_configured" in messages
    assert "trial_signup_notify_unsent" in messages
    assert "trial_signup_notify_unset" in messages


async def test_no_pii_in_logs(session, mailer, caplog, monkeypatch):
    # DEBUG for Juli's own loggers; the database driver's DEBUG statement echo
    # (aiosqlite) is a test-only artefact, INFO like production.
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.DEBUG, logger="juli_backend")
    monkeypatch.setenv("TRIAL_SIGNUP_RELAY_KEY", "k")
    async with _public(session) as client:
        await client.post("/v1/trial-signups", json=VALID)  # created
        await client.post("/v1/trial-signups", json={**VALID, "phone": "1"})  # invalid
        await client.post("/v1/trial-signups", json={**VALID, "website": "x"})  # honeypot
        for _ in range(signups.PER_EMAIL_LIMIT):  # rate limited at the end
            await client.post(
                "/v1/trial-signups",
                json=VALID,
                headers={"x-juli-relay-key": "k", "x-juli-client-ip": "203.0.113.9"},
            )
    forbidden = [
        "0912345678",
        "912345678",
        PHONE,
        "lan.nguyen@example.vn",
        EMAIL,
        NAME,
        "lanshop",
        "203.0.113.9",
    ]
    for record in caplog.records:
        rendered = record.getMessage() + " " + repr(record.__dict__)
        for value in forbidden:
            assert value not in rendered, (record.name, record.getMessage())
    messages = {r.getMessage() for r in caplog.records}
    assert {
        "trial_signup_created",
        "trial_signup_invalid",
        "trial_signup_honeypot",
        "trial_signup_rate_limited",
    } <= messages


# -- Ops console --------------------------------------------------------------------


async def _staff(session, role: str | None) -> User:
    email = f"{role or 'nobody'}-{uuid.uuid4().hex[:6]}@app-juli.com"
    user = await make_user(session, email=email)
    if role is not None:
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


async def _seed(session, n: int = 2) -> list[TrialSignup]:
    data = signups.validate(VALID).data
    assert data is not None
    rows = []
    for i in range(n):
        other = signups.SignupInput(**{**data.__dict__, "email": f"lead{i}@example.vn"})
        rows.append(await signups.create_signup(session, other, ip_digest=None))
    await session.commit()
    return rows


async def test_ops_list_needs_operator(session):
    await _seed(session)
    for role, code in (("viewer", 403), (None, 403), ("operator", 200), ("admin", 200)):
        user = await _staff(session, role)
        async with _client_as(session, user) as client:
            response = await client.get("/v1/ops/trial-signups")
        assert response.status_code == code, role
    body = response.json()
    assert len(body["data"]) == 2
    first = body["data"][0]
    # contact details are shown to the team, unmasked (prospects asked to be called)
    assert first["phone"] == "0912345678" and first["email"].endswith("@example.vn")
    assert first["status"] == "new" and first["status_label"] == "Mới"
    assert first["role_label"] == "Nhà bán"
    assert body["counts"] == {"new": 2, "contacted": 0, "converted": 0, "spam": 0}
    assert [o["value"] for o in body["statuses"]] == ["new", "contacted", "converted", "spam"]


async def test_ops_needs_cloudflare_access(session, monkeypatch):
    monkeypatch.delenv("OPS_CF_ACCESS_BYPASS")
    user = await _staff(session, "admin")
    async with _client_as(session, user) as client:
        assert (await client.get("/v1/ops/trial-signups")).status_code == 403
        rows = await _seed(session, 1)
        response = await client.patch(
            f"/v1/ops/trial-signups/{rows[0].id}", json={"status": "spam"}
        )
    assert response.status_code == 403


async def test_ops_without_a_token_is_401(session):
    async with _public(session) as client:
        assert (await client.get("/v1/ops/trial-signups")).status_code == 401


async def test_ops_status_change_is_audited(session):
    rows = await _seed(session, 2)
    target = rows[0]
    viewer = await _staff(session, "viewer")
    async with _client_as(session, viewer) as client:
        refused = await client.patch(
            f"/v1/ops/trial-signups/{target.id}", json={"status": "contacted"}
        )
    assert refused.status_code == 403
    assert await _count(session, OpsAuditLog) == 0

    op = await _staff(session, "operator")
    op_email = op.email  # read now: the 404 below rolls back and expires ORM rows
    target_id = target.id
    async with _client_as(session, op) as client:
        response = await client.patch(
            f"/v1/ops/trial-signups/{target.id}", json={"status": "contacted"}
        )
        filtered = await client.get("/v1/ops/trial-signups?status=contacted")
        same = await client.patch(
            f"/v1/ops/trial-signups/{target.id}", json={"status": "contacted"}
        )
        bad = await client.patch(f"/v1/ops/trial-signups/{target.id}", json={"status": "won"})
        missing = await client.patch(
            f"/v1/ops/trial-signups/{uuid.uuid4()}", json={"status": "spam"}
        )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "contacted" and data["handled_by"] == op_email
    assert data["handled_at"] is not None
    assert [r["id"] for r in filtered.json()["data"]] == [str(target_id)]
    assert same.status_code == 200
    assert bad.status_code == 422 and missing.status_code == 404

    audits = (await session.execute(select(OpsAuditLog))).scalars().all()
    assert len(audits) == 1  # the no-op save wrote nothing
    entry = audits[0]
    assert entry.action == "trial_signup_status"
    assert entry.actor_email == op_email
    assert entry.field == f"trial_signup:{target_id}"
    assert entry.before == {"status": "new"} and entry.after == {"status": "contacted"}
    assert entry.shop_id is None
    # the audit row never carries contact details
    assert "0912345678" not in repr(entry.before) + repr(entry.after)
    await session.refresh(target)
    assert target.status == "contacted"


async def test_ops_status_changes_per_signup_do_not_merge(session):
    rows = await _seed(session, 2)
    op = await _staff(session, "operator")
    async with _client_as(session, op) as client:
        for row in rows:
            r = await client.patch(f"/v1/ops/trial-signups/{row.id}", json={"status": "spam"})
            assert r.status_code == 200
    assert await _count(session, OpsAuditLog) == 2


# -- migration ----------------------------------------------------------------------


def test_migration_091_is_ops_only_and_chained():
    body = MIGRATION.read_text("utf-8")
    assert 'revision: str = "091_trial_signups"' in body
    assert len("091_trial_signups") <= 32
    assert 'down_revision: str | None = "090_reviewer_accounts"' in body
    assert "ENABLE ROW LEVEL SECURITY" in body
    assert "FOR ALL TO {OPS_ROLE}" in body
    assert "REVOKE ALL ON public.{TABLE} FROM {APP_ROLE}" in body
    assert "GRANT {APP_ROLE}" not in body and "TO {APP_ROLE}" not in body
    assert ("public", "trial_signups") in get_ops_only_tables()
    # The deferred contract step must stay the chain's tail (its docstring): it is
    # re-parented onto whatever `versions/` head is current, so read that head from the
    # tree rather than pinning a revision every new migration would break (P53, D62).
    # P61-F: the deferred chain is versions head -> 101 (data step) -> 074 (the tail).
    head = _versions_head()
    backfill = DEFERRED.parent / "101_write_mode_backfill.py"
    assert f'down_revision: str | None = "{head}"' in backfill.read_text("utf-8"), (
        f"deferred/101 must revise the current versions/ head {head!r}"
    )
    assert 'down_revision: str | None = "101_write_mode_backfill"' in DEFERRED.read_text("utf-8")


def _versions_head() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    heads = ScriptDirectory.from_config(Config(str(REPO / "alembic.ini"))).get_heads()
    assert len(heads) == 1, f"versions/ must have exactly one head, found {heads!r}"
    return heads[0]
