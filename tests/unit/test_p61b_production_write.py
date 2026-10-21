"""Fast track P61-B (D71.2): production writes per shop, flags off; honest sandbox runs.

What these prove, on the SQLite unit substrate (the real-Postgres, ``juli_app``,
two-shop proof is ``tests/integration/test_p61b_production_write_two_shop.py``):

- the transport layer: a production write client may sign the listing edit and
  the reads around it, nothing else (no price, no create), and is never built
  for the sandbox merchant;
- the per-shop write credential is the shop's own, never another shop's, never
  the sandbox merchant's;
- the resolver matrix: every gate off gives the sandbox or a named refusal; all
  gates on AND the shop's enable row give a production capability for THAT shop;
  the kill switch wins; enabling shop B never enables shop A;
- the listing handlers: today's behaviour with the flags off (sandbox, outcome
  says ``simulated``); a live write only through every gate, through B's own
  credential, with ``run_write_values`` + an allowed audit row; price / create /
  run-less executions refused before an authorization is consumed;
- honest UX: a run that wrote to the sandbox is ``simulated`` in the run list
  and its card, never "Đã áp dụng";
- measurement: the impact reader skips simulated writes, and a simulated listing
  run has no Đo lường.

No test here reaches TikTok: the HTTP session behind the real guarded client is
``tests/support/fakes.FakeTikTokTransport``.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.integrations.tiktok import (
    ClientFactoryConfig,
    ProductionWriteClientFactory,
    ProductionWriteResources,
    TikTokCapability,
    TransportGuardError,
)
from juli_backend.integrations.tiktok.capabilities import (
    PRODUCTION_WRITE_ALLOWED_REQUESTS,
    is_production_write_allowed,
)
from juli_backend.models.models import (
    WRITE_MODE_LIVE,
    WRITE_MODE_SIMULATED,
    WRITE_MODES,
    ImpactReading,
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
from juli_backend.models.run_changes import RunWriteValue
from juli_backend.services.execution import production_write as production_write_module
from juli_backend.services.execution.production_write_resolver import (
    PreconditionFailure,
    PreconditionName,
    record_rls_boot_check_passed,
    resolve_write_capability,
)
from tests.support.fakes import FakeTikTokTransport

# Test merchant ids (P61-G, D71.6): nothing is configured; these are just row values.
SANDBOX_AUTH_ID = "test-sandbox-merchant"

pytestmark = pytest.mark.asyncio

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "backend/src/juli_backend/database/migrations"
OPTIMIZE = "listing.optimize_product"
PRODUCT_A = "1001"
PRODUCT_B = "2002"
SANDBOX = object()


def teardown_function():
    from juli_backend.services.execution import production_write_resolver

    production_write_resolver._RLS_BOOT_CHECK_PASSED = False


# --- fixtures -------------------------------------------------------------------------


async def _seed_shop(session: AsyncSession, label: str, merchant: str, product: str):
    user = User(id=uuid.uuid4(), phone=f"+8490{uuid.uuid4().int % 10**7:07d}")
    shop = Shop(id=uuid.uuid4(), user_id=user.id, shop_name=f"P61-B {label}")
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
    shop_a, product_a = await _seed_shop(session, "a", "merchant-a", PRODUCT_A)
    shop_b, product_b = await _seed_shop(session, "b", "merchant-b", PRODUCT_B)
    return {"a": (shop_a, product_a), "b": (shop_b, product_b)}


async def _authorize(session, shop_id, product, mutation_kind=OPTIMIZE):
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


async def _run(session, shop, product) -> WorkflowRun:
    run = WorkflowRun(
        shop_id=shop.id,
        product_id=product.id,
        status="running",
        prompt_version="optimize_product.v3",
        prompt_sha256="0" * 64,
        state={},
    )
    session.add(run)
    await session.flush()
    return run


def _arm(monkeypatch, tmp_path, *, attest: bool = True, rls: bool = True) -> None:
    """Every global gate on (the shop's own enable row is the test's to add)."""
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
    return loader


@pytest.fixture
def transport(monkeypatch):
    """A fake HTTP session behind the REAL ProductionWriteClientFactory + guard."""
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


async def _resolve(session, shop, product):
    return await resolve_write_capability(
        session,
        tool_name=OPTIMIZE,
        payload={"tiktok_product_id": product, "mutation_kind": OPTIMIZE},
        shop_id=shop.id,
        run_id=uuid.uuid4(),
    )


async def _consumed(session, authorization) -> bool:
    await session.refresh(authorization)
    return authorization.consumed_at is not None


# --- transport layer ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "allowed"),
    [
        ("GET", f"/product/202309/products/{PRODUCT_B}", True),
        ("PUT", f"/product/202309/products/{PRODUCT_B}", True),
        ("POST", "/product/202309/images/upload", True),
        ("GET", "/product/202309/products/seo_words", True),
        ("GET", "/product/202309/products/suggestions", True),
        # D13: price is a recommendation only; Juli never reverts a price.
        ("POST", f"/product/202309/products/{PRODUCT_B}/prices/update", False),
        ("POST", "/product/202309/products", False),
        ("POST", f"/product/202309/products/{PRODUCT_B}/inventory/update", False),
        ("POST", "/promotion/202309/activities", False),
        ("POST", "/fulfillment/202309/packages/ship", False),
        ("DELETE", f"/product/202309/products/{PRODUCT_B}", False),
    ],
)
def test_the_production_guard_signs_only_the_listing_edit(method, path, allowed):
    assert is_production_write_allowed(method, path) is allowed


def test_production_is_a_strict_subset_of_the_sandbox_allowlist():
    from juli_backend.integrations.tiktok.capabilities import SANDBOX_ALLOWED_REQUESTS

    production = {
        (method, pattern.pattern) for method, pattern in PRODUCTION_WRITE_ALLOWED_REQUESTS
    }
    sandbox = {(method, pattern.pattern) for method, pattern in SANDBOX_ALLOWED_REQUESTS}
    assert production < sandbox
    assert not any("prices" in pattern for _method, pattern in production)


def _config(merchant: str) -> ClientFactoryConfig:
    return ClientFactoryConfig(
        app_key="k", app_secret="s", access_token="t", merchant_auth_id=merchant
    )


def test_the_factory_refuses_the_sandbox_merchant_and_an_empty_one():
    with pytest.raises(ValueError, match="sandbox_write"):
        ProductionWriteClientFactory().create(
            dataclasses.replace(_config(SANDBOX_AUTH_ID), credential_capability="sandbox_write")
        )
    with pytest.raises(ValueError, match="carries"):
        ProductionWriteClientFactory().create(
            dataclasses.replace(
                _config(SANDBOX_AUTH_ID), sandbox_merchant_auth_ids=frozenset({SANDBOX_AUTH_ID})
            )
        )
    with pytest.raises(ValueError, match="empty"):
        ProductionWriteClientFactory().create(_config(""))
    resources = ProductionWriteClientFactory().create_resources(_config("merchant-b"))
    assert isinstance(resources, ProductionWriteResources)
    with pytest.raises(TransportGuardError):
        resources.products.update_prices(product_id=PRODUCT_B, body={"skus": []})
    with pytest.raises(TransportGuardError):
        resources.products.create(body={})


# --- the shop's own write credential -----------------------------------------------------


async def test_the_write_credential_is_the_shops_own(session, shops):
    from juli_backend.core.security import (
        NoWriteCredentialForShop,
        resolve_write_credential_for_shop,
    )

    shop_a, _ = shops["a"]
    shop_b, _ = shops["b"]
    credential = await resolve_write_credential_for_shop(session, shop_b.id)
    assert credential.shop_id == shop_b.id
    assert credential.merchant_authorization_id == "merchant-b"

    # A shop whose only credential carries the merchant id a sandbox_write row carries has
    # no write credential (the sandbox merchant is read from the DB, P61-G).
    sandbox_user = User(id=uuid.uuid4(), phone="+84901234598")
    sandbox_shop = Shop(id=uuid.uuid4(), user_id=sandbox_user.id, shop_name="P61-G sandbox")
    session.add_all([sandbox_user, sandbox_shop])
    await session.flush()
    session.add(
        TikTokCredential(
            shop_id=sandbox_shop.id,
            merchant_authorization_id=SANDBOX_AUTH_ID,
            capability=TikTokCapability.SANDBOX_WRITE.value,
            access_token="sandbox-token",
            refresh_token="r",
            token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=30),
        )
    )
    user = User(id=uuid.uuid4(), phone="+84901234599")
    lonely = Shop(id=uuid.uuid4(), user_id=user.id, shop_name="P61-B sandbox-only")
    session.add_all([user, lonely])
    await session.flush()
    session.add(
        TikTokCredential(
            shop_id=lonely.id,
            merchant_authorization_id=SANDBOX_AUTH_ID,
            capability=TikTokCapability.SELLER_CONNECT.value,
            access_token="sandbox-token",
            refresh_token="r",
            token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=30),
        )
    )
    await session.flush()
    with pytest.raises(NoWriteCredentialForShop):
        await resolve_write_credential_for_shop(session, lonely.id)
    assert (await resolve_write_credential_for_shop(session, shop_a.id)).shop_id == shop_a.id


# --- the resolver matrix ----------------------------------------------------------------


async def test_flag_off_is_the_sandbox_for_every_shop_even_when_enabled(
    session, shops, sandbox, monkeypatch, tmp_path
):
    _arm(monkeypatch, tmp_path)
    monkeypatch.setenv("PRODUCTION_WRITE_ENABLED", "false")
    shop_b, _ = shops["b"]
    await _enable(session, shop_b.id)
    authorization = await _authorize(session, shop_b.id, PRODUCT_B)
    assert await _resolve(session, shop_b, PRODUCT_B) is SANDBOX
    assert not await _consumed(session, authorization)


async def test_enabling_shop_b_does_not_enable_shop_a(
    session, shops, sandbox, monkeypatch, tmp_path
):
    _arm(monkeypatch, tmp_path)
    shop_a, _ = shops["a"]
    shop_b, _ = shops["b"]
    await _enable(session, shop_b.id)
    auth_a = await _authorize(session, shop_a.id, PRODUCT_A)
    auth_b = await _authorize(session, shop_b.id, PRODUCT_B)

    assert await _resolve(session, shop_a, PRODUCT_A) is SANDBOX
    assert not await _consumed(session, auth_a)

    marker = await _resolve(session, shop_b, PRODUCT_B)
    assert marker["capability"] == "production_write"
    assert marker["shop_id"] == str(shop_b.id)
    assert marker["authorization_id"] == str(auth_b.id)
    assert await _consumed(session, auth_b)
    audits = (await session.execute(select(ProductionWriteAudit))).scalars().all()
    assert [(row.shop_id, row.precondition_name) for row in audits] == [(shop_b.id, None)]


@pytest.mark.parametrize(
    ("gate", "expected"),
    [
        ("authorization", PreconditionName.NO_MATCHING_AUTHORIZATION),
        ("rls", PreconditionName.RLS_BOOT_CHECK_FAILED),
        ("attestation", PreconditionName.NO_ATTESTATION_FOR_RELEASE_SHA),
        ("kill_switch", PreconditionName.PRODUCTION_WRITE_KILL_SWITCH_ACTIVE),
    ],
)
async def test_each_gate_off_refuses_by_name_for_an_enabled_shop(
    session, shops, sandbox, monkeypatch, tmp_path, gate, expected
):
    _arm(monkeypatch, tmp_path, attest=gate != "attestation", rls=gate != "rls")
    if gate == "kill_switch":
        monkeypatch.setenv("PRODUCTION_WRITE_KILL_SWITCH", "true")
    shop_b, _ = shops["b"]
    await _enable(session, shop_b.id)
    authorization = None
    if gate != "authorization":
        authorization = await _authorize(session, shop_b.id, PRODUCT_B)

    with pytest.raises(PreconditionFailure) as refused:
        await _resolve(session, shop_b, PRODUCT_B)
    assert refused.value.precondition == expected
    if authorization is not None:
        assert not await _consumed(session, authorization)
    refusals = (await session.execute(select(ProductionWriteAudit))).scalars().all()
    assert [row.precondition_name for row in refusals] == [expected.value]
    sandbox.assert_not_awaited()


async def test_the_kill_switch_wins_over_every_other_gate(
    session, shops, sandbox, monkeypatch, tmp_path
):
    _arm(monkeypatch, tmp_path)
    shop_b, _ = shops["b"]
    await _enable(session, shop_b.id)
    authorization = await _authorize(session, shop_b.id, PRODUCT_B)
    monkeypatch.setenv("PRODUCTION_WRITE_KILL_SWITCH", "on")  # malformed = active
    with pytest.raises(PreconditionFailure) as refused:
        await _resolve(session, shop_b, PRODUCT_B)
    assert refused.value.precondition is PreconditionName.PRODUCTION_WRITE_KILL_SWITCH_ACTIVE
    assert not await _consumed(session, authorization)


async def test_the_production_capability_builds_that_shops_own_client(
    session, shops, sandbox, transport, monkeypatch, tmp_path
):
    from juli_backend.services.agent import composition
    from juli_backend.services.execution.production_write import ProductionWriteBindingError

    _arm(monkeypatch, tmp_path)
    shop_a, _ = shops["a"]
    shop_b, _ = shops["b"]
    await _enable(session, shop_b.id)
    await _authorize(session, shop_b.id, PRODUCT_B)
    marker = await _resolve(session, shop_b, PRODUCT_B)

    resources = await composition.build_write_resources(
        session, shop_id=shop_b.id, capability=marker
    )
    assert isinstance(resources, ProductionWriteResources)
    assert composition.write_mode_of(resources) == WRITE_MODE_LIVE
    (config,) = transport.configs
    assert config.merchant_auth_id == "merchant-b"
    assert config.access_token == "token-b"
    assert config.shop_cipher == "cipher-b"

    # The same capability can never build shop A's client.
    with pytest.raises(ProductionWriteBindingError):
        await composition.build_write_resources(session, shop_id=shop_a.id, capability=marker)
    # Without a capability it is the sandbox, exactly as before. (composition binds the
    # loader at import, so the recorder is bound there too, whatever the import order.)
    monkeypatch.setattr(composition, "load_sandbox_write_resources", sandbox)
    assert await composition.build_write_resources(session) is SANDBOX
    assert composition.write_mode_of(SANDBOX) == WRITE_MODE_SIMULATED


# --- the listing handlers -------------------------------------------------------------


def _payload(shop, product, *, run=None, **extra):
    payload = {
        "_execution_shop_id": str(shop.id),
        "_execution_id": str(uuid.uuid4()),
        "product_id": product,
        "edit_body": {"title": f"New title {product}"},
        **extra,
    }
    if run is not None:
        payload["_execution_workflow_run_id"] = str(run.id)
    return payload


async def test_flags_off_runs_the_sandbox_chain_and_says_simulated(
    session, shops, sandbox, monkeypatch
):
    from juli_backend.services.execution import listing_handlers

    chain = []
    monkeypatch.setattr(
        listing_handlers,
        "run_optimize_product_chain",
        lambda resources, payload: chain.append(resources) or {"product_id": payload["product_id"]},
    )
    shop_a, _ = shops["a"]
    outcome = await listing_handlers.optimize_product_handler(session, _payload(shop_a, PRODUCT_A))
    assert chain == [SANDBOX]
    assert outcome["write_mode"] == WRITE_MODE_SIMULATED


async def test_a_live_write_goes_through_shop_bs_credential_and_records_its_values(
    session, shops, sandbox, transport, monkeypatch, tmp_path
):
    from juli_backend.services.execution import listing_handlers

    _arm(monkeypatch, tmp_path)
    shop_b, product_b = shops["b"]
    await _enable(session, shop_b.id)
    authorization = await _authorize(session, shop_b.id, PRODUCT_B)
    run = await _run(session, shop_b, product_b)

    outcome = await listing_handlers.optimize_product_handler(
        session, _payload(shop_b, PRODUCT_B, run=run)
    )

    assert outcome["write_mode"] == WRITE_MODE_LIVE
    assert outcome["authorization_id"] == str(authorization.id)
    (edit,) = transport.writes()
    assert edit["method"] == "PUT" and edit["path"].endswith(f"/products/{PRODUCT_B}")
    assert {call["access_token"] for call in transport.calls} == {"token-b"}
    values = (await session.execute(select(RunWriteValue))).scalars().all()
    assert {(v.shop_id, v.workflow_run_id, v.field) for v in values} == {
        (shop_b.id, run.id, "title")
    }
    (title,) = values
    assert (title.before_value, title.after_value) == ("B old", f"New title {PRODUCT_B}")
    sandbox.assert_not_awaited()


@pytest.mark.parametrize("case", ["price", "create", "no_run"])
async def test_never_live_mutations_are_refused_before_an_authorization_is_spent(
    session, shops, sandbox, transport, monkeypatch, tmp_path, case
):
    from juli_backend.services.execution import listing_handlers

    _arm(monkeypatch, tmp_path)
    shop_b, product_b = shops["b"]
    await _enable(session, shop_b.id)
    run = await _run(session, shop_b, product_b)
    kind = "listing.create_hero_product" if case == "create" else OPTIMIZE
    authorization = await _authorize(session, shop_b.id, PRODUCT_B, mutation_kind=kind)

    with pytest.raises(PreconditionFailure) as refused:
        if case == "price":
            await listing_handlers.optimize_product_handler(
                session, _payload(shop_b, PRODUCT_B, run=run, price_update={"skus": []})
            )
        elif case == "create":
            await listing_handlers.create_hero_product_handler(
                session, _payload(shop_b, PRODUCT_B, run=run, category_id="1")
            )
        else:
            await listing_handlers.optimize_product_handler(session, _payload(shop_b, PRODUCT_B))
    expected = (
        PreconditionName.NO_WORKFLOW_RUN
        if case == "no_run"
        else PreconditionName.MUTATION_NOT_ALLOWED_IN_PRODUCTION
    )
    assert refused.value.precondition is expected
    assert not await _consumed(session, authorization)
    assert transport.calls == []
    assert (await session.execute(select(func.count(ProductionWriteAudit.id)))).scalar_one() == 0


async def test_the_payload_cannot_choose_which_authorization_is_spent(
    session, shops, sandbox, transport, monkeypatch, tmp_path
):
    """The mutation kind is the tool's own name: an authorization issued for a
    different mutation on the same product is never consumed by this tool."""
    from juli_backend.services.execution import listing_handlers

    _arm(monkeypatch, tmp_path)
    shop_b, product_b = shops["b"]
    await _enable(session, shop_b.id)
    run = await _run(session, shop_b, product_b)
    other = await _authorize(session, shop_b.id, PRODUCT_B, mutation_kind="something_else")
    with pytest.raises(PreconditionFailure) as refused:
        await listing_handlers.optimize_product_handler(
            session, _payload(shop_b, PRODUCT_B, run=run, mutation_kind="something_else")
        )
    assert refused.value.precondition is PreconditionName.NO_MATCHING_AUTHORIZATION
    assert not await _consumed(session, other)
    assert transport.calls == []


# --- honest UX ------------------------------------------------------------------------


async def _write_execution(session, shop, run, *, status="succeeded"):
    session.add(
        ToolExecution(
            shop_id=shop.id,
            approval_id="a",
            tool_name="update_product_listing",
            payload_json="{}",
            status=status,
            workflow_run_id=run.id,
            tool_call_id=str(uuid.uuid4()),
            operation="update_product_listing",
        )
    )
    await session.flush()


async def test_the_run_list_says_simulated_only_for_a_sandbox_run_that_wrote(session, shops):
    from juli_backend.services.agent_runs.listing import list_runs

    shop_b, product_b = shops["b"]
    wrote = await _run(session, shop_b, product_b)
    wrote.status, wrote.stop_reason, wrote.write_mode = (
        "completed",
        "final_response",
        WRITE_MODE_SIMULATED,
    )
    await _write_execution(session, shop_b, wrote)
    second = Product(
        id=uuid.uuid4(),
        shop_id=shop_b.id,
        tiktok_product_id="2003",
        name="other",
        status="ACTIVE",
        update_time=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(second)
    await session.flush()
    nothing_written = await _run(session, shop_b, second)
    nothing_written.status, nothing_written.write_mode = "completed", WRITE_MODE_SIMULATED
    await session.flush()

    items = {item.id: item for item in await list_runs(session, shop_b.id, limit=10)}
    assert items[wrote.id].simulated is True
    assert items[nothing_written.id].simulated is False

    wrote.write_mode = WRITE_MODE_LIVE
    await session.flush()
    items = {item.id: item for item in await list_runs(session, shop_b.id, limit=10)}
    assert items[wrote.id].simulated is False


def test_the_card_of_a_sandbox_run_is_simulated_not_applied():
    from types import SimpleNamespace

    from juli_backend.services.demo_decisions import card_view

    card = SimpleNamespace(status="executing", surfaced_at=None, computed_at=None)
    for mode, expected in ((WRITE_MODE_SIMULATED, "simulated"), (WRITE_MODE_LIVE, "applied")):
        context = SimpleNamespace(
            latest_run=SimpleNamespace(status="completed", write_mode=mode),
            writes=[object()],
            product=None,
        )
        assert card_view._status(card, {}, context, datetime.now(UTC)) == expected


def test_the_demo_copy_never_says_applied_for_a_simulated_run():
    copy = (ROOT / "apps/demo/src/lib/quyet-dinh/simulated-copy.ts").read_text("utf-8")
    assert "Đã chạy thử" in copy
    assert "Đã áp dụng" not in copy and "đã cập nhật" not in copy.lower()
    run_model = (ROOT / "apps/demo/src/lib/quyet-dinh/run-model.ts").read_text("utf-8")
    assert run_model.count("run.simulated ?") == 2


# --- measurement ----------------------------------------------------------------------


async def test_the_impact_reader_skips_sandbox_writes(session, shops):
    from juli_backend.workers.impact_reader.pipeline import run_daily_impact_reader

    shop_b, product_b = shops["b"]
    t = date(2026, 1, 15)
    stamp = datetime(t.year, t.month, t.day, 12, tzinfo=UTC)
    payload = json.dumps({"product_id": PRODUCT_B, "title": "New"})
    simulated_run = await _run(session, shop_b, product_b)
    simulated_run.write_mode = WRITE_MODE_SIMULATED
    simulated_run.status = "completed"
    by_run = ToolExecution(
        shop_id=shop_b.id,
        approval_id="r",
        tool_name="update_product_listing",
        payload_json=payload,
        status="succeeded",
        workflow_run_id=simulated_run.id,
        updated_at=stamp,
    )
    by_outcome = ToolExecution(
        shop_id=shop_b.id,
        approval_id="o",
        tool_name=OPTIMIZE,
        payload_json=payload,
        outcome_json=json.dumps({"write_mode": WRITE_MODE_SIMULATED}),
        status="succeeded",
        updated_at=stamp,
    )
    legacy = ToolExecution(
        shop_id=shop_b.id,
        approval_id="l",
        tool_name=OPTIMIZE,
        payload_json=payload,
        status="succeeded",
        updated_at=stamp,
    )
    session.add_all([by_run, by_outcome, legacy])
    await session.flush()

    result = await run_daily_impact_reader(session, t + timedelta(days=20))

    assert result.executions_skipped_simulated == 2
    measured = set((await session.execute(select(ImpactReading.tool_execution_id))).scalars().all())
    assert by_run.id not in measured and by_outcome.id not in measured
    assert legacy.id in measured


async def test_a_simulated_listing_run_has_no_measurement(session, shops):
    from juli_backend.services import lever_flows

    shop_b, product_b = shops["b"]
    run = await _run(session, shop_b, product_b)
    run.status, run.write_mode = "completed", WRITE_MODE_SIMULATED
    await session.flush()
    with pytest.raises(lever_flows.NotMeasurable) as refused:
        await lever_flows.measure_run(session, shop_b.id, run)
    assert refused.value.code == "simulated"
    assert "chạy thử" in refused.value.message_vi


# --- schema pins ----------------------------------------------------------------------


def test_migration_097_pins_the_model_and_stays_under_the_cleanup():
    text = (MIGRATIONS / "versions/097_production_write_shops.py").read_text("utf-8")
    assert 'revision: str = "097_production_write_shops"' in text
    assert len("097_production_write_shops") <= 32
    assert 'WRITE_MODES = ("live", "simulated")' in text
    assert WRITE_MODES == ("live", "simulated")
    assert "GRANT SELECT ON public.{TABLE} TO {APP_ROLE}" in text
    assert "INSERT" not in text.split("def upgrade", 1)[1].split("def downgrade", 1)[0]
    deferred = (MIGRATIONS / "deferred/074_users_placeholder_phone_cleanup.py").read_text("utf-8")
    assert 'down_revision: str | None = "101_write_mode_backfill"' in deferred

    from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP

    assert TABLE_CLASSIFICATION_MAP[("public", "production_write_shops")] == "tenant_direct"
    assert {c.name for c in ProductionWriteShop.__table__.columns} == {
        "shop_id",
        "enabled_by",
        "reason",
        "enabled_at",
    }
    assert "write_mode" in WorkflowRun.__table__.columns


@pytest.mark.parametrize(
    ("before", "after", "intended"),
    [
        ({"title": "a", "description": "d"}, {"title": "b", "description": "d"}, {}),
        ({"title": "a"}, {"title": "a"}, {"title": "sent"}),
        ({"title": " a "}, {"title": "a"}, {"title": "a"}),
        (
            {"main_images": [{"uri": "u1"}]},
            {"main_images": [{"uri": "u2"}]},
            {"description": "x"},
        ),
    ],
)
def test_the_production_listing_diff_matches_the_agents(before, after, intended):
    from juli_backend.services.agent.runner.write_capture import (
        LISTING_OPERATION,
        diff_write,
        field_values,
    )
    from juli_backend.services.execution.production_write import (
        LISTING_WRITE_TOOL_NAME,
        diff_listing_write,
    )

    assert LISTING_WRITE_TOOL_NAME == LISTING_OPERATION
    agent = diff_write(
        LISTING_OPERATION,
        before=field_values(LISTING_OPERATION, before),
        after=field_values(LISTING_OPERATION, after),
        intended=intended,
    )
    assert diff_listing_write(before=before, after=after, intended=intended) == [
        (w.field, w.before, w.after, w.after_source) for w in agent
    ]
