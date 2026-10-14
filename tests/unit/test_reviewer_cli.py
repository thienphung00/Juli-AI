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
