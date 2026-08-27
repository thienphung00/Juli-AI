"""`workers.impact_reader.queries.measurable_tool_names` — issue #1219 / AGT-W4B.

The defect this closes: `queries.py` used to hardcode
``MEASURABLE_TOOL_NAMES = frozenset({"listing.optimize_product"})`` — the
*old* dispatcher's own tool name. The real agent ledger
(``services/agent/runner/ledger.py``, wired through
``ProductToolExecutor.execute`` — ``tool_executor.py``) writes
``ToolExecution.tool_name`` as the *registered* ADR-069 tool name itself
(``update_product_price``, ``update_product_listing``, ...), so
``load_measurable_executions`` selected zero rows, forever, silently —
``run_daily_impact_reader`` always reported ``executions_scanned=0`` and
nothing looked wrong.

**Why this suite cannot pass with either side hardcoded.** A test that
types ``"update_product_price"`` as a literal on both the "expected
measurable name" side and the "what the ledger wrote" side would keep
passing even if ``queries.py`` reverted to the old
``listing.optimize_product``-only literal — that is exactly the shape of
test that let the original defect ship unnoticed. Every test below gets
its "which names are measurable" side from calling the real production
function (``queries.measurable_tool_names()``) and/or the real registry
(``services/agent/composition.py::build_product_tool_registry()``), and
gets its "what did the ledger actually write" side by driving a real
``ProductToolExecutor`` + real ``ToolExecutionLedger`` and reading back the
persisted ``ToolExecution.tool_name`` column — never a hand-typed stand-in
for either.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from juli_backend.integrations.tiktok.factories import SandboxWriteResources
from juli_backend.models.models import (
    ImpactReading,
    Product,
    Shop,
    ToolExecution,
    User,
    WorkflowRun,
)
from juli_backend.orm_base import Base
from juli_backend.services.agent import composition as composition_module
from juli_backend.services.agent.runner.ledger import ToolExecutionLedger
from juli_backend.services.agent.runner.tool_executor import ProductToolExecutor
from juli_backend.services.agent.tools import (
    ToolClassification,
    ToolPolicy,
    ToolRegistry,
    ToolSpec,
)
from juli_backend.services.agent.tools.product_write import (
    UpdateProductListingInput,
    UpdateProductPriceInput,
)
from juli_backend.workers.impact_reader.pipeline import run_daily_impact_reader
from juli_backend.workers.impact_reader.queries import measurable_tool_names

_SQLITE_SCHEMA_TRANSLATE_MAP = {"ops": None, "bronze": None, "gold": None, "silver": None}


# --- shared seeding / fake-resource helpers, mirroring
# --- test_agent_runner_ledger.py's own conventions -------------------------


def _seed_run(session: Session) -> tuple[uuid.UUID, uuid.UUID]:
    """Minimal valid User -> Shop -> Product -> WorkflowRun chain, so a real
    `ToolExecutionLedger.execute_write` has a valid `workflow_run_id` FK
    target — mirrors `test_agent_runner_ledger.py::_seed_run`."""
    shop_id = uuid.uuid4()
    user_id = uuid.uuid4()
    session.add(User(id=user_id, phone=f"+{uuid.uuid4().int % 10**14:014d}"))
    session.add(Shop(id=shop_id, user_id=user_id, shop_name="Measurable Set Test Shop"))
    session.flush()

    product_id = uuid.uuid4()
    session.add(
        Product(
            id=product_id,
            shop_id=shop_id,
            tiktok_product_id=f"tt-{uuid.uuid4().hex[:12]}",
            name="Measurable Set Test Product",
            status="ACTIVE",
            update_time=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    session.flush()

    run_id = uuid.uuid4()
    session.add(
        WorkflowRun(
            id=run_id,
            shop_id=shop_id,
            product_id=product_id,
            state={},
            status="running",
            prompt_version="v1",
            prompt_sha256="0" * 64,
        )
    )
    session.flush()
    session.commit()
    return shop_id, run_id


class _FakeProductsResource:
    """Stub standing in for `ProductsResource` — records calls, no HTTP."""

    def __init__(self) -> None:
        self.update_prices_calls: list[tuple[str, dict]] = []
        self.edit_calls: list[tuple[str, dict]] = []

    def update_prices(self, *, product_id: str, body: dict) -> dict:
        self.update_prices_calls.append((product_id, body))
        return {}

    def edit(self, *, product_id: str, body: dict) -> dict:
        self.edit_calls.append((product_id, body))
        return {}


def _write_resources(products: _FakeProductsResource) -> SandboxWriteResources:
    return SandboxWriteResources(
        inventory=None,  # type: ignore[arg-type]
        products=products,  # type: ignore[arg-type]
        fulfillment=None,  # type: ignore[arg-type]
        promotion=None,  # type: ignore[arg-type]
    )


def _minimal_params_for_confirm_write(tool_name: str) -> BaseModel:
    """Minimal valid input for each currently-registered CONFIRM WRITE
    tool. Deliberately raises for any name it doesn't recognize rather than
    silently skipping it — a new CONFIRM write tool must extend this, or
    the exhaustiveness proof below stops being exhaustive."""
    if tool_name == "update_product_price":
        return UpdateProductPriceInput.model_validate(
            {"skus": [{"sku_ref": "S1", "amount": "199000", "currency": "VND"}]}
        )
    if tool_name == "update_product_listing":
        return UpdateProductListingInput.model_validate(
            {"title": "New SEO Title", "description": "New description copy"}
        )
    raise AssertionError(
        f"No minimal params defined for CONFIRM write tool {tool_name!r} — extend "
        "_minimal_params_for_confirm_write so this contract test stays exhaustive."
    )


# ---------------------------------------------------------------------------
# AC2 (the deliverable), side A: the measurable set is exactly the real
# registry's WRITE-classified names plus the one legacy exception — never a
# second hand-maintained literal.
# ---------------------------------------------------------------------------


class TestMeasurableSetIsDerivedFromTheRealRegistry:
    def test_measurable_set_equals_registry_write_names_plus_legacy_name(self):
        registry = composition_module.build_product_tool_registry()
        write_names = {
            spec.name
            for spec in registry.list_all()
            if spec.classification is ToolClassification.WRITE
        }
        assert write_names  # sanity: the real registry really has WRITE tools

        assert measurable_tool_names() == write_names | {"listing.optimize_product"}

    def test_read_classified_tools_are_never_measurable(self):
        registry = composition_module.build_product_tool_registry()
        read_names = {
            spec.name
            for spec in registry.list_all()
            if spec.classification is ToolClassification.READ
        }
        assert read_names  # sanity: the real registry really has READ tools

        assert read_names.isdisjoint(measurable_tool_names())


# ---------------------------------------------------------------------------
# AC1 + AC2, side B: the real ledger's persisted `tool_name` for a real
# CONFIRM write dispatch is in the measurable set — proven by actually
# dispatching, not by asserting a literal against itself.
# ---------------------------------------------------------------------------


class TestRealLedgerDispatchLandsInTheMeasurableSet:
    def test_every_confirm_write_tools_persisted_operation_name_is_measurable(self):
        registry = composition_module.build_product_tool_registry()
        confirm_write_specs = [
            spec
            for spec in registry.list_all()
            if spec.classification is ToolClassification.WRITE and spec.policy is ToolPolicy.CONFIRM
        ]
        assert confirm_write_specs  # sanity: at least update_product_price/_listing exist

        engine = create_engine(
            "sqlite:///:memory:",
            execution_options={"schema_translate_map": _SQLITE_SCHEMA_TRANSLATE_MAP},
        )
        Base.metadata.create_all(engine, checkfirst=True)
        session = sessionmaker(bind=engine)()
        try:
            shop_id, run_id = _seed_run(session)
            ledger = ToolExecutionLedger(session, shop_id=shop_id)
            products = _FakeProductsResource()
            write_resources = _write_resources(products)
            measurable = measurable_tool_names()

            seen_operations: set[str] = set()
            for spec in confirm_write_specs:
                executor = ProductToolExecutor(
                    registry=registry,
                    write_resources=write_resources,
                    product_id="tt-contract-1",
                    sku_refs={"S1": "vendor-sku-1"},
                    product_detail={
                        "id": "tt-contract-1",
                        "title": "Test Product",
                        "description": "Test",
                        "category_chains": [{"id": "123", "is_leaf": True}],
                        "skus": [
                            {"id": "vendor-sku-1", "price": {"amount": "100", "currency": "VND"}}
                        ],
                        "package_weight": {"value": "1", "unit": "kg"},
                        # Required on every edit, not just photo changes (#1389).
                        "main_images": [{"uri": "tos-alisg-i-test/img"}],
                    },
                    ledger=ledger,
                    workflow_run_id=run_id,
                )
                params = _minimal_params_for_confirm_write(spec.name)
                tool_call_id = f"call-{spec.name}"

                executor.execute(tool_name=spec.name, params=params, tool_call_id=tool_call_id)

                row = session.execute(
                    select(ToolExecution).where(
                        ToolExecution.workflow_run_id == run_id,
                        ToolExecution.tool_call_id == tool_call_id,
                        ToolExecution.operation == spec.name,
                    )
                ).scalar_one()
                # The REAL name the REAL ledger persisted — this is the
                # `ToolExecution.tool_name` column `load_measurable_executions`
                # filters on, read back from the DB, not re-asserted against
                # `spec.name` in name only.
                seen_operations.add(row.tool_name)
                assert row.tool_name in measurable

            # The loop above was exhaustive against the real registry's own
            # CONFIRM WRITE set — nothing silently skipped.
            assert seen_operations == {spec.name for spec in confirm_write_specs}
        finally:
            session.close()
            engine.dispose()


# ---------------------------------------------------------------------------
# AC3: registering a new WRITE tool makes it measurable with NO edit to the
# reader — proven by registering one and calling the unmodified production
# function.
# ---------------------------------------------------------------------------


class _NewWriteToolInput(BaseModel):
    pass


class _NewWriteToolOutput(BaseModel):
    pass


class TestRegisteringANewWriteToolRequiresNoReaderEdit:
    def test_new_write_tool_is_measurable_purely_by_registration(self, monkeypatch):
        new_spec = ToolSpec(
            name="update_product_category",
            description=(
                "A hypothetical new WRITE capability, registered purely to prove #1219's contract."
            ),
            input_model=_NewWriteToolInput,
            output_model=_NewWriteToolOutput,
            classification=ToolClassification.WRITE,
            policy=ToolPolicy.CONFIRM,
            timeout_seconds=20,
        )

        real_build_product_tool_registry = composition_module.build_product_tool_registry

        def _registry_with_the_new_tool() -> ToolRegistry:
            registry = ToolRegistry()
            for spec in real_build_product_tool_registry().list_all():
                registry.register(spec)
            registry.register(new_spec)
            return registry

        # Standing in for "someone registered a new WRITE ToolSpec in
        # production" — the seam `queries.measurable_tool_names()` reaches
        # (`composition.build_product_tool_registry`) is what changes here,
        # never `queries.py` or `composition.py` themselves.
        monkeypatch.setattr(
            composition_module, "build_product_tool_registry", _registry_with_the_new_tool
        )

        assert "update_product_category" in measurable_tool_names()


# ---------------------------------------------------------------------------
# AC4: legacy `listing.optimize_product` rows remain measurable.
# ---------------------------------------------------------------------------


class TestLegacyToolNameStillMeasurable:
    def test_listing_optimize_product_is_still_in_the_measurable_set(self):
        assert "listing.optimize_product" in measurable_tool_names()


# ---------------------------------------------------------------------------
# AC1 + AC6, full unit-tier end-to-end: a `tool_executions` row written by a
# REAL agent run (real `ProductToolExecutor` + real `ToolExecutionLedger`,
# a real CONFIRM write) is selected by `load_measurable_executions` and the
# pipeline turns it into a written `impact_readings` row — here an explicit
# `suppressed` reading, since no daily analytics are seeded — never a skip
# and never a crash.
#
# The ledger's own module docstring documents why its DB access is a plain
# synchronous `sqlalchemy.orm.Session` while the rest of this reader uses
# `AsyncSession` — this test bridges the two backends via a shared on-disk
# SQLite file (not `:memory:`, which is private per-connection) so both
# sides durably see the same row.
# ---------------------------------------------------------------------------

_REFERENCE_T = date(2026, 1, 1)


async def test_real_agent_run_confirm_write_is_measured_end_to_end(tmp_path):
    db_path = tmp_path / "measurable_set_e2e.db"

    sync_engine = create_engine(
        f"sqlite:///{db_path}",
        execution_options={"schema_translate_map": _SQLITE_SCHEMA_TRANSLATE_MAP},
    )
    Base.metadata.create_all(sync_engine, checkfirst=True)

    sync_session = sessionmaker(bind=sync_engine)()
    shop_id, run_id = _seed_run(sync_session)

    registry = composition_module.build_product_tool_registry()
    products = _FakeProductsResource()
    executor = ProductToolExecutor(
        registry=registry,
        write_resources=_write_resources(products),
        product_id="tt-measurable-set-e2e",
        sku_refs={"S1": "vendor-sku-1"},
        ledger=ToolExecutionLedger(sync_session, shop_id=shop_id),
        workflow_run_id=run_id,
    )
    params = UpdateProductPriceInput.model_validate(
        {"skus": [{"sku_ref": "S1", "amount": "199000", "currency": "VND"}]}
    )
    executor.execute(tool_name="update_product_price", params=params, tool_call_id="call-e2e-1")

    row = sync_session.execute(
        select(ToolExecution).where(
            ToolExecution.workflow_run_id == run_id,
            ToolExecution.tool_call_id == "call-e2e-1",
            ToolExecution.operation == "update_product_price",
        )
    ).scalar_one()
    execution_id = row.id
    assert row.tool_name == "update_product_price"
    assert products.update_prices_calls  # the real handler really ran

    # ADR-077 decision 2's T proxy is `updated_at` (`queries.execution_t`),
    # bumped to "now" by the real dispatch above. Backdate it so the
    # elapse boundary this test needs has already passed — this clock
    # control is the only non-real ingredient; the row and its
    # `tool_name`/`payload_json` are entirely the product of the real
    # dispatch above.
    row.updated_at = datetime(
        _REFERENCE_T.year, _REFERENCE_T.month, _REFERENCE_T.day, 12, tzinfo=UTC
    )
    sync_session.add(row)
    sync_session.commit()
    sync_session.close()
    sync_engine.dispose()

    async_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        execution_options={"schema_translate_map": _SQLITE_SCHEMA_TRANSLATE_MAP},
    )
    try:
        async_session_factory = async_sessionmaker(async_engine, expire_on_commit=False)
        async with async_session_factory() as session:
            result = await run_daily_impact_reader(session, _REFERENCE_T + timedelta(days=14))
            await session.commit()

            # AC1: the row really was selected by load_measurable_executions.
            assert result.executions_scanned == 1
            # AC6: never a skip.
            assert result.executions_skipped_unclassified == 0
            # AC6: a written impact_readings row (an explicit suppressed
            # reading, since no AnalyticsPerformanceInterval rows exist for
            # this product — the reference-shop-only daily topup gap
            # queries.py's own docstring names).
            assert result.readings_written > 0

            readings = (
                (
                    await session.execute(
                        select(ImpactReading).where(ImpactReading.tool_execution_id == execution_id)
                    )
                )
                .scalars()
                .all()
            )
            assert readings
            assert all(reading.confidence == "suppressed" for reading in readings)
    finally:
        await async_engine.dispose()
