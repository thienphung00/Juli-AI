"""`concurrency.py` — ADR-073 decision 4, issue #1122 / AGT-W3A.

Covers the basis-hash compare-before-write machinery `ProductToolExecutor`
(`tool_executor.py`, this same slice) routes scoped WRITE tool calls
through: per-field hash change detection, per-operation field scoping,
fail-closed rejection before signing (zero vendor calls on a mismatch), the
one-bounded-re-proposal boundary (`concurrency_conflict` on the second
mismatch), the conflict payload's LLM-safety (no hash, no raw vendor id,
passes `guard_inbound_tool_result` unchanged), `RunState.basis_snapshots`'
invisibility to the LLM, and the P1-1 partial unique index this decision
also depends on structurally.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from juli_backend.core.config.runtime import sync_database_url
from juli_backend.integrations.tiktok.factories import (
    ProductionReadResources,
    SandboxWriteResources,
)
from juli_backend.models.models import Product, Shop, User, WorkflowRun
from juli_backend.orm_base import Base
from juli_backend.services.agent.runner.concurrency import (
    ConcurrencyConflict,
    ConcurrencyExhaustedError,
    ConcurrencyGuard,
    ConcurrencyMatch,
    MutableProductFields,
    capture_basis_snapshot,
    extract_mutable_fields,
    field_scope_for,
)
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.runner.status import StopReason
from juli_backend.services.agent.runner.tool_executor import ProductToolExecutor
from juli_backend.services.agent.sanitize import guard_inbound_tool_result
from juli_backend.services.agent.tools import ToolRegistry
from juli_backend.services.agent.tools.product import (
    GetProductInformationInput,
    register_product_read_tools,
)
from juli_backend.services.agent.tools.product_write import (
    UpdateProductListingInput,
    UpdateProductPriceInput,
    register_product_write_tools,
)

# --- fixtures shared across this module -------------------------------------


def _base_raw(**overrides) -> dict:
    raw = {
        "title": "A widget",
        "description": "A fine widget for sale",
        "status": "LIVE",
        "skus": [
            {"id": "vendor-sku-1", "price": {"tax_exclusive_price": "10000", "currency": "VND"}}
        ],
        "main_images": [{"uri": "vendor-image-uri-1", "width": 800, "height": 800}],
    }
    raw.update(overrides)
    return raw


def _fields(**overrides) -> MutableProductFields:
    return extract_mutable_fields(_base_raw(**overrides))


# --- AC: the basis hash changes iff one of the four mutable fields changes -


class TestBasisHashChangeDetection:
    def test_hash_changes_when_title_changes(self):
        base = capture_basis_snapshot(_fields())
        changed = capture_basis_snapshot(_fields(title="A different widget"))
        assert changed["title"] != base["title"]
        assert changed["description"] == base["description"]
        assert changed["price"] == base["price"]
        assert changed["images"] == base["images"]

    def test_hash_changes_when_description_changes(self):
        base = capture_basis_snapshot(_fields())
        changed = capture_basis_snapshot(_fields(description="A totally different description"))
        assert changed["description"] != base["description"]
        assert changed["title"] == base["title"]
        assert changed["price"] == base["price"]
        assert changed["images"] == base["images"]

    def test_hash_changes_when_price_changes(self):
        base = capture_basis_snapshot(_fields())
        changed = capture_basis_snapshot(
            _fields(
                skus=[
                    {
                        "id": "vendor-sku-1",
                        "price": {"tax_exclusive_price": "99999", "currency": "VND"},
                    }
                ]
            )
        )
        assert changed["price"] != base["price"]
        assert changed["title"] == base["title"]
        assert changed["description"] == base["description"]
        assert changed["images"] == base["images"]

    def test_hash_changes_when_images_change(self):
        base = capture_basis_snapshot(_fields())
        changed = capture_basis_snapshot(_fields(main_images=[{"uri": "a-different-image-uri"}]))
        assert changed["images"] != base["images"]
        assert changed["title"] == base["title"]
        assert changed["description"] == base["description"]
        assert changed["price"] == base["price"]

    def test_hash_is_unaffected_by_an_out_of_scope_field(self):
        """`status` is not one of the four mutable fields — `extract_mutable_fields`
        structurally cannot see it (MutableProductFields has no such attribute),
        so a status change can never move the basis hash."""
        base = capture_basis_snapshot(_fields(status="LIVE"))
        changed = capture_basis_snapshot(_fields(status="FROZEN"))
        assert changed == base

    def test_snapshot_is_deterministic_across_independent_reads(self):
        """Two reads of an unchanged product hash identically — the basis
        the very first write compares against must be stable."""
        assert capture_basis_snapshot(_fields()) == capture_basis_snapshot(_fields())


# --- AC: compare-before-write is scoped to only the fields the specific ---
# write mutates --------------------------------------------------------------


class TestPerOperationFieldScoping:
    def test_price_scope_is_price_only(self):
        assert field_scope_for("update_product_price") == ("price",)

    def test_listing_scope_is_title_description_images(self):
        assert field_scope_for("update_product_listing") == ("title", "description", "images")

    def test_price_write_does_not_conflict_on_an_out_of_scope_description_edit(self):
        """The core proof this issue names explicitly: a price-only write
        must not conflict because the seller edited the description."""
        guard = ConcurrencyGuard(basis_snapshot=capture_basis_snapshot(_fields()))
        seller_edited = _fields(description="Seller changed this while we were thinking")

        result = guard.check_before_write(
            operation="update_product_price", current_fields=seller_edited
        )

        assert isinstance(result, ConcurrencyMatch)

    def test_listing_write_does_not_conflict_on_an_out_of_scope_price_edit(self):
        """And vice versa: update_product_listing's scope excludes price."""
        guard = ConcurrencyGuard(basis_snapshot=capture_basis_snapshot(_fields()))
        seller_edited = _fields(
            skus=[
                {
                    "id": "vendor-sku-1",
                    "price": {"tax_exclusive_price": "55555", "currency": "VND"},
                }
            ]
        )

        result = guard.check_before_write(
            operation="update_product_listing", current_fields=seller_edited
        )

        assert isinstance(result, ConcurrencyMatch)

    def test_price_write_conflicts_on_an_in_scope_price_edit(self):
        guard = ConcurrencyGuard(basis_snapshot=capture_basis_snapshot(_fields()))
        seller_edited = _fields(
            skus=[
                {
                    "id": "vendor-sku-1",
                    "price": {"tax_exclusive_price": "1", "currency": "VND"},
                }
            ]
        )

        result = guard.check_before_write(
            operation="update_product_price", current_fields=seller_edited
        )

        assert isinstance(result, ConcurrencyConflict)

    def test_listing_write_conflicts_on_an_in_scope_title_edit(self):
        guard = ConcurrencyGuard(basis_snapshot=capture_basis_snapshot(_fields()))
        seller_edited = _fields(title="Seller renamed this")

        result = guard.check_before_write(
            operation="update_product_listing", current_fields=seller_edited
        )

        assert isinstance(result, ConcurrencyConflict)


# --- AC: conflict payload is sanitized and LLM-safe -------------------------


class TestConflictPayloadIsSanitizedAndLlmSafe:
    def test_conflict_payload_shape(self):
        guard = ConcurrencyGuard(basis_snapshot=capture_basis_snapshot(_fields()))
        result = guard.check_before_write(
            operation="update_product_price",
            current_fields=_fields(
                skus=[
                    {"id": "vendor-sku-1", "price": {"tax_exclusive_price": "1", "currency": "VND"}}
                ]
            ),
        )
        assert isinstance(result, ConcurrencyConflict)
        assert result.payload["conflict"] is True
        assert "current_values" in result.payload
        assert set(result.payload["current_values"]) == {"price"}

    def test_conflict_payload_never_contains_a_raw_vendor_sku_id(self):
        guard = ConcurrencyGuard(basis_snapshot=capture_basis_snapshot(_fields()))
        result = guard.check_before_write(
            operation="update_product_price",
            current_fields=_fields(
                skus=[
                    {
                        "id": "vendor-sku-1",
                        "price": {"tax_exclusive_price": "1", "currency": "VND"},
                    }
                ]
            ),
        )
        assert "vendor-sku-1" not in repr(result.payload)

    def test_conflict_payload_never_contains_a_raw_image_uri(self):
        guard = ConcurrencyGuard(basis_snapshot=capture_basis_snapshot(_fields()))
        result = guard.check_before_write(
            operation="update_product_listing",
            current_fields=_fields(main_images=[{"uri": "vendor-image-uri-2"}]),
        )
        assert "vendor-image-uri-1" not in repr(result.payload)
        assert "vendor-image-uri-2" not in repr(result.payload)

    def test_conflict_payload_never_contains_any_basis_hash_value(self):
        basis = capture_basis_snapshot(_fields())
        guard = ConcurrencyGuard(basis_snapshot=basis)
        result = guard.check_before_write(
            operation="update_product_listing", current_fields=_fields(title="Changed")
        )
        rendered = repr(result.payload)
        for hash_value in basis.values():
            assert hash_value not in rendered

    def test_conflict_payload_passes_through_guard_inbound_tool_result_unchanged(self):
        guard = ConcurrencyGuard(basis_snapshot=capture_basis_snapshot(_fields()))
        result = guard.check_before_write(
            operation="update_product_price",
            current_fields=_fields(
                skus=[
                    {"id": "vendor-sku-1", "price": {"tax_exclusive_price": "1", "currency": "VND"}}
                ]
            ),
        )
        guarded = guard_inbound_tool_result(result.payload, tool_name="update_product_price")
        assert guarded == result.payload


# --- AC: exactly one bounded re-proposal ------------------------------------


class TestOneBoundedReproposal:
    def test_first_conflict_then_success_completes(self):
        guard = ConcurrencyGuard(basis_snapshot=capture_basis_snapshot(_fields()))
        stale = _fields(title="Seller edited while we were thinking")
        fresh = _fields()  # matches the original basis again

        first = guard.check_before_write(operation="update_product_listing", current_fields=stale)
        assert isinstance(first, ConcurrencyConflict)

        second = guard.check_before_write(operation="update_product_listing", current_fields=fresh)
        assert isinstance(second, ConcurrencyMatch)

    def test_second_conflict_on_the_same_operation_stops_with_concurrency_conflict(self):
        guard = ConcurrencyGuard(basis_snapshot=capture_basis_snapshot(_fields()))
        stale_once = _fields(title="First seller edit")
        stale_twice = _fields(title="Second, different seller edit")

        first = guard.check_before_write(
            operation="update_product_listing", current_fields=stale_once
        )
        assert isinstance(first, ConcurrencyConflict)

        with pytest.raises(ConcurrencyExhaustedError) as exc_info:
            guard.check_before_write(operation="update_product_listing", current_fields=stale_twice)

        assert exc_info.value.operation == "update_product_listing"
        assert exc_info.value.stop_reason is StopReason.CONCURRENCY_CONFLICT

    def test_bound_is_never_a_third_revalidation_attempt(self):
        """Explicit negative proof: no code path in this module ever returns
        a *third* ConcurrencyConflict for the same operation — the second
        mismatch always raises instead of returning."""
        guard = ConcurrencyGuard(basis_snapshot=capture_basis_snapshot(_fields()))
        for _ in range(5):
            try:
                result = guard.check_before_write(
                    operation="update_product_price",
                    current_fields=_fields(
                        skus=[
                            {
                                "id": "vendor-sku-1",
                                "price": {"tax_exclusive_price": "1", "currency": "VND"},
                            }
                        ]
                    ),
                )
            except ConcurrencyExhaustedError:
                return  # reached the bound — success
            assert isinstance(result, ConcurrencyConflict)
        pytest.fail(
            "guard allowed more than one conflict without raising ConcurrencyExhaustedError"
        )

    def test_conflict_bound_is_not_reset_by_a_fresh_basis_read(self):
        """A model dodging the bound by calling a READ tool between retries
        must not get a fresh two-attempt budget — see concurrency.py's
        module docstring, 'Conflict counts are monotonic'."""
        guard = ConcurrencyGuard(basis_snapshot=capture_basis_snapshot(_fields()))
        stale = _fields(title="First seller edit")

        first = guard.check_before_write(operation="update_product_listing", current_fields=stale)
        assert isinstance(first, ConcurrencyConflict)

        # The model calls get_product_information again — a fresh basis is
        # recorded, matching the seller's latest (still-changing) title.
        guard.record_basis(_fields(title="Yet another seller edit"))

        # A second mismatch against the *new* basis must still exhaust the
        # bound for this operation, not start a new two-attempt budget.
        with pytest.raises(ConcurrencyExhaustedError):
            guard.check_before_write(
                operation="update_product_listing",
                current_fields=_fields(title="A third, different value"),
            )


# --- AC: basis snapshot is invisible to the LLM -----------------------------


class TestBasisSnapshotInvisibleToTheLlm:
    def test_conversation_window_for_llm_excludes_basis_snapshots(self):
        basis = capture_basis_snapshot(_fields())
        state = RunState(
            conversation_window=[{"role": "user", "content": "optimize this listing"}],
            basis_snapshots=basis,
        )

        window = state.conversation_window_for_llm()

        assert window == [{"role": "user", "content": "optimize this listing"}]
        rendered = repr(window)
        for hash_value in basis.values():
            assert hash_value not in rendered
        for field_name in ("title", "description", "price", "images"):
            assert field_name not in rendered

    def test_run_state_to_dict_keeps_basis_snapshots_structurally_separate(self):
        """Sanity check that basis_snapshots really is a distinct top-level
        key, not something folded into conversation_window on serialize —
        the property conversation_window_for_llm relies on."""
        basis = capture_basis_snapshot(_fields())
        state = RunState(
            conversation_window=[{"role": "user", "content": "hi"}], basis_snapshots=basis
        )
        blob = state.to_dict()
        assert blob["basis_snapshots"] == basis
        assert blob["conversation_window"] == [{"role": "user", "content": "hi"}]


# --- ProductToolExecutor wiring: pre-signing rejection + zero vendor calls -


class _FakeProductsResource:
    """Stub standing in for `ProductsResource`. WRITE calls mutate `_details`
    in place — like a real vendor apply would — so a re-read after a write
    reflects the write, exactly what the post-write basis refresh relies on.
    """

    def __init__(self, *, details: dict) -> None:
        self._details = dict(details)
        self.get_details_calls: list[str] = []
        self.get_seo_words_calls: list[list[str]] = []
        self.get_suggestions_calls: list[list[str]] = []
        self.update_prices_calls: list[tuple[str, dict]] = []
        self.edit_calls: list[tuple[str, dict]] = []

    def get_details(self, product_id: str) -> dict:
        self.get_details_calls.append(product_id)
        return dict(self._details)

    def get_seo_words(self, *, product_ids: list[str]) -> dict:
        self.get_seo_words_calls.append(product_ids)
        return {"products": []}

    def get_suggestions(self, *, product_ids: list[str]) -> dict:
        self.get_suggestions_calls.append(product_ids)
        return {"products": []}

    def update_prices(self, *, product_id: str, body: dict) -> dict:
        self.update_prices_calls.append((product_id, body))
        by_id = {sku["id"]: sku for sku in body.get("skus", [])}
        skus = [dict(sku) for sku in self._details.get("skus", [])]
        for sku in skus:
            if sku.get("id") in by_id:
                new_price = by_id[sku["id"]]["price"]
                sku["price"] = {
                    "tax_exclusive_price": new_price["amount"],
                    "currency": new_price["currency"],
                }
        self._details = {**self._details, "skus": skus}
        return {}

    def edit(self, *, product_id: str, body: dict) -> dict:
        self.edit_calls.append((product_id, body))
        self._details = {**self._details, **body}
        return {}

    def set_details(self, details: dict) -> None:
        self._details = dict(details)


def _read_resources(products: _FakeProductsResource) -> ProductionReadResources:
    return ProductionReadResources(
        authorization=None,  # type: ignore[arg-type]
        orders=None,  # type: ignore[arg-type]
        products=products,  # type: ignore[arg-type]
        returns=None,  # type: ignore[arg-type]
        inventory=None,  # type: ignore[arg-type]
        analytics=None,  # type: ignore[arg-type]
        promotion=None,  # type: ignore[arg-type]
    )


def _write_resources(products: _FakeProductsResource) -> SandboxWriteResources:
    return SandboxWriteResources(
        inventory=None,  # type: ignore[arg-type]
        products=products,  # type: ignore[arg-type]
        fulfillment=None,  # type: ignore[arg-type]
        promotion=None,  # type: ignore[arg-type]
    )


def _full_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    return registry


class _FakeLedger:
    """Mirrors test_agent_runner_ledger.py's `_FakeLedger` double — the
    ledger boundary criterion 4 ("the P1-5 ledger path is invoked exactly
    as it would be without this slice present") spies on."""

    def __init__(self) -> None:
        self.execute_write_calls: list[dict] = []

    def execute_write(
        self, *, workflow_run_id, tool_call_id, operation, perform, verify_applied=None
    ):
        self.execute_write_calls.append(
            {
                "workflow_run_id": workflow_run_id,
                "tool_call_id": tool_call_id,
                "operation": operation,
            }
        )
        return perform()


class TestConcurrencyGuardWiringOnMatch:
    def test_hash_match_proceeds_to_the_ledger_unchanged(self):
        products = _FakeProductsResource(details=_base_raw())
        ledger = _FakeLedger()
        guard = ConcurrencyGuard(basis_snapshot=capture_basis_snapshot(_fields()))
        executor = ProductToolExecutor(
            registry=_full_registry(),
            write_resources=_write_resources(products),
            product_id="p1",
            sku_refs={"S1": "vendor-sku-1"},
            ledger=ledger,
            workflow_run_id=uuid.uuid4(),
            concurrency_guard=guard,
        )
        params = UpdateProductPriceInput.model_validate(
            {"skus": [{"sku_ref": "S1", "amount": "10000", "currency": "VND"}]}
        )

        result = executor.execute(
            tool_name="update_product_price", params=params, tool_call_id="call-1"
        )

        assert len(ledger.execute_write_calls) == 1
        assert ledger.execute_write_calls[0]["operation"] == "update_product_price"
        assert products.update_prices_calls  # perform() actually ran
        assert "conflict" not in result

    def test_hash_match_without_a_ledger_dispatches_directly(self):
        """Same match path, no ledger configured — proceeds exactly like a
        pre-#1122 direct dispatch."""
        products = _FakeProductsResource(details=_base_raw())
        guard = ConcurrencyGuard(basis_snapshot=capture_basis_snapshot(_fields()))
        executor = ProductToolExecutor(
            registry=_full_registry(),
            write_resources=_write_resources(products),
            product_id="p1",
            sku_refs={"S1": "vendor-sku-1"},
            concurrency_guard=guard,
        )
        params = UpdateProductPriceInput.model_validate(
            {"skus": [{"sku_ref": "S1", "amount": "10000", "currency": "VND"}]}
        )

        executor.execute(tool_name="update_product_price", params=params)

        assert products.update_prices_calls


class TestConcurrencyGuardWiringOnMismatch:
    def test_mismatch_rejects_before_signing_zero_vendor_calls_and_zero_ledger_calls(self):
        products = _FakeProductsResource(details=_base_raw())
        ledger = _FakeLedger()
        # Basis captured from a *different* price than what the fake now holds.
        stale_basis = capture_basis_snapshot(
            _fields(
                skus=[
                    {
                        "id": "vendor-sku-1",
                        "price": {"tax_exclusive_price": "1", "currency": "VND"},
                    }
                ]
            )
        )
        guard = ConcurrencyGuard(basis_snapshot=stale_basis)
        executor = ProductToolExecutor(
            registry=_full_registry(),
            write_resources=_write_resources(products),
            product_id="p1",
            sku_refs={"S1": "vendor-sku-1"},
            ledger=ledger,
            workflow_run_id=uuid.uuid4(),
            concurrency_guard=guard,
        )
        params = UpdateProductPriceInput.model_validate(
            {"skus": [{"sku_ref": "S1", "amount": "10000", "currency": "VND"}]}
        )

        result = executor.execute(
            tool_name="update_product_price", params=params, tool_call_id="call-1"
        )

        assert result["conflict"] is True
        assert products.update_prices_calls == []  # zero vendor WRITE calls
        assert ledger.execute_write_calls == []  # ledger/perform never reached

    def test_second_mismatch_on_the_same_operation_raises_and_still_makes_zero_vendor_calls(self):
        products = _FakeProductsResource(details=_base_raw())
        stale_basis = capture_basis_snapshot(
            _fields(
                skus=[
                    {
                        "id": "vendor-sku-1",
                        "price": {"tax_exclusive_price": "1", "currency": "VND"},
                    }
                ]
            )
        )
        guard = ConcurrencyGuard(basis_snapshot=stale_basis)
        executor = ProductToolExecutor(
            registry=_full_registry(),
            write_resources=_write_resources(products),
            product_id="p1",
            sku_refs={"S1": "vendor-sku-1"},
            concurrency_guard=guard,
        )
        params = UpdateProductPriceInput.model_validate(
            {"skus": [{"sku_ref": "S1", "amount": "10000", "currency": "VND"}]}
        )

        first = executor.execute(tool_name="update_product_price", params=params)
        assert first["conflict"] is True

        with pytest.raises(ConcurrencyExhaustedError):
            executor.execute(tool_name="update_product_price", params=params)

        assert products.update_prices_calls == []

    def test_listing_mismatch_never_calls_edit(self):
        products = _FakeProductsResource(details=_base_raw())
        stale_basis = capture_basis_snapshot(_fields(title="Stale title from earlier read"))
        guard = ConcurrencyGuard(basis_snapshot=stale_basis)
        executor = ProductToolExecutor(
            registry=_full_registry(),
            write_resources=_write_resources(products),
            product_id="p1",
            concurrency_guard=guard,
        )
        params = UpdateProductListingInput.model_validate({"title": "Agent-proposed title"})

        result = executor.execute(tool_name="update_product_listing", params=params)

        assert result["conflict"] is True
        assert products.edit_calls == []


class TestConcurrencyGuardWiringBasisCapture:
    def test_get_product_information_records_the_basis(self):
        products = _FakeProductsResource(details=_base_raw())
        guard = ConcurrencyGuard()
        executor = ProductToolExecutor(
            registry=_full_registry(),
            read_resources=_read_resources(products),
            product_id="p1",
            concurrency_guard=guard,
        )
        assert guard.basis_snapshot == {}

        executor.execute(tool_name="get_product_information", params=GetProductInformationInput())

        assert guard.basis_snapshot == capture_basis_snapshot(_fields())

    def test_get_seo_keywords_does_not_touch_the_guard(self):
        """Only get_product_information captures a basis — the other two
        READ tools don't return the four mutable fields at all."""
        products = _FakeProductsResource(details=_base_raw())
        guard = ConcurrencyGuard()
        executor = ProductToolExecutor(
            registry=_full_registry(),
            read_resources=_read_resources(products),
            product_id="p1",
            concurrency_guard=guard,
        )

        from juli_backend.services.agent.tools.product import GetSeoKeywordsInput

        executor.execute(tool_name="get_seo_keywords", params=GetSeoKeywordsInput())

        assert guard.basis_snapshot == {}

    def test_successful_write_refreshes_basis_so_a_second_write_does_not_self_conflict(
        self,
    ):
        products = _FakeProductsResource(details=_base_raw())
        guard = ConcurrencyGuard(basis_snapshot=capture_basis_snapshot(_fields()))
        executor = ProductToolExecutor(
            registry=_full_registry(),
            write_resources=_write_resources(products),
            product_id="p1",
            sku_refs={"S1": "vendor-sku-1"},
            concurrency_guard=guard,
        )
        params = UpdateProductPriceInput.model_validate(
            {"skus": [{"sku_ref": "S1", "amount": "20000", "currency": "VND"}]}
        )

        first = executor.execute(tool_name="update_product_price", params=params)
        assert "conflict" not in first

        # `_FakeProductsResource.update_prices` already mutated `_details`
        # in place to reflect the just-written price, exactly like a real
        # vendor apply would — no manual simulation needed here. Without the
        # post-write basis refresh, this second same-operation write would
        # spuriously conflict against the now-stale (pre-write) basis.
        second = executor.execute(tool_name="update_product_price", params=params)
        assert "conflict" not in second
        assert len(products.update_prices_calls) == 2


# --- AC: P1-1's partial unique index prevents a second Juli-initiated run --
# on the same (shop_id, product_id) -- tested without ever constructing or
# invoking a WorkflowRunner ---------------------------------------------------


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def _postgres_reachable() -> bool:
    url = _database_url()
    if not url.startswith("postgresql"):
        return False
    try:
        engine = create_engine(
            sync_database_url(url), pool_pre_ping=True, connect_args={"connect_timeout": 3}
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


_BACKEND_PARAMS = [
    "sqlite",
    pytest.param(
        "postgres",
        marks=pytest.mark.skipif(
            not _postgres_reachable(),
            reason="DATABASE_URL is not set to a reachable Postgres instance.",
        ),
    ),
]

_SQLITE_SCHEMA_TRANSLATE_MAP = {"ops": None, "bronze": None, "gold": None, "silver": None}


@pytest.fixture(scope="module")
def _disposable_postgres_url():
    base_url = _database_url()
    if not base_url.startswith("postgresql"):
        yield None
        return

    admin_url = make_url(sync_database_url(base_url)).set(database="postgres")
    db_name = f"juli_concurrency_test_{uuid.uuid4().hex[:12]}"

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin_engine.dispose()

    disposable_url = make_url(sync_database_url(base_url)).set(database=db_name)
    try:
        # `str(URL)` masks the password as `***` (SQLAlchemy renders it that way
        # deliberately so URLs are log-safe), and this value goes straight to
        # `create_engine`, so every connection would authenticate with a literal
        # `***`. Same defect as #1121's and #1131's copies of this fixture.
        yield disposable_url.render_as_string(hide_password=False)
    finally:
        admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": db_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        admin_engine.dispose()


def _build_postgres_engine(url: str):
    engine = create_engine(url, pool_pre_ping=True)
    with engine.begin() as conn:
        for schema_name in ("bronze", "silver", "gold", "ops"):
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))
    Base.metadata.create_all(engine, checkfirst=True)
    return engine


@pytest.fixture(params=_BACKEND_PARAMS)
def sync_engine(request, _disposable_postgres_url):
    if request.param == "sqlite":
        engine = create_engine(
            "sqlite:///:memory:",
            execution_options={"schema_translate_map": _SQLITE_SCHEMA_TRANSLATE_MAP},
        )
        Base.metadata.create_all(engine, checkfirst=True)
    else:
        engine = _build_postgres_engine(_disposable_postgres_url)
    yield engine
    engine.dispose()


@pytest.fixture
def session(sync_engine) -> Session:
    factory = sessionmaker(bind=sync_engine)
    sess = factory()
    yield sess
    sess.close()


@pytest.fixture
def postgres_only_session(_disposable_postgres_url) -> Session:
    """Postgres-only, never parametrized over SQLite — for the "a terminal
    run does not block a new active one" proof, which specifically exercises
    the index's `postgresql_where` partial predicate. SQLite has no partial
    index support at all: SQLAlchemy's `postgresql_where` DDL argument is a
    Postgres-only kwarg the SQLite dialect silently ignores, so on SQLite
    this index is unconditionally unique over (shop_id, product_id) — it
    would *always* reject a second row regardless of status, which is not
    what this test proves. Skips cleanly when DATABASE_URL is not a
    reachable Postgres instance, mirroring test_agent_runner_ledger.py's
    `postgres_only_session_factory` convention.
    """
    if _disposable_postgres_url is None:
        pytest.skip(
            "DATABASE_URL is not set to a reachable Postgres instance — the partial "
            "index's postgresql_where predicate cannot be proven on SQLite."
        )
    engine = _build_postgres_engine(_disposable_postgres_url)
    factory = sessionmaker(bind=engine)
    sess = factory()
    try:
        yield sess
    finally:
        sess.close()
        engine.dispose()


def _seed_shop_and_product(session: Session) -> tuple[uuid.UUID, uuid.UUID]:
    shop_id = uuid.uuid4()
    user_id = uuid.uuid4()
    session.add(User(id=user_id, phone=f"+{uuid.uuid4().int % 10**14:014d}"))
    session.add(Shop(id=shop_id, user_id=user_id, shop_name="Concurrency Test Shop"))
    session.flush()

    product_id = uuid.uuid4()
    session.add(
        Product(
            id=product_id,
            shop_id=shop_id,
            tiktok_product_id=f"tt-{uuid.uuid4().hex[:12]}",
            name="Concurrency Test Product",
            status="ACTIVE",
            # Naive UTC: asyncpg rejects tz-aware datetimes for naive
            # DateTime columns where SQLite silently tolerates them.
            update_time=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    session.flush()
    session.commit()
    return shop_id, product_id


def _new_run(shop_id: uuid.UUID, product_id: uuid.UUID, *, status: str) -> WorkflowRun:
    return WorkflowRun(
        id=uuid.uuid4(),
        shop_id=shop_id,
        product_id=product_id,
        state={},
        status=status,
        prompt_version="v1",
        prompt_sha256="0" * 64,
    )


class TestPartialUniqueIndexPreventsAConcurrentRunOnTheSameProduct:
    """P1-1's structural half of ADR-073 decision 4: a second
    Juli-initiated run on the same (shop_id, product_id) fails at INSERT
    time while an active row exists — proven here via direct SQLAlchemy
    inserts against the real schema, never through WorkflowRunner."""

    @pytest.mark.parametrize("active_status", ["queued", "running", "waiting_approval"])
    def test_second_active_run_on_same_product_fails_at_insert(self, session, active_status):
        shop_id, product_id = _seed_shop_and_product(session)
        session.add(_new_run(shop_id, product_id, status=active_status))
        session.commit()

        session.add(_new_run(shop_id, product_id, status=active_status))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


class TestPartialUniqueIndexAllowsATerminalRunAlongsideANewOne:
    """Postgres-only (see `postgres_only_session`'s docstring) — this is
    specifically a proof of the index's `postgresql_where` predicate, which
    SQLite does not support at all."""

    @pytest.mark.parametrize("terminal_status", ["completed", "cancelled", "timed_out", "failed"])
    def test_completed_run_does_not_block_a_new_active_run(
        self, postgres_only_session, terminal_status
    ):
        session = postgres_only_session
        shop_id, product_id = _seed_shop_and_product(session)
        session.add(_new_run(shop_id, product_id, status=terminal_status))
        session.commit()

        # A new active run for the same product is allowed once the prior
        # one is terminal — the partial index only covers active statuses.
        session.add(_new_run(shop_id, product_id, status="queued"))
        session.commit()  # must not raise
