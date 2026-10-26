"""Fast track P61-F (D71.2): the agent run's production leg, two shops.

What these prove on the SQLite unit substrate (the real-Postgres, ``juli_app``,
two-shop proof of the same leg is
``tests/integration/test_p61f_agent_production_write_two_shop.py``):

- the gate matrix of the resume leg (``composition.resolve_agent_write_leg``): the
  one-time authorization is spent only when the global flag, THIS shop's enable
  row and every ADR-085 gate pass; every other combination is the sandbox (or a
  named refusal) with the authorization untouched;
- D13 and the image rule: a price confirmation and a listing edit that would
  attach a sandbox-staged image are refused by name BEFORE any authorization is
  consumed;
- the capability is for exactly the pending tool, the run's own product and the
  run's own shop -- an authorization for another tool / product / shop never
  satisfies it;
- the worker seam (``agent_workflow._write_resources_for_leg``): a decline, a
  first leg and a lever-flow re-check never reach the resolver; an approved resume
  does, and stamps ``write_mode`` only when a live write is really about to happen;
- ``write_mode`` settles to ``simulated`` when the confirmed call never reached the
  ledger, and stays ``live`` when it did (or may have);
- a revert reads the listing through the mode the run wrote with, and a revert of a
  live run never falls back to the sandbox;
- migration 101 (deferred): placement, chain, the gate's refusal, and its data
  step on a real table.

No test here reaches TikTok: the HTTP session behind the real guarded client is
``tests/support/fakes.FakeTikTokTransport``.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.integrations.tiktok import (
    ProductionWriteClientFactory,
    ProductionWriteResources,
    TikTokCapability,
)
from juli_backend.models.models import (
    WRITE_MODE_LIVE,
    WRITE_MODE_SIMULATED,
    Product,
    ProductionWriteAudit,
    ProductionWriteAuthorization,
    ProductionWriteShop,
    Shop,
    TikTokCredential,
    ToolExecution,
    User,
    WorkflowRun,
)
from juli_backend.services.agent import composition
from juli_backend.services.execution import production_write as production_write_module
from juli_backend.services.execution.production_write_resolver import (
    PreconditionName,
    record_rls_boot_check_passed,
)
from juli_backend.workers.tasks import agent_workflow
from tests.support.fakes import FakeTikTokTransport

pytestmark = pytest.mark.asyncio

LISTING = "update_product_listing"
PRICE = "update_product_price"
PRODUCT_A = "1001"
PRODUCT_B = "2002"
SANDBOX = object()


def teardown_function():
    from juli_backend.services.execution import production_write_resolver

    production_write_resolver._RLS_BOOT_CHECK_PASSED = False


# --- fixtures ---------------------------------------------------------------------------


async def _seed_shop(session: AsyncSession, label: str, merchant: str, product: str):
    user = User(id=uuid.uuid4(), phone=f"+8490{uuid.uuid4().int % 10**7:07d}")
    shop = Shop(id=uuid.uuid4(), user_id=user.id, shop_name=f"P61-F {label}")
    session.add_all([user, shop])
    await session.flush()
    session.add(
        TikTokCredential(
            shop_id=shop.id,
            merchant_authorization_id=merchant,
            capability=TikTokCapability.SELLER_CONNECT.value,
            shop_cipher=f"cipher-{label}",
            access_token=f"token-{label}",
            refresh_token=f"refresh-{label}",
            token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=30),
        )
    )
    product_row = Product(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_product_id=product,
        name=f"Product {label}",
        status="ACTIVE",
        update_time=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(product_row)
    await session.flush()
    return shop, product_row


@pytest_asyncio.fixture
async def shops(session: AsyncSession):
    return {
        "a": await _seed_shop(session, "a", "merchant-a", PRODUCT_A),
        "b": await _seed_shop(session, "b", "merchant-b", PRODUCT_B),
    }


async def _authorize(session, shop_id, product, mutation_kind=LISTING):
    row = ProductionWriteAuthorization(
        id=uuid.uuid4(),
        shop_id=shop_id,
        tiktok_product_id=product,
        mutation_kind=mutation_kind,
        authorized_by="owner",
        expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
    )
    session.add(row)
    await session.flush()
    return row


async def _enable(session, shop_id):
    session.add(ProductionWriteShop(shop_id=shop_id, enabled_by="owner"))
    await session.flush()


async def _run(session, shop, product, *, state=None, **extra) -> WorkflowRun:
    run = WorkflowRun(
        shop_id=shop.id,
        product_id=product.id,
        status="waiting_approval",
        prompt_version="optimize_product.v3",
        prompt_sha256="0" * 64,
        state=state if state is not None else {},
        subject_ref=str(uuid.uuid4()),
        **extra,
    )
    session.add(run)
    await session.flush()
    return run


def _arm(monkeypatch, tmp_path, *, attest: bool = True, rls: bool = True) -> None:
    monkeypatch.setenv("PRODUCTION_WRITE_ENABLED", "true")
    monkeypatch.setenv("PRODUCTION_WRITE_KILL_SWITCH", "false")
    sha = "a" * 40
    monkeypatch.setenv("RELEASE_SHA", sha)
    attestations = tmp_path / "attestations"
    attestations.mkdir(exist_ok=True)
    if attest:
        (attestations / f"{sha}.json").write_text(
            json.dumps({"release_sha": sha, "outcome": "pass", "performed_by": "test"})
        )
    monkeypatch.setenv("PRODUCTION_WRITE_ATTESTATION_DIR", str(attestations))
    if rls:
        record_rls_boot_check_passed()


@pytest.fixture
def sandbox(monkeypatch):
    """The sandbox loader every non-production write goes through, as a recorder."""
    monkeypatch.setenv("TIKTOK_APP_KEY", "app-key")
    monkeypatch.setenv("TIKTOK_APP_SECRET", "app-secret")
    loader = AsyncMock(return_value=SANDBOX)
    monkeypatch.setattr(
        "juli_backend.services.execution.sandbox_guard.load_sandbox_write_resources", loader
    )
    monkeypatch.setattr(composition, "load_sandbox_write_resources", loader)
    return loader


@pytest.fixture
def transport(monkeypatch):
    fake = FakeTikTokTransport(
        {
            PRODUCT_A: {"id": PRODUCT_A, "title": "A old", "description": "A desc"},
            PRODUCT_B: {"id": PRODUCT_B, "title": "B old", "description": "B desc"},
        }
    )
    fake.configs = []

    class _Factory(ProductionWriteClientFactory):
        def create(self, config):
            fake.configs.append(config)
            client = super().create(config)
            client._session = fake
            return client

    monkeypatch.setattr(production_write_module, "ProductionWriteClientFactory", _Factory)
    monkeypatch.setenv("TIKTOK_APP_KEY", "app-key")
    monkeypatch.setenv("TIKTOK_APP_SECRET", "app-secret")
    return fake


async def _consumed(session, authorization) -> bool:
    await session.refresh(authorization)
    return authorization.consumed_at is not None


async def _audits(session):
    return (await session.execute(select(ProductionWriteAudit))).scalars().all()


async def _leg(session, shop, product, run, tool=LISTING, **kwargs):
    return await composition.resolve_agent_write_leg(
        session,
        shop_id=shop.id,
        run_id=run.id,
        tiktok_product_id=product.tiktok_product_id,
        tool_name=tool,
        **kwargs,
    )


# --- the gate matrix of the resume leg ----------------------------------------------------


async def test_every_gate_open_spends_the_authorization_and_builds_the_shops_own_resources(
    session, shops, sandbox, transport, monkeypatch, tmp_path
):
    _arm(monkeypatch, tmp_path)
    shop_b, product_b = shops["b"]
    await _enable(session, shop_b.id)
    authorization = await _authorize(session, shop_b.id, PRODUCT_B)
    run = await _run(session, shop_b, product_b)

    leg = await _leg(session, shop_b, product_b, run)

    assert leg.live and leg.refusal is None
    assert isinstance(leg.resources, ProductionWriteResources)
    assert composition.write_mode_of(leg.resources) == WRITE_MODE_LIVE
    assert leg.authorization_id == str(authorization.id)
    assert await _consumed(session, authorization)
    (config,) = transport.configs
    assert (config.merchant_auth_id, config.access_token) == ("merchant-b", "token-b")
    assert [
        (a.shop_id, a.run_id, a.authorization_id, a.mutation_kind, a.tiktok_product_id)
        for a in await _audits(session)
    ] == [(shop_b.id, run.id, authorization.id, LISTING, PRODUCT_B)]
    sandbox.assert_not_awaited()


async def test_flag_off_is_the_sandbox_and_nothing_is_consumed_or_audited(
    session, shops, sandbox, transport, monkeypatch, tmp_path
):
    _arm(monkeypatch, tmp_path)
    monkeypatch.setenv("PRODUCTION_WRITE_ENABLED", "false")
    shop_b, product_b = shops["b"]
    await _enable(session, shop_b.id)
    authorization = await _authorize(session, shop_b.id, PRODUCT_B)
    run = await _run(session, shop_b, product_b)

    leg = await _leg(session, shop_b, product_b, run)

    assert not leg.live and leg.refusal is None and leg.resources is None
    assert not await _consumed(session, authorization)
    assert await _audits(session) == []
    assert transport.calls == []


async def test_a_shop_without_its_enable_row_stays_on_the_sandbox_while_b_goes_live(
    session, shops, sandbox, transport, monkeypatch, tmp_path
):
    _arm(monkeypatch, tmp_path)
    shop_a, product_a = shops["a"]
    shop_b, product_b = shops["b"]
    await _enable(session, shop_b.id)
    auth_a = await _authorize(session, shop_a.id, PRODUCT_A)
    auth_b = await _authorize(session, shop_b.id, PRODUCT_B)
    run_a = await _run(session, shop_a, product_a)
    run_b = await _run(session, shop_b, product_b)

    leg_a = await _leg(session, shop_a, product_a, run_a)
    leg_b = await _leg(session, shop_b, product_b, run_b)

    assert not leg_a.live and leg_a.refusal is None
    assert not await _consumed(session, auth_a)
    assert leg_b.live and await _consumed(session, auth_b)
    assert {a.shop_id for a in await _audits(session)} == {shop_b.id}


@pytest.mark.parametrize(
    ("gate", "expected"),
    [
        ("authorization", PreconditionName.NO_MATCHING_AUTHORIZATION),
        ("rls", PreconditionName.RLS_BOOT_CHECK_FAILED),
        ("attestation", PreconditionName.NO_ATTESTATION_FOR_RELEASE_SHA),
        ("kill_switch", PreconditionName.PRODUCTION_WRITE_KILL_SWITCH_ACTIVE),
    ],
)
async def test_each_adr085_gate_keeps_an_enabled_shop_on_the_sandbox_by_name(
    session, shops, sandbox, transport, monkeypatch, tmp_path, gate, expected
):
    _arm(monkeypatch, tmp_path, attest=gate != "attestation", rls=gate != "rls")
    if gate == "kill_switch":
        monkeypatch.setenv("PRODUCTION_WRITE_KILL_SWITCH", "true")
    shop_b, product_b = shops["b"]
    await _enable(session, shop_b.id)
    authorization = (
        None if gate == "authorization" else await _authorize(session, shop_b.id, PRODUCT_B)
    )
    run = await _run(session, shop_b, product_b)

    leg = await _leg(session, shop_b, product_b, run)

    assert not leg.live
    assert leg.refusal == expected.value
    if authorization is not None:
        assert not await _consumed(session, authorization)
    assert [a.precondition_name for a in await _audits(session)] == [expected.value]
    assert transport.calls == []


async def test_the_authorization_must_be_for_this_tool_this_product_and_this_shop(
    session, shops, sandbox, transport, monkeypatch, tmp_path
):
    """The capability is keyed by the run's shop + product and the pending tool's own
    name, so an authorization for anything else never satisfies it."""
    _arm(monkeypatch, tmp_path)
    shop_a, product_a = shops["a"]
    shop_b, product_b = shops["b"]
    await _enable(session, shop_b.id)
    other_tool = await _authorize(
        session, shop_b.id, PRODUCT_B, mutation_kind="listing.optimize_product"
    )
    other_product = await _authorize(session, shop_b.id, "9999")
    other_shop = await _authorize(session, shop_a.id, PRODUCT_B)
    run = await _run(session, shop_b, product_b)

    leg = await _leg(session, shop_b, product_b, run)

    assert not leg.live and leg.refusal == PreconditionName.NO_MATCHING_AUTHORIZATION.value
    for untouched in (other_tool, other_product, other_shop):
        assert not await _consumed(session, untouched)
    assert transport.calls == []


async def test_a_partner_reviewer_request_is_never_routed_live(
    session, shops, sandbox, transport, monkeypatch, tmp_path
):
    """D73 Q6: the resolver refuses a reviewer request before any authorization lookup;
    the resume leg reads that as a refusal and stays on the sandbox."""
    _arm(monkeypatch, tmp_path)
    monkeypatch.setattr("juli_backend.integrations.tiktok.reviewer_session_active", lambda: True)
    shop_b, product_b = shops["b"]
    await _enable(session, shop_b.id)
    authorization = await _authorize(session, shop_b.id, PRODUCT_B)
    run = await _run(session, shop_b, product_b)

    leg = await _leg(session, shop_b, product_b, run)

    assert not leg.live and leg.refusal == PreconditionName.REVIEWER_SESSION.value
    assert not await _consumed(session, authorization)
    assert transport.calls == []


async def test_a_price_confirmation_is_refused_by_name_before_an_authorization_is_spent(
    session, shops, sandbox, transport, monkeypatch, tmp_path
):
    _arm(monkeypatch, tmp_path)
    shop_b, product_b = shops["b"]
    await _enable(session, shop_b.id)
    # Even a price authorization the owner issued (the CLI will issue anything) is not spent.
    authorization = await _authorize(session, shop_b.id, PRODUCT_B, mutation_kind=PRICE)
    run = await _run(session, shop_b, product_b)

    leg = await _leg(session, shop_b, product_b, run, tool=PRICE)

    assert not leg.live
    assert leg.refusal == PreconditionName.MUTATION_NOT_ALLOWED_IN_PRODUCTION.value
    assert not await _consumed(session, authorization)
    assert [(a.authorization_id, a.precondition_name) for a in await _audits(session)] == [
        (None, "mutation_not_allowed_in_production")
    ]
    assert transport.calls == []


async def test_a_listing_edit_that_attaches_a_sandbox_staged_image_is_refused_by_name(
    session, shops, sandbox, transport, monkeypatch, tmp_path
):
    _arm(monkeypatch, tmp_path)
    shop_b, product_b = shops["b"]
    await _enable(session, shop_b.id)
    authorization = await _authorize(session, shop_b.id, PRODUCT_B)
    run = await _run(session, shop_b, product_b)

    leg = await _leg(session, shop_b, product_b, run, staged_image=True)

    assert not leg.live and leg.refusal == PreconditionName.STAGED_IMAGE_ON_SANDBOX.value
    assert not await _consumed(session, authorization)
    assert [a.precondition_name for a in await _audits(session)] == ["staged_image_on_sandbox"]
    assert transport.calls == []


async def test_the_refusals_are_silent_for_a_shop_that_is_not_production_enabled(
    session, shops, sandbox, transport, monkeypatch, tmp_path
):
    """A shop that is not enabled never had a live path, so a price or an image on it is
    today's sandbox run: no refusal, no audit row."""
    _arm(monkeypatch, tmp_path)
    shop_a, product_a = shops["a"]
    run = await _run(session, shop_a, product_a)
    for kwargs in ({"tool": PRICE}, {"staged_image": True}):
        leg = await _leg(session, shop_a, product_a, run, **kwargs)
        assert not leg.live and leg.refusal is None
    assert await _audits(session) == []


# --- revert -------------------------------------------------------------------------------


async def test_a_revert_of_a_simulated_run_never_goes_live(
    session, shops, sandbox, transport, monkeypatch, tmp_path
):
    _arm(monkeypatch, tmp_path)
    shop_b, product_b = shops["b"]
    await _enable(session, shop_b.id)
    authorization = await _authorize(session, shop_b.id, PRODUCT_B)
    run = await _run(session, shop_b, product_b)

    for source_mode in (WRITE_MODE_SIMULATED, None):
        leg = await _leg(
            session, shop_b, product_b, run, is_revert=True, source_write_mode=source_mode
        )
        assert not leg.live and leg.refusal == PreconditionName.REVERT_OF_SIMULATED_RUN.value
    assert not await _consumed(session, authorization)


async def test_a_revert_of_a_live_run_goes_live_or_fails_but_never_falls_back(
    session, shops, sandbox, transport, monkeypatch, tmp_path
):
    _arm(monkeypatch, tmp_path)
    shop_b, product_b = shops["b"]
    shop_a, product_a = shops["a"]
    await _enable(session, shop_b.id)
    run_b = await _run(session, shop_b, product_b)
    run_a = await _run(session, shop_a, product_a)

    # No authorization yet: a named failure, not a sandbox restore.
    with pytest.raises(composition.RevertLiveWriteUnavailable) as refused:
        await _leg(
            session, shop_b, product_b, run_b, is_revert=True, source_write_mode=WRITE_MODE_LIVE
        )
    assert refused.value.reason == PreconditionName.NO_MATCHING_AUTHORIZATION.value
    # The shop's enable row was withdrawn: also a failure.
    with pytest.raises(composition.RevertLiveWriteUnavailable) as refused:
        await _leg(
            session, shop_a, product_a, run_a, is_revert=True, source_write_mode=WRITE_MODE_LIVE
        )
    assert refused.value.reason == "production_write_not_enabled_for_shop"

    await _authorize(session, shop_b.id, PRODUCT_B)
    leg = await _leg(
        session, shop_b, product_b, run_b, is_revert=True, source_write_mode=WRITE_MODE_LIVE
    )
    assert leg.live


async def test_the_live_reader_follows_the_mode_the_run_wrote_with(session, monkeypatch):
    from juli_backend.services.run_changes import read_live_product

    shop_id = uuid.uuid4()
    calls: list[str] = []

    class _Products:
        def __init__(self, tag):
            self._tag = tag

        def get_details(self, product_id):
            calls.append(f"{self._tag}:{product_id}")
            return {"title": self._tag}

    class _Resources:
        def __init__(self, tag):
            self.products = _Products(tag)

    async def _read(_session, _shop_id):
        assert _shop_id == shop_id
        return _Resources("shop-read")

    async def _write(_session, *_args):
        return _Resources("sandbox")

    monkeypatch.setattr(composition, "build_read_resources", _read)
    monkeypatch.setattr(composition, "build_write_resources", _write)

    assert (await read_live_product(session, shop_id, "p1", WRITE_MODE_LIVE))[
        "title"
    ] == "shop-read"
    assert (await read_live_product(session, shop_id, "p1", WRITE_MODE_SIMULATED))[
        "title"
    ] == "sandbox"
    assert (await read_live_product(session, shop_id, "p1", None))["title"] == "sandbox"
    assert (await read_live_product(session, shop_id, "p1"))["title"] == "sandbox"
    assert calls == ["shop-read:p1", "sandbox:p1", "sandbox:p1", "sandbox:p1"]


# --- the worker seam ----------------------------------------------------------------------


def _pending(tool=LISTING, **arguments):
    return {
        "pending_confirmation": {"call_id": "call-1", "tool_name": tool, "arguments": arguments}
    }


@pytest.fixture
def default_sandbox(monkeypatch):
    async def _default(session):
        return SANDBOX

    monkeypatch.setattr(agent_workflow, "_default_write_resources", _default)


async def _seam(session, run, product, **overrides):
    kwargs = {"resume_approved": True, "staged_image": False, "is_revert": False}
    kwargs.update(overrides)
    return await agent_workflow._write_resources_for_leg(session, run, product, **kwargs)


async def test_an_approved_resume_takes_the_confirmed_listing_edit_live_and_stamps_it(
    session, shops, sandbox, transport, default_sandbox, monkeypatch, tmp_path
):
    _arm(monkeypatch, tmp_path)
    shop_b, product_b = shops["b"]
    await _enable(session, shop_b.id)
    authorization = await _authorize(session, shop_b.id, PRODUCT_B)
    run = await _run(session, shop_b, product_b, state=_pending(title="new"))

    resources, call_id = await _seam(session, run, product_b)

    assert isinstance(resources, ProductionWriteResources) and call_id == "call-1"
    assert run.write_mode == WRITE_MODE_LIVE
    assert await _consumed(session, authorization)


@pytest.mark.parametrize("case", ["declined", "first_leg", "no_pending_tool"])
async def test_only_an_approved_pending_confirmation_reaches_the_resolver(
    session, shops, sandbox, transport, default_sandbox, monkeypatch, tmp_path, case
):
    _arm(monkeypatch, tmp_path)
    shop_b, product_b = shops["b"]
    await _enable(session, shop_b.id)
    authorization = await _authorize(session, shop_b.id, PRODUCT_B)
    state = {} if case == "first_leg" else _pending()
    if case == "no_pending_tool":
        state = {"pending_confirmation": {"call_id": "c", "arguments": {}}}
    run = await _run(session, shop_b, product_b, state=state)

    resources, call_id = await _seam(session, run, product_b, resume_approved=case != "declined")

    assert resources is SANDBOX and call_id is None
    assert not await _consumed(session, authorization)
    assert await _audits(session) == []
    assert run.write_mode is None


async def test_a_refused_live_leg_is_stamped_simulated_and_runs_on_the_sandbox(
    session, shops, sandbox, transport, default_sandbox, monkeypatch, tmp_path
):
    _arm(monkeypatch, tmp_path)
    shop_b, product_b = shops["b"]
    await _enable(session, shop_b.id)  # no authorization: a gate refuses
    run = await _run(session, shop_b, product_b, state=_pending())

    resources, call_id = await _seam(session, run, product_b)

    assert resources is SANDBOX and call_id is None
    assert run.write_mode == WRITE_MODE_SIMULATED


async def test_the_models_staged_image_flag_can_only_refuse_a_live_write(
    session, shops, sandbox, transport, default_sandbox, monkeypatch, tmp_path
):
    _arm(monkeypatch, tmp_path)
    shop_b, product_b = shops["b"]
    await _enable(session, shop_b.id)
    authorization = await _authorize(session, shop_b.id, PRODUCT_B)
    run = await _run(session, shop_b, product_b, state=_pending(attach_staged_image=True))

    resources, _call = await _seam(session, run, product_b)

    assert resources is SANDBOX and run.write_mode == WRITE_MODE_SIMULATED
    assert not await _consumed(session, authorization)

    # The server's own knowledge (a lever flow's staged photo) refuses it too.
    run2 = await _run(session, shop_b, product_b, state=_pending())
    resources, _call = await _seam(session, run2, product_b, staged_image=True)
    assert resources is SANDBOX and not await _consumed(session, authorization)


async def test_the_revert_leg_reads_the_reverted_runs_mode_from_its_row(
    session, shops, sandbox, transport, default_sandbox, monkeypatch, tmp_path
):
    _arm(monkeypatch, tmp_path)
    shop_b, product_b = shops["b"]
    await _enable(session, shop_b.id)
    authorization = await _authorize(session, shop_b.id, PRODUCT_B)
    original = await _run(session, shop_b, product_b, write_mode=WRITE_MODE_SIMULATED)
    revert = await _run(session, shop_b, product_b, state=_pending(), reverts_run_id=original.id)

    resources, _call = await _seam(session, revert, product_b, is_revert=True)
    assert resources is SANDBOX and not await _consumed(session, authorization)

    original.write_mode = WRITE_MODE_LIVE
    await session.flush()
    resources, call_id = await _seam(session, revert, product_b, is_revert=True)
    assert isinstance(resources, ProductionWriteResources) and call_id == "call-1"
    assert revert.write_mode == WRITE_MODE_LIVE


# --- write_mode settles to what happened ----------------------------------------------------


async def _ledger_row(session, shop, run, call_id, status):
    session.add(
        ToolExecution(
            shop_id=shop.id,
            approval_id="a",
            tool_name=LISTING,
            payload_json="{}",
            status=status,
            workflow_run_id=run.id,
            tool_call_id=call_id,
            operation=LISTING,
        )
    )
    await session.flush()


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("succeeded", WRITE_MODE_LIVE),
        ("in_flight", WRITE_MODE_LIVE),  # ambiguous: never reported as "nothing changed"
        ("failed", WRITE_MODE_SIMULATED),
        (None, WRITE_MODE_SIMULATED),  # the confirmed call never reached the ledger
    ],
)
async def test_live_is_kept_only_when_the_write_reached_the_ledger(
    session, shops, status, expected
):
    shop_b, product_b = shops["b"]
    run = await _run(session, shop_b, product_b, write_mode=WRITE_MODE_LIVE)
    if status is not None:
        await _ledger_row(session, shop_b, run, "call-1", status)
    if status is None:
        # A row of ANOTHER call must not keep this one live.
        await _ledger_row(session, shop_b, run, "call-0", "succeeded")

    final = await composition.settle_live_write_mode(session, run_id=run.id, tool_call_id="call-1")

    assert final == expected == run.write_mode


async def test_settling_never_touches_a_simulated_run(session, shops):
    shop_b, product_b = shops["b"]
    run = await _run(session, shop_b, product_b, write_mode=WRITE_MODE_SIMULATED)
    assert await composition.settle_live_write_mode(session, run_id=run.id, tool_call_id="x") == (
        WRITE_MODE_SIMULATED
    )


async def test_the_live_leg_runner_settles_after_the_resume_and_delegates_the_rest(session, shops):
    shop_b, product_b = shops["b"]
    run = await _run(session, shop_b, product_b, write_mode=WRITE_MODE_LIVE)

    class _Inner:
        marker = "inner"

        async def resume(self, workflow_run_id, *, approved):
            return ("resumed", workflow_run_id, approved)

    wrapped = agent_workflow._LiveLegRunner(_Inner(), session, run_id=run.id, tool_call_id="call-1")
    assert wrapped.marker == "inner"
    assert await wrapped.resume(run.id, approved=True) == ("resumed", run.id, True)
    assert run.write_mode == WRITE_MODE_SIMULATED  # no ledger row for call-1


# --- the audit link of a recorded write ---------------------------------------------------------


async def test_a_refusal_row_does_not_hide_the_allowed_audit_row_of_the_write(session, shops):
    from juli_backend.models.run_changes import RunWriteValue
    from juli_backend.services.agent.runner.write_capture import FieldWrite
    from juli_backend.services.run_changes import SqlWriteValueRecorder

    shop_b, product_b = shops["b"]
    run = await _run(session, shop_b, product_b)
    authorization = await _authorize(session, shop_b.id, PRODUCT_B)

    def _audit(**extra):
        return ProductionWriteAudit(
            id=uuid.uuid4(),
            run_id=run.id,
            shop_id=shop_b.id,
            tiktok_product_id=PRODUCT_B,
            mutation_kind=LISTING,
            release_sha="0" * 40,
            **extra,
        )

    refused = _audit(precondition_name="no_matching_authorization")
    allowed = _audit(authorization_id=authorization.id)
    session.add_all([refused, allowed])
    await session.commit()

    def record(sync_session):
        SqlWriteValueRecorder(sync_session, shop_id=shop_b.id, workflow_run_id=run.id).record(
            tool_name=LISTING,
            tool_call_id="call-1",
            tiktok_product_id=PRODUCT_B,
            writes=[FieldWrite("title", "old", "new", "read_back")],
        )

    await session.run_sync(record)
    row = (await session.execute(select(RunWriteValue))).scalar_one()
    assert row.production_write_audit_id == allowed.id


# --- the first leg ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("possible", "resume_approved", "expected"),
    [
        (False, False, WRITE_MODE_SIMULATED),  # today's behaviour, byte for byte
        (True, False, None),  # production-enabled shop, nothing decided before approval
        (True, True, WRITE_MODE_SIMULATED),  # approved, sandbox sentinel -> simulated
    ],
)
async def test_the_first_leg_does_not_guess_for_a_production_enabled_shop(
    monkeypatch, possible, resume_approved, expected
):
    import juli_backend.services.agent.runner as runner_pkg
    from tests.unit import test_agent_workflow_task_wiring as wiring

    monkeypatch.setattr(runner_pkg, "WorkflowRunner", wiring._SpyWorkflowRunner)
    monkeypatch.setattr(agent_workflow, "_default_llm_service", lambda: "FAKE_LLM_SERVICE")
    monkeypatch.setattr(agent_workflow, "_default_tool_registry", wiring.ToolRegistry)
    monkeypatch.setattr(agent_workflow, "_playbook_for_run", lambda _run: wiring._dummy_playbook())
    monkeypatch.setattr(agent_workflow, "_default_read_resources", wiring._fake_read_resources)
    monkeypatch.setattr(agent_workflow, "_default_write_resources", wiring._fake_write_resources)
    monkeypatch.setattr(agent_workflow, "_ensure_session_factory", lambda: lambda: None)

    async def _no_flow(*_a, **_k):
        return None

    from juli_backend.services import lever_flows

    monkeypatch.setattr(lever_flows, "wiring_for_run", _no_flow)

    async def _possible(_session, _shop_id):
        return possible

    monkeypatch.setattr(composition, "shop_production_write_possible", _possible)
    run, product = wiring._seeded_run_and_product()

    await agent_workflow._construct_runner(
        session=object(),
        sync_session=object(),
        run=run,
        product=product,
        resume_approved=resume_approved,
    )

    assert run.write_mode == expected


# --- migration 101 (deferred) -------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "backend/src/juli_backend/database/migrations"
BACKFILL = MIGRATIONS / "deferred/101_write_mode_backfill.py"


async def test_migration_101_is_a_deferred_data_step_the_gate_refuses_and_074_chains_under_it():
    import sys

    sys.path.insert(0, str(REPO / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    body = BACKFILL.read_text("utf-8")
    assert 'revision: str = "101_write_mode_backfill"' in body
    assert len("101_write_mode_backfill") <= 32
    # P68 (E11), then D76, re-parented the deferred step onto the new versions/ head.
    assert 'down_revision: str | None = "103_data_use_consents"' in body
    assert not list((MIGRATIONS / "versions").glob("101*"))
    result = evaluate_migration_paths([BACKFILL])
    assert not result.accepted
    assert {(f.kind, f.operation) for f in result.findings} == {("data_moving", "execute(UPDATE)")}
    cleanup = (MIGRATIONS / "deferred/074_users_placeholder_phone_cleanup.py").read_text("utf-8")
    assert 'down_revision: str | None = "101_write_mode_backfill"' in cleanup


async def test_migration_101_is_one_literal_statement_and_its_downgrade_is_a_no_op():
    import ast

    tree = ast.parse(BACKFILL.read_text("utf-8"))
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    (call,) = [n for n in ast.walk(functions["upgrade"]) if isinstance(n, ast.Call)]
    assert isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str)
    assert not [n for n in ast.walk(functions["downgrade"]) if isinstance(n, ast.Call)]
