"""P32-A AC-32.3: the reviewer provisioning command (create / renew / revoke / show)."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from sqlalchemy import select

from juli_backend.models.ops import OpsAuditLog, OpsReviewerAccount
from juli_backend.services.reviewer import accounts
from juli_backend.services.reviewer.cli import build_parser, run
from juli_backend.services.reviewer.gotrue import BAN_FOREVER, UNBAN, AuthUser, GoTrueAdmin


class FakeGoTrue:
    def __init__(self) -> None:
        self.user_id = uuid.uuid4()
        self.calls: list[tuple] = []

    def create_or_update(self, email, password, platform):
        self.calls.append(("create", email, password, platform))
        return AuthUser(id=self.user_id, email=email)

    def update(self, user_id, *, password=None, platform=None, ban=None):
        self.calls.append(("update", user_id, password, platform, ban))
        return AuthUser(id=user_id, email="x")


@pytest.fixture(autouse=True)
def _no_cache():
    accounts.forget_cached()
    yield
    accounts.forget_cached()


async def _run(session, fake, *argv):
    lines: list[str] = []
    code = await run(build_parser().parse_args(list(argv)), session, lambda: fake, lines.append)
    return code, lines


async def test_create_renew_revoke_cycle(session):
    fake = FakeGoTrue()
    email = "Shopee-Review@app-juli.com"
    code, lines = await _run(
        session,
        fake,
        "create",
        "--email",
        email,
        "--platform",
        "Shopee",
        "--by",
        "owner@app-juli.com",
    )
    assert code == 0
    password = fake.calls[0][2]
    assert len(password) >= 20
    assert fake.calls[0][1] == "shopee-review@app-juli.com" and fake.calls[0][3] == "shopee"
    assert sum(password in line for line in lines) == 1  # printed exactly once
    row = (await session.execute(select(OpsReviewerAccount))).scalar_one()
    assert row.user_id == fake.user_id and row.platform == "shopee" and row.revoked_at is None
    assert (row.expires_at - row.created_at).days in (29, 30)

    code, _ = await _run(session, fake, "revoke", "--email", email, "--by", "owner@app-juli.com")
    assert code == 0
    assert fake.calls[-1][-1] == BAN_FOREVER
    await session.refresh(row)
    assert row.revoked_at is not None

    code, lines = await _run(
        session, fake, "renew", "--email", email, "--days", "7", "--rotate-password",
        "--by", "owner@app-juli.com",
    )  # fmt: skip
    assert code == 0
    assert fake.calls[-1][-1] == UNBAN and fake.calls[-1][2]
    await session.refresh(row)
    assert row.revoked_at is None

    audit = (await session.execute(select(OpsAuditLog))).scalars().all()
    assert [a.action for a in audit] == [
        "reviewer_account_create",
        "reviewer_account_revoke",
        "reviewer_account_renew",
    ]
    # No password anywhere in the database.
    dumped = json.dumps([[a.before, a.after] for a in audit], default=str)
    assert password not in dumped and fake.calls[-1][2] not in dumped


async def test_by_must_be_staff_and_unknown_email(session):
    fake = FakeGoTrue()
    with pytest.raises(SystemExit):
        await _run(
            session,
            fake,
            "create",
            "--email",
            "a@b.c",
            "--platform",
            "shopee",
            "--by",
            "x@gmail.com",
        )
    code, lines = await _run(
        session, fake, "revoke", "--email", "nobody@app-juli.com", "--by", "o@app-juli.com"
    )
    assert code == 1 and lines == ["not found"]
    assert fake.calls == []


def test_gotrue_create_takes_over_an_existing_user():
    seen: list[tuple[str, str, dict]] = []
    existing = str(uuid.uuid4())

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        seen.append((request.method, request.url.path, body))
        assert request.headers["apikey"] == "service-key"
        if request.method == "POST":
            return httpx.Response(422, json={"error_code": "email_exists"})
        if request.method == "GET":
            return httpx.Response(
                200, json={"users": [{"id": existing, "email": "r@app-juli.com"}]}
            )
        return httpx.Response(200, json={"id": existing, "email": "r@app-juli.com"})

    admin = GoTrueAdmin(
        "https://x.supabase.co",
        "service-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    user = admin.create_or_update("r@app-juli.com", "pw-123456789", "shopee")
    assert str(user.id) == existing
    put = seen[-1]
    assert put[0] == "PUT" and put[1] == f"/auth/v1/admin/users/{existing}"
    assert put[2]["app_metadata"] == {"juli_role": "reviewer", "juli_platform": "shopee"}
    assert put[2]["ban_duration"] == "none" and put[2]["email_confirm"] is True
    assert seen[0][2]["app_metadata"]["juli_role"] == "reviewer"


def test_new_style_secret_key_is_sent_in_apikey_only():
    """`sb_secret_…` keys are not JWTs; Supabase answers 401 when they are sent as Bearer."""
    headers: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        headers.append(dict(request.headers))
        return httpx.Response(200, json={"id": str(uuid.uuid4()), "email": "r@app-juli.com"})

    for key, bearer in (("sb_secret_abc123", False), ("eyJhbGciOiJIUzI1NiJ9.e30.sig", True)):
        headers.clear()
        admin = GoTrueAdmin(
            "https://x.supabase.co",
            key,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        admin.create_or_update("r@app-juli.com", "pw-123456789", "shopee")
        assert headers and all(h["apikey"] == key for h in headers)
        assert all(("authorization" in h) is bearer for h in headers)


# -- P67 (D75 Q4): reset = a fresh account, so the reviewer's history starts empty --------


class FakeAuthServer:
    """Supabase users by e-mail: ``create`` refuses a taken address, like GoTrue."""

    def __init__(self) -> None:
        self.users: dict[uuid.UUID, dict] = {}
        self.calls: list[tuple] = []

    def find_by_email(self, email):
        for user_id, user in self.users.items():
            if user["email"] == email:
                return AuthUser(id=user_id, email=email)
        return None

    def create(self, email, password, platform):
        self.calls.append(("create", email, platform))
        assert self.find_by_email(email) is None, "GoTrue refuses a taken address"
        user_id = uuid.uuid4()
        self.users[user_id] = {"email": email, "password": password, "ban": None}
        return AuthUser(id=user_id, email=email)

    def create_or_update(self, email, password, platform):
        existing = self.find_by_email(email)
        if existing is not None:
            self.users[existing.id]["password"] = password
            return existing
        return self.create(email, password, platform)

    def update(self, user_id, *, password=None, platform=None, ban=None, email=None):
        self.calls.append(("update", user_id, email, ban))
        user = self.users[user_id]
        user.update({k: v for k, v in (("email", email), ("ban", ban)) if v is not None})
        return AuthUser(id=user_id, email=user["email"])


async def test_create_on_an_existing_email_keeps_the_user_id_and_the_old_row(session):
    """Why ``reset`` exists: ``create`` takes over the same user and row (old created_at)."""
    server = FakeAuthServer()
    email = "shopee-review@app-juli.com"
    by = ("--by", "owner@app-juli.com")
    await _run(session, server, "create", "--email", email, "--platform", "shopee", *by)
    first = (await session.execute(select(OpsReviewerAccount))).scalar_one()
    first_id, first_created = first.user_id, first.created_at

    await _run(session, server, "create", "--email", email, "--platform", "shopee", *by)

    again = (await session.execute(select(OpsReviewerAccount))).scalar_one()
    assert (again.user_id, again.created_at) == (first_id, first_created)


async def test_reset_creates_a_new_user_and_row_and_retires_the_old_ones(session):
    server = FakeAuthServer()
    email = "shopee-review@app-juli.com"
    by = ("--by", "owner@app-juli.com")
    await _run(session, server, "create", "--email", email, "--platform", "shopee", *by)
    old = (await session.execute(select(OpsReviewerAccount))).scalar_one()
    old_id, old_created = old.user_id, old.created_at

    code, lines = await _run(
        session, server, "reset", "--email", email, "--platform", "shopee", *by
    )

    assert code == 0, lines
    rows = {r.email: r for r in (await session.execute(select(OpsReviewerAccount))).scalars().all()}
    fresh = rows[email]
    assert fresh.user_id != old_id and fresh.revoked_at is None
    assert fresh.created_at >= old_created and fresh.id != old.id
    (retired,) = [r for e, r in rows.items() if e != email]
    assert retired.user_id == old_id and retired.revoked_at is not None
    assert retired.email.startswith("shopee-review+retired-") and retired.email.endswith(
        "@app-juli.com"
    )
    # Supabase: the old user is banned under the retired address; the new one owns the e-mail.
    assert server.users[old_id]["email"] == retired.email
    assert server.users[old_id]["ban"] == BAN_FOREVER
    assert server.find_by_email(email).id == fresh.user_id
    # The sign-in gate reads the fresh account (new created_at = the P66 history cut-off).
    loaded = await accounts.load_account(session, fresh.user_id)
    assert loaded is not None and loaded.created_at == fresh.created_at
    assert await accounts.load_account(session, old_id) is not None  # kept, revoked
    # The new password is printed once; nothing else prints a secret.
    password = server.users[fresh.user_id]["password"]
    assert sum(password in line for line in lines) == 1
    old_password = server.users[old_id]["password"]
    assert not any(old_password in line for line in lines)
    audit = (await session.execute(select(OpsAuditLog))).scalars().all()
    dumped = json.dumps([[a.before, a.after] for a in audit], default=str)
    assert password not in dumped


async def test_reset_with_no_account_yet_just_creates_one(session):
    server = FakeAuthServer()
    code, lines = await _run(
        session, server, "reset", "--email", "new@app-juli.com", "--platform", "shopee",
        "--by", "owner@app-juli.com",
    )  # fmt: skip
    assert code == 0
    row = (await session.execute(select(OpsReviewerAccount))).scalar_one()
    assert row.email == "new@app-juli.com" and not any(line.startswith("retired") for line in lines)


def test_gotrue_create_never_takes_over_and_update_can_rename():
    seen: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        seen.append((request.method, request.url.path, body))
        if request.method == "POST":
            return httpx.Response(422, json={"error_code": "email_exists"})
        return httpx.Response(200, json={"id": str(uuid.uuid4()), "email": body.get("email")})

    admin = GoTrueAdmin(
        "https://x.supabase.co",
        "service-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    from juli_backend.services.reviewer.gotrue import GoTrueError

    with pytest.raises(GoTrueError):
        admin.create("r@app-juli.com", "pw-123456789", "shopee")
    assert [m for m, _, _ in seen] == ["POST"], "no lookup, no take-over"
    user_id = uuid.uuid4()
    admin.update(user_id, email="r+retired-1@app-juli.com", ban=BAN_FOREVER)
    assert seen[-1][2] == {
        "email": "r+retired-1@app-juli.com",
        "email_confirm": True,
        "ban_duration": BAN_FOREVER,
    }
