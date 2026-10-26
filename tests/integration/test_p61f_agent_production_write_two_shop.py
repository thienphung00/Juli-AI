"""Two shops, real Postgres, as `juli_app`: the AGENT run's confirmed write goes live for
the enabled shop only (fast track P61-F, D71.2).

Every ADR-085 gate is armed for both shops (global flag on, kill switch off, RLS boot
check recorded, release attested, an unconsumed `update_product_listing` authorization
for each shop's product). Only shop B has a `production_write_shops` row. Then, through
the real worker seam (`agent_workflow._construct_runner`, resume leg, seller approved),
the real resolver, the real per-shop credential resolver, the real guarded production
client, the real `ProductToolExecutor` with its real ledger and `run_write_values`
recorder -- and only the HTTP session replaced by `FakeTikTokTransport`:

- shop B's confirmed listing edit goes out under B's own token, B alone gets an allowed
  `production_write_audit` row and `run_write_values`, B's authorization is consumed, and
  B's run is `write_mode='live'` (settled: the write reached the ledger);
- shop A (no enable row) takes the sandbox: nothing reaches the production client, A's
  authorization is untouched, A has no audit row, and A's run is `simulated`;
- a price confirmation on the enabled shop is refused by name (audited) before its
  authorization is spent, and the run is `simulated`;
- the deferred migration 101 backfill, run on the real `workflow_runs` table, marks a
  pre-097 sandbox run `simulated` and leaves a live run, an unstamped no-write run and an
  already-stamped run alone; it is idempotent and its downgrade is a no-op.
"""

from __future__ import annotations

import importlib.util
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.integrations.tiktok import ProductionWriteClientFactory
from juli_backend.services.agent import composition, write_approval
from juli_backend.services.agent.runner.concurrency import (
    capture_basis_snapshot,
    extract_mutable_fields,
)
from juli_backend.services.agent.tools.product_write import UpdateProductListingInput
from juli_backend.services.execution import production_write as production_write_module
from juli_backend.services.execution.production_write_resolver import (
    record_rls_boot_check_passed,
)
from juli_backend.workers.tasks import agent_workflow
from tests.integration.two_tenant import RUNTIME_ROLE
from tests.support.fakes import FakeTikTokTransport

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

LISTING = "update_product_listing"
PRICE = "update_product_price"
CALL_ID = "call-p61f-1"
#: Per tenant: the TikTok product id, the merchant id and the token its own credential
#: carries. Test data only.
SHOP_DATA = {
    "a": ("930001", "p61f-merchant-a", "p61f-token-a"),
    "b": ("940002", "p61f-merchant-b", "p61f-token-b"),
}


#: A second product of shop B, whose run is paused on a PRICE confirmation (D13 case).
PRICE_PRODUCT = "940003"


def _listing(key: str) -> dict:
    product, _merchant, _token = SHOP_DATA[key]
    return {
        "id": product,
        "title": f"{key} old",
        "description": f"{key} desc",
        "category_chains": [{"id": "cat-1", "is_leaf": True}],
        "main_images": [{"uri": f"img-{key}"}],
        "skus": [],
    }


@asynccontextmanager
async def committing_juli_app_session(shop_id: uuid.UUID):
    """A `juli_app` async session scoped to one shop whose commits really commit."""
    from juli_backend.core.config.runtime import async_database_url

    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
            await conn.execute(
                text("SELECT set_config('app.current_shop_id', :v, false)").bindparams(
                    v=str(shop_id)
                )
            )
            await conn.commit()
            session = AsyncSession(bind=conn, expire_on_commit=False)
            try:
                yield session
            finally:
                await session.close()
    finally:
        await engine.dispose()


def _seed_run(
    conn, tenant, key: str, *, tool: str, mutation_kind: str, product_tt: str | None = None
) -> dict:
    """A paused run of the tenant's product with the pending confirmation, plus an
    unconsumed authorization for `mutation_kind` on that product."""
    now = datetime.now(UTC).replace(tzinfo=None)
    product_tt = product_tt or SHOP_DATA[key][0]
    product_id, run_id, auth_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    listing = _listing(key)
    conn.execute(
        text(
            "INSERT INTO public.products (id, shop_id, tiktok_product_id, name, status,"
            " revenue, units_sold, update_time, created_at, updated_at) VALUES (:id,"
            " :shop, :tt, 'p61f', 'ACTIVE', 0, 0, :now, :now, :now)"
        ),
        {"id": str(product_id), "shop": str(tenant.shop_id), "tt": product_tt, "now": now},
    )
    state = {
        "basis_snapshots": capture_basis_snapshot(extract_mutable_fields(listing)),
        "product_detail": listing,
        "pending_confirmation": {
            "call_id": CALL_ID,
            "tool_name": tool,
            "arguments": {"title": f"{key} new title"},
        },
    }
    # ADR-116 §6 (D76): the shop owner's CONFIRM click, as decide_confirmation freezes it.
    state["pending_confirmation"][write_approval.APPROVED_CHANGE_KEY] = (
        write_approval.approved_change_block(
            state, decided_by_user_id=tenant.user_id, decided_at=now, card_approval=None
        )
    )
    conn.execute(
        text(
            "INSERT INTO public.workflow_runs (id, shop_id, product_id, state, status,"
            " prompt_version, prompt_sha256, running_seconds_elapsed, cancel_requested,"
            " subject_ref, created_at, updated_at) VALUES (:id, :shop, :product, CAST(:state"
            " AS jsonb), 'waiting_approval', 'optimize_product.v3', :sha, 0, false, :product,"
            " :now, :now)"
        ),
        {
            "id": str(run_id),
            "shop": str(tenant.shop_id),
            "product": str(product_id),
            "state": json.dumps(state),
            "sha": "0" * 64,
            "now": now,
        },
    )
    conn.execute(
        text(
            "INSERT INTO public.production_write_authorizations (id, shop_id,"
            " tiktok_product_id, mutation_kind, authorized_by, expires_at, created_at)"
            " VALUES (:id, :shop, :tt, :kind, 'owner', :expires, :now)"
        ),
        {
            "id": str(auth_id),
            "shop": str(tenant.shop_id),
            "tt": product_tt,
            "kind": mutation_kind,
            "expires": now + timedelta(hours=1),
            "now": now,
        },
    )
    return {"shop_id": tenant.shop_id, "run_id": run_id, "auth_id": auth_id}


@pytest.fixture(scope="module")
def seeded(owner_engine, two_tenants):
    """Per tenant: its own write credential and a paused run awaiting the listing edit.
    Shop B (only) is turned on. A third paused run (shop B, pending PRICE) for the D13 case."""
    now = datetime.now(UTC).replace(tzinfo=None)
    rows = {}
    with owner_engine.begin() as conn:
        for key, tenant in zip(("a", "b"), two_tenants, strict=True):
            _product, merchant, token = SHOP_DATA[key]
            conn.execute(
                text(
                    "INSERT INTO public.tiktok_credentials (id, shop_id, merchant_authorization_id,"
                    " capability, shop_cipher, access_token, refresh_token, token_expires_at,"
                    " status, refresh_count, created_at, updated_at) VALUES (:id, :shop,"
                    " :merchant, 'seller_connect', :cipher, :token, 'refresh', :expires,"
                    " 'active', 0, :now, :now)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "shop": str(tenant.shop_id),
                    "merchant": merchant,
                    "cipher": f"cipher-{key}",
                    "token": token,
                    "expires": now + timedelta(days=30),
                    "now": now,
                },
            )
            rows[key] = _seed_run(conn, tenant, key, tool=LISTING, mutation_kind=LISTING)
        rows["b_price"] = _seed_run(
            conn, two_tenants[1], "b", tool=PRICE, mutation_kind=PRICE, product_tt=PRICE_PRODUCT
        )
        conn.execute(
            text(
                "INSERT INTO public.production_write_shops (shop_id, enabled_by, reason)"
                " VALUES (:shop, 'owner', 'P61-F two-shop proof')"
            ),
            {"shop": str(rows["b"]["shop_id"])},
        )
    return rows


class _SandboxStub:
    """Stands in for the sandbox merchant's write resources: records every call."""

    def __init__(self, listing: dict) -> None:
        self.listing = dict(listing)
        self.edits: list[dict] = []
        outer = self

        class _Products:
            def get_details(self, product_id):
                return dict(outer.listing)

            def edit(self, *, product_id, body):
                outer.edits.append(body)
                outer.listing.update(
                    {k: v for k, v in body.items() if k in ("title", "description")}
                )
                return {}

        self.products = _Products()


@pytest.fixture
def armed(monkeypatch, tmp_path):
    """Every global ADR-085 gate on, a fake transport behind the real production factory,
    and the collaborators that have nothing to do with the write replaced."""
    sha = "c" * 40
    attestations = tmp_path / "attestations"
    attestations.mkdir()
    (attestations / f"{sha}.json").write_text(
        json.dumps({"release_sha": sha, "outcome": "pass", "performed_by": "test"})
    )
    monkeypatch.setenv("PRODUCTION_WRITE_ENABLED", "true")
    monkeypatch.setenv("PRODUCTION_WRITE_KILL_SWITCH", "false")
    monkeypatch.setenv("PRODUCTION_WRITE_ATTESTATION_DIR", str(attestations))
    monkeypatch.setenv("RELEASE_SHA", sha)
    monkeypatch.setenv("TIKTOK_APP_KEY", "app-key")
    monkeypatch.setenv("TIKTOK_APP_SECRET", "app-secret")
    record_rls_boot_check_passed()

    transport = FakeTikTokTransport({_listing(k)["id"]: _listing(k) for k in SHOP_DATA})

    class _Factory(ProductionWriteClientFactory):
        def create(self, config):
            client = super().create(config)
            client._session = transport
            return client

    monkeypatch.setattr(production_write_module, "ProductionWriteClientFactory", _Factory)

    sandboxes: dict[str, _SandboxStub] = {}

    async def _sandbox_resources(session):
        stub = _SandboxStub(_listing("a"))
        sandboxes["last"] = stub
        return stub

    async def _read_resources(session, shop_id=None):
        return object()

    monkeypatch.setattr(agent_workflow, "_default_write_resources", _sandbox_resources)
    monkeypatch.setattr(agent_workflow, "_default_read_resources", _read_resources)
    monkeypatch.setattr(agent_workflow, "_default_llm_service", lambda: object())
    yield transport, sandboxes
    from juli_backend.services.execution import production_write_resolver

    production_write_resolver._RLS_BOOT_CHECK_PASSED = False


def _scalar(owner_engine, sql: str, **params):
    with owner_engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


def _rows(owner_engine, sql: str, **params):
    with owner_engine.connect() as conn:
        return conn.execute(text(sql), params).all()


def _consumed(owner_engine, auth_id) -> bool:
    return (
        _scalar(
            owner_engine,
            "SELECT consumed_at FROM public.production_write_authorizations WHERE id = :id",
            id=str(auth_id),
        )
        is not None
    )


def _write_mode(owner_engine, run_id):
    return _scalar(
        owner_engine, "SELECT write_mode FROM public.workflow_runs WHERE id = :id", id=str(run_id)
    )


async def _resume_leg(row: dict, params: UpdateProductListingInput | None = None):
    """The resume leg of an APPROVED pending confirmation, up to and including the write.

    `_construct_runner` is the worker's own seam; the confirmed call is dispatched through
    the executor it built (what `WorkflowRunner.resume` does after the consent checks),
    and the leg is settled the way `_LiveLegRunner.resume` settles it.
    """
    shop_id = row["shop_id"]
    async with committing_juli_app_session(shop_id) as session:
        async with agent_workflow._scoped_ledger_session(shop_id) as sync_session:
            run, product = await agent_workflow._load_context(session, row["run_id"])
            runner = await agent_workflow._construct_runner(
                session, sync_session, run, product, resume_approved=True
            )
            result = None
            if params is not None:
                result = runner._tool_executor.execute(
                    tool_name=LISTING, params=params, tool_call_id=CALL_ID
                )
            sync_session.commit()
            if isinstance(runner, agent_workflow._LiveLegRunner):
                await composition.settle_live_write_mode(
                    session, run_id=run.id, tool_call_id=CALL_ID
                )
            await session.commit()
            return runner, result


async def test_shop_a_without_its_enable_row_runs_the_confirmed_edit_on_the_sandbox(
    owner_engine, seeded, armed
):
    transport, sandboxes = armed
    shop_a = seeded["a"]["shop_id"]

    runner, _result = await _resume_leg(seeded["a"], UpdateProductListingInput(title="a new title"))

    assert not isinstance(runner, agent_workflow._LiveLegRunner)
    assert sandboxes["last"].edits and sandboxes["last"].listing["title"] == "a new title"
    assert transport.calls == []  # nothing reached the production client
    assert not _consumed(owner_engine, seeded["a"]["auth_id"])
    assert (
        _rows(
            owner_engine,
            "SELECT 1 FROM public.production_write_audit WHERE shop_id = :s",
            s=str(shop_a),
        )
        == []
    )
    assert _write_mode(owner_engine, seeded["a"]["run_id"]) == "simulated"


async def test_shop_bs_confirmed_edit_goes_live_under_bs_credential_with_bs_rows_only(
    owner_engine, seeded, armed
):
    transport, sandboxes = armed
    shop_a, shop_b = seeded["a"]["shop_id"], seeded["b"]["shop_id"]
    product_b, _merchant_b, token_b = SHOP_DATA["b"]

    runner, _result = await _resume_leg(seeded["b"], UpdateProductListingInput(title="b new title"))

    assert isinstance(runner, agent_workflow._LiveLegRunner)
    assert "last" not in sandboxes or sandboxes["last"].edits == []
    # Every request went out under B's own token; the one write is B's listing edit.
    assert {call["access_token"] for call in transport.calls} == {token_b}
    (edit,) = transport.writes()
    assert edit["method"] == "PUT" and edit["path"].endswith(f"/products/{product_b}")
    assert transport.listings[product_b]["title"] == "b new title"
    assert transport.listings[SHOP_DATA["a"][0]]["title"] == "a old"

    # B: one allowed audit row naming its authorization and run; A: none.
    assert _rows(
        owner_engine,
        "SELECT authorization_id, precondition_name, run_id, mutation_kind"
        " FROM public.production_write_audit WHERE shop_id = :s",
        s=str(shop_b),
    ) == [(seeded["b"]["auth_id"], None, seeded["b"]["run_id"], LISTING)]
    assert (
        _scalar(
            owner_engine,
            "SELECT count(*) FROM public.production_write_audit WHERE shop_id = :s",
            s=str(shop_a),
        )
        == 0
    )
    assert _consumed(owner_engine, seeded["b"]["auth_id"])
    assert not _consumed(owner_engine, seeded["a"]["auth_id"])

    # run_write_values for B's run only, with the real before/after of the listing.
    values = _rows(
        owner_engine,
        "SELECT shop_id, workflow_run_id, field, before_value, after_value"
        " FROM public.run_write_values WHERE tiktok_product_id = ANY(:products)",
        products=[SHOP_DATA["a"][0], product_b],
    )
    assert [(v[0], v[1], v[2]) for v in values if v[0] == shop_b] == [
        (shop_b, seeded["b"]["run_id"], "title")
    ]
    assert not [v for v in values if v[0] == shop_a and v[1] == seeded["b"]["run_id"]]
    b_title = next(v for v in values if v[0] == shop_b)
    assert (b_title[3], b_title[4]) == ("b old", "b new title")

    # Each recorded field links to the allowed audit row of exactly this write.
    audit_id = _scalar(
        owner_engine,
        "SELECT id FROM public.production_write_audit WHERE shop_id = :s",
        s=str(shop_b),
    )
    assert (
        _scalar(
            owner_engine,
            "SELECT production_write_audit_id FROM public.run_write_values"
            " WHERE workflow_run_id = :r AND field = 'title'",
            r=str(seeded["b"]["run_id"]),
        )
        == audit_id
    )

    # The ledger row exists (the write reached it), so the run stays live.
    assert _rows(
        owner_engine,
        "SELECT status FROM public.tool_executions WHERE workflow_run_id = :r",
        r=str(seeded["b"]["run_id"]),
    ) == [("succeeded",)]
    assert _write_mode(owner_engine, seeded["b"]["run_id"]) == "live"


async def test_a_price_confirmation_on_the_enabled_shop_is_refused_by_name_and_spends_nothing(
    owner_engine, seeded, armed
):
    transport, _sandboxes = armed
    shop_b = seeded["b"]["shop_id"]
    calls_before = len(transport.calls)

    runner, _ = await _resume_leg(seeded["b_price"])

    assert not isinstance(runner, agent_workflow._LiveLegRunner)
    assert len(transport.calls) == calls_before
    assert not _consumed(owner_engine, seeded["b_price"]["auth_id"])
    assert _rows(
        owner_engine,
        "SELECT authorization_id, precondition_name FROM public.production_write_audit"
        " WHERE run_id = :r",
        r=str(seeded["b_price"]["run_id"]),
    ) == [(None, "mutation_not_allowed_in_production")]
    assert _write_mode(owner_engine, seeded["b_price"]["run_id"]) == "simulated"
    assert shop_b  # (the run belongs to the enabled shop)


# --- migration 101 (deferred): the write_mode backfill on the real table -----------------

BACKFILL = (
    Path(__file__).resolve().parents[2]
    / "backend/src/juli_backend/database/migrations/deferred/101_write_mode_backfill.py"
)


def _load_backfill():
    spec = importlib.util.spec_from_file_location("deferred_101_write_mode_backfill", BACKFILL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _apply(engine, fn_name: str) -> None:
    module = _load_backfill()
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            getattr(module, fn_name)()


def _seed_backfill_cases(owner_engine, tenant) -> dict[str, uuid.UUID]:
    """Runs in the states 097 left them: write_mode NULL (or stamped), with and without
    a succeeded write and a spent production authorization."""
    now = datetime.now(UTC).replace(tzinfo=None)
    runs: dict[str, uuid.UUID] = {}
    suffix = uuid.uuid4().hex[:8]
    with owner_engine.begin() as conn:
        product_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO public.products (id, shop_id, tiktok_product_id, name, status,"
                " revenue, units_sold, update_time, created_at, updated_at) VALUES (:id,"
                " :shop, :tt, 'bf', 'ACTIVE', 0, 0, :now, :now, :now)"
            ),
            {
                "id": str(product_id),
                "shop": str(tenant.shop_id),
                "tt": f"bf-{suffix}",
                "now": now,
            },
        )
        cases = {
            # name: (write_mode, tool statuses, spent_authorization)
            "sandbox_write": (None, [("update_product_listing", "succeeded")], False),
            "sandbox_image_only": (None, [("upload_product_image", "succeeded")], False),
            "dispatched_sandbox": (None, [("listing.optimize_product", "succeeded")], False),
            "live_spent_auth": (None, [("update_product_listing", "succeeded")], True),
            "live_stamped": ("live", [("update_product_listing", "succeeded")], True),
            "wrote_nothing": (None, [], False),
            "only_failed": (None, [("update_product_listing", "failed")], False),
            "other_tool": (None, [("get_product_information", "succeeded")], False),
            "already_simulated": ("simulated", [("update_product_listing", "succeeded")], False),
        }
        for name, (mode, executions, spent) in cases.items():
            run_id = uuid.uuid4()
            runs[name] = run_id
            conn.execute(
                text(
                    "INSERT INTO public.workflow_runs (id, shop_id, product_id, state, status,"
                    " prompt_version, prompt_sha256, running_seconds_elapsed, cancel_requested,"
                    " subject_ref, write_mode, created_at, updated_at) VALUES (:id, :shop,"
                    " :product, '{}', 'completed', 'optimize_product.v3', :sha, 0, false, :ref,"
                    " :mode, :now, :now)"
                ),
                {
                    "id": str(run_id),
                    "shop": str(tenant.shop_id),
                    "product": str(product_id),
                    "sha": "0" * 64,
                    "ref": f"bf-{suffix}-{name}",
                    "mode": mode,
                    "now": now,
                },
            )
            for index, (tool, status) in enumerate(executions):
                conn.execute(
                    text(
                        "INSERT INTO public.tool_executions (id, shop_id, approval_id, tool_name,"
                        " payload_json, status, workflow_run_id, tool_call_id, operation,"
                        " created_at, updated_at) VALUES (:id, :shop, 'a', :tool, '{}', :status,"
                        " :run, :call, :tool, :now, :now)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "shop": str(tenant.shop_id),
                        "tool": tool,
                        "status": status,
                        "run": str(run_id),
                        "call": f"call-{index}",
                        "now": now,
                    },
                )
            if spent:
                auth_id = uuid.uuid4()
                conn.execute(
                    text(
                        "INSERT INTO public.production_write_authorizations (id, shop_id,"
                        " tiktok_product_id, mutation_kind, authorized_by, expires_at,"
                        " consumed_at, consumed_by_run_id, created_at) VALUES (:id, :shop,"
                        " :tt, 'update_product_listing', 'owner', :expires, :now, :run, :now)"
                    ),
                    {
                        "id": str(auth_id),
                        "shop": str(tenant.shop_id),
                        "tt": f"bf-{suffix}",
                        "expires": now + timedelta(hours=1),
                        "now": now,
                        "run": str(run_id),
                    },
                )
    return runs


def test_the_backfill_marks_sandbox_written_runs_simulated_and_leaves_live_ones_alone(
    owner_engine, two_tenants
):
    runs = _seed_backfill_cases(owner_engine, two_tenants[0])

    def modes():
        return {name: _write_mode(owner_engine, run_id) for name, run_id in runs.items()}

    _apply(owner_engine, "upgrade")
    expected = {
        "sandbox_write": "simulated",
        "sandbox_image_only": "simulated",
        "dispatched_sandbox": "simulated",
        # A run that spent a production authorization went live (or tried to): not ours to call.
        "live_spent_auth": None,
        "live_stamped": "live",
        "wrote_nothing": None,
        "only_failed": None,
        "other_tool": None,
        "already_simulated": "simulated",
    }
    assert modes() == expected

    # Idempotent: a second run changes nothing; the downgrade is a no-op by design.
    _apply(owner_engine, "upgrade")
    assert modes() == expected
    _apply(owner_engine, "downgrade")
    assert modes() == expected


def test_the_backfill_never_touches_another_shops_unwritten_runs(owner_engine, two_tenants):
    """The step is a data fact per run, not per shop: a run of the other tenant that wrote
    nothing is unchanged, one that wrote to the sandbox is marked -- by its own rows only."""
    runs_a = _seed_backfill_cases(owner_engine, two_tenants[0])
    runs_b = _seed_backfill_cases(owner_engine, two_tenants[1])
    _apply(owner_engine, "upgrade")
    for runs in (runs_a, runs_b):
        assert _write_mode(owner_engine, runs["sandbox_write"]) == "simulated"
        assert _write_mode(owner_engine, runs["live_spent_auth"]) is None
        assert _write_mode(owner_engine, runs["wrote_nothing"]) is None
