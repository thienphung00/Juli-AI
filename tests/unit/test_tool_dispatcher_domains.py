"""Domain-registered tool dispatch and the subject-generic tool context —
issue #1704 (W9-A/P-SHARED-4, spec P0-3).

AC1 → the product domain is migrated with zero behaviour change
      (`test_product_domain_migration_is_behaviour_preserving`, and the
      committed golden scenario, which this diff never regenerates).
AC2 → a test-only `inventory` domain's handler receives a context carrying
      the run's subject and NO product id
      (`test_non_product_domain_receives_subject_generic_context`).
AC3 → a spec with no domain is refused at import time
      (`test_domainless_spec_is_refused`).
AC4 → a WRITE-CONFIRM tool in the test domain pauses the runner at CONFIRM
      exactly as a product write does
      (`test_confirm_policy_is_domain_independent`).

## The failure mode these tests exist to catch

A refactor of dispatch fails silently in two directions: a tool that stops
being reachable, and a tool that becomes reachable from a domain it does not
belong to. A green suite shows neither, and neither does a test that asserts
against a hand-written list of tool names — that list is a second copy of the
answer, and it goes stale in the same commit that breaks the thing.

So every reachability assertion here is DERIVED twice and compared:

* the "after" set from `domain_registry.reachable_tool_names()`, which folds
  the registered domains' own handler tables;
* the "before" set from the three module-level dicts the pre-#1704 executor
  dispatched over (`PRODUCT_READ_TOOL_HANDLERS`, `PRODUCT_WRITE_TOOL_HANDLERS`,
  `TERMINAL_TOOL_HANDLERS`), which this diff did not touch;

and, tool by tool over the REAL production registry, the handler the new
dispatch resolves is asserted to be the SAME OBJECT the pre-#1704 if/elif
would have resolved — `_legacy_dispatch` below is that if/elif, copied from
the pre-change `tool_executor.py::execute._dispatch`. Nothing in this module
names a tool by hand except the two the test-only domain invents.
"""

from __future__ import annotations

import io
import re
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from juli_backend.integrations.tiktok.factories import (
    ProductionReadResources,
    SandboxWriteResources,
)
from juli_backend.models.models import Product, RunConfirmation, Shop, User, WorkflowRun
from juli_backend.services.agent import approval as approval_module
from juli_backend.services.agent.composition import build_product_tool_registry
from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.llm import AssistantTurn, ToolCallBlock, Usage
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.playbooks import (
    OPTIMIZE_PRODUCT_PLAYBOOK,
    OPTIMIZE_PRODUCT_TERMINATION_POLICY,
    Playbook,
    PlaybookStep,
)
from juli_backend.services.agent.runner.conversation_store import JsonbConversationStore
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.runner.tool_executor import (
    DomainToolExecutor,
    ProductToolExecutor,
    ToolExecutionError,
)
from juli_backend.services.agent.status import StopReason
from juli_backend.services.agent.tools.domain_registry import (
    bindable_subject_types,
    get_tool_domain,
    reachable_tool_names,
    tool_domain_registered_for_test,
)
from juli_backend.services.agent.tools.domains import (
    PRODUCT_DOMAIN,
    RunSubject,
    ToolContext,
    ToolDomain,
    ToolDomainBindingError,
    ToolNotInDomainError,
    UnregisteredToolDomainError,
)
from juli_backend.services.agent.tools.product import (
    PRODUCT_READ_TOOL_HANDLERS,
    ProductToolContext,
)
from juli_backend.services.agent.tools.product_write import PRODUCT_WRITE_TOOL_HANDLERS
from juli_backend.services.agent.tools.registry import (
    DomainlessToolError,
    ToolClassification,
    ToolPolicy,
    ToolRegistry,
    ToolSpec,
)
from juli_backend.services.agent.tools.terminal import (
    TERMINAL_TOOL_HANDLERS,
    ConcludeWithoutChangesInput,
)
from tests.support.tool_domains import (
    SKU_SET_SUBJECT_TYPE,
    TEST_INVENTORY_DOMAIN,
    TEST_INVENTORY_READ_TOOL,
    TEST_INVENTORY_WRITE_TOOL,
    InventoryToolRecorder,
    make_inventory_domain,
    register_inventory_tools,
)

# --- fake marketplace resources -------------------------------------------------
#
# Mirrors `test_agent_runner_tool_executor.py`'s own fake: records calls, no
# HTTP, and only the `products.*` methods the real handlers reach for.


class _FakeProductsResource:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def get_details(self, product_id: str) -> dict:
        self.calls.append(("get_details", product_id))
        return {
            "title": "A widget",
            "status": "LIVE",
            "category_chains": [{"id": "600001", "is_leaf": True}],
            "skus": [{"id": "vendor-sku-1"}],
            "package_weight": {"value": "1", "unit": "KILOGRAM"},
            "main_images": [{"uri": "tos://main-1"}],
        }

    def get_seo_words(self, *, product_ids: list[str]) -> dict:
        self.calls.append(("get_seo_words", tuple(product_ids)))
        return {"products": []}

    def get_suggestions(self, *, product_ids: list[str]) -> dict:
        self.calls.append(("get_suggestions", tuple(product_ids)))
        return {"products": []}

    def update_prices(self, *, product_id: str, body: dict) -> dict:
        self.calls.append(("update_prices", (product_id, body)))
        return {}

    def edit(self, *, product_id: str, body: dict) -> dict:
        self.calls.append(("edit", (product_id, body)))
        return {}

    def upload_product_image(self, *, image_bytes: bytes, filename: str) -> dict:
        # The filename's stem is a fresh `uuid4()` per call by design
        # (`screen_and_reencode_image` replaces any caller-supplied name), so
        # only its extension is comparable between two dispatches of the same
        # tool. Recording the whole name would make this fake, not the
        # dispatcher, the thing that differs.
        self.calls.append(("upload_product_image", (len(image_bytes), Path(filename).suffix)))
        return {"uri": "tos://uploaded-1"}


def _read_resources(products: _FakeProductsResource) -> ProductionReadResources:
    return ProductionReadResources(
        authorization=None,
        orders=None,
        products=products,
        returns=None,
        inventory=None,
        analytics=None,
        promotion=None,
    )


def _write_resources(products: _FakeProductsResource) -> SandboxWriteResources:
    return SandboxWriteResources(
        inventory=None,
        products=products,
        fulfillment=None,
        promotion=None,
    )


_PRODUCT_DETAIL = {
    "category_chains": [{"id": "600001", "is_leaf": True}],
    "skus": [{"id": "vendor-sku-1"}],
    "package_weight": {"value": "1", "unit": "KILOGRAM"},
    "main_images": [{"uri": "tos://main-1"}],
}

_BOUND_PRODUCT_ID = "bound-product-id"


def _valid_png_bytes() -> bytes:
    """A genuinely decodable image, so `upload_product_image` reaches its
    vendor call on both dispatch paths rather than both failing the same way
    inside `screen_and_reencode_image`. Comparing two identical refusals is a
    much weaker equivalence than comparing two identical writes."""
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(buffer, format="PNG")
    return buffer.getvalue()


_PENDING_IMAGE_BYTES = _valid_png_bytes()


def _executor_kwargs(products: _FakeProductsResource, *, resourced: bool) -> dict[str, Any]:
    """The one constructor configuration both dispatch paths are given.

    `resourced=False` is the second configuration: an executor built with no
    marketplace bundles at all, which is how the missing-resource refusal
    branches get compared as well as the happy ones.
    """
    return {
        "read_resources": _read_resources(products) if resourced else None,
        "write_resources": _write_resources(products) if resourced else None,
        "product_id": _BOUND_PRODUCT_ID,
        # "1" is what `_sample_params` fills a required `str` field with, so
        # `update_product_price` resolves its sku_ref and actually reaches the
        # vendor call rather than both paths merely failing the same way.
        "sku_refs": {"S1": "vendor-sku-1", "1": "vendor-sku-1"},
        "staged_image_uri": "tos://staged-1",
        "pending_image_bytes": _PENDING_IMAGE_BYTES,
        "image_inspector": None,
        "product_detail": _PRODUCT_DETAIL,
    }


# --- the pre-#1704 dispatch, kept as the reference implementation ---------------


def _legacy_dispatch(
    *, tool_name: str, spec: ToolSpec, params: BaseModel, kwargs: dict[str, Any]
) -> Any:
    """The if/elif `tool_executor.py::execute._dispatch` ran before #1704.

    Copied from the pre-change source rather than re-derived, so "the new
    dispatch resolves what the old one resolved" is a comparison against the
    old ALGORITHM, not against a restatement of the new one. The concurrency
    and ledger branches are absent because neither collaborator is
    configured in this comparison (`concurrency_guard=None`,
    `ledger=None`), so neither branch ran before this change either.
    """
    context = ProductToolContext(
        product_id=kwargs["product_id"],
        sku_refs=kwargs["sku_refs"],
        staged_image_uri=kwargs["staged_image_uri"],
        pending_image_bytes=kwargs["pending_image_bytes"],
        image_inspector=kwargs["image_inspector"],
        product_detail=kwargs["product_detail"],
    )

    if tool_name in TERMINAL_TOOL_HANDLERS:
        result = TERMINAL_TOOL_HANDLERS[tool_name](None, context, params)
    elif spec.classification is ToolClassification.READ:
        read_handler = PRODUCT_READ_TOOL_HANDLERS.get(tool_name)
        if read_handler is None:
            raise ToolExecutionError(
                f"Tool {tool_name!r} is registered READ but has no handler in "
                "PRODUCT_READ_TOOL_HANDLERS."
            )
        if kwargs["read_resources"] is None:
            raise ToolExecutionError(
                f"Tool {tool_name!r} requires read_resources, but this "
                "ProductToolExecutor was constructed without them."
            )
        result = read_handler(kwargs["read_resources"], context, params)
    else:
        write_handler = PRODUCT_WRITE_TOOL_HANDLERS.get(tool_name)
        if write_handler is None:
            raise ToolExecutionError(
                f"Tool {tool_name!r} is registered WRITE but has no handler in "
                "PRODUCT_WRITE_TOOL_HANDLERS."
            )
        if kwargs["write_resources"] is None:
            raise ToolExecutionError(
                f"Tool {tool_name!r} requires write_resources, but this "
                "ProductToolExecutor was constructed without them."
            )
        result = write_handler(kwargs["write_resources"], context, params)

    return result.model_dump(mode="json")


def _legacy_handler_for(spec: ToolSpec) -> Any:
    """Which handler OBJECT the pre-#1704 if/elif would have reached."""
    if spec.name in TERMINAL_TOOL_HANDLERS:
        return TERMINAL_TOOL_HANDLERS[spec.name]
    if spec.classification is ToolClassification.READ:
        return PRODUCT_READ_TOOL_HANDLERS.get(spec.name)
    return PRODUCT_WRITE_TOOL_HANDLERS.get(spec.name)


def _legacy_reachable_tool_names() -> frozenset[str]:
    """The tool names the pre-#1704 dispatch could reach, derived from the
    three literal tables it dispatched over — never a hand-written list."""
    return frozenset(
        set(PRODUCT_READ_TOOL_HANDLERS)
        | set(PRODUCT_WRITE_TOOL_HANDLERS)
        | set(TERMINAL_TOOL_HANDLERS)
    )


#: Any `0x...` in an exception message is an allocation address from some
#: object's `repr` (PIL's "cannot identify image file <_io.BytesIO object at
#: 0x...>" is the one that bit this test), and two dispatches of the same tool
#: allocate different objects. Comparing it would make the heap, not the
#: dispatcher, the thing under test — and it passes locally whenever CPython
#: happens to reuse the address, so it fails only in a long run.
_ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]+")


def _outcome(call) -> tuple[Any, ...]:
    """Run `call` and reduce it to a comparable value — including the way it
    failed, so the refusal branches are compared as strictly as the happy
    ones."""
    try:
        return ("returned", call())
    except Exception as exc:
        return ("raised", type(exc).__name__, _ADDRESS_RE.sub("0xADDR", str(exc)))


# --- generic params, derived from each spec's own input_model -------------------


def _sample_value(annotation: Any) -> Any:
    origin = getattr(annotation, "__origin__", None)
    if origin is list:
        return [_sample_value(annotation.__args__[0])]
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _sample_params(annotation)
    if annotation is bool:
        return False
    if annotation is int:
        return 1
    if annotation is str:
        return "1"
    raise AssertionError(
        f"no sample value for {annotation!r}; a new tool input field needs one here "
        "rather than a hand-written params fixture that could silently skip a tool"
    )


def _sample_params(model: type[BaseModel]) -> BaseModel:
    """A valid `input_model` instance built from the model's own required
    fields, so a tool added later is exercised without an edit here."""
    values = {
        name: _sample_value(field.annotation)
        for name, field in model.model_fields.items()
        if field.is_required()
    }
    return model(**values)


# --- AC1: the product domain migrated with zero behaviour change ----------------


def test_product_domain_migration_is_behaviour_preserving():
    """Every tool in the REAL production registry dispatches, through the
    real `ProductToolExecutor`, to the same outcome the pre-#1704 if/elif
    produced — in both executor configurations, happy and resource-less.

    The set iterated over is the registry's own, so a tool added or removed
    moves this test with it; nothing here names a tool.
    """
    registry = build_product_tool_registry()
    specs = registry.list_all()
    assert specs, "the production registry must not be empty"

    compared = 0
    for spec in specs:
        params = _sample_params(spec.input_model)
        for resourced in (True, False):
            legacy_products = _FakeProductsResource()
            legacy_kwargs = _executor_kwargs(legacy_products, resourced=resourced)
            legacy = _outcome(
                lambda: _legacy_dispatch(
                    tool_name=spec.name,
                    spec=spec,
                    params=params,
                    kwargs=legacy_kwargs,
                )
            )

            domain_products = _FakeProductsResource()
            executor = ProductToolExecutor(
                registry=registry,
                **_executor_kwargs(domain_products, resourced=resourced),
            )
            current = _outcome(lambda: executor.execute(tool_name=spec.name, params=params))

            assert current == legacy, (
                f"{spec.name!r} (resourced={resourced}) dispatched differently "
                f"after #1704: {current!r} vs {legacy!r}"
            )
            assert domain_products.calls == legacy_products.calls, (
                f"{spec.name!r} (resourced={resourced}) made different vendor calls after #1704"
            )
            compared += 1

    assert compared == len(specs) * 2


class TestProductDomainMigrationIsBehaviourPreserving:
    """The derived reachability assertions the criterion above rests on."""

    def test_every_registered_tool_resolves_to_the_handler_it_resolved_to_before(self):
        """The object identity check, tool by tool over the real registry.

        A tool that silently moved domain would still *run* — it would run
        the other domain's handler — so comparing outcomes alone is not
        enough. This compares the resolved callable itself.
        """
        for spec in build_product_tool_registry().list_all():
            resolved = get_tool_domain(spec.domain).handler_for(spec.name)
            assert resolved is _legacy_handler_for(spec), (
                f"{spec.name!r} now resolves to a different handler than the "
                f"pre-#1704 dispatch reached"
            )

    def test_the_reachable_tool_set_is_derived_and_unchanged(self):
        """Both sides derived: the registered domains' handler tables, and
        the three literal tables the old executor dispatched over."""
        assert reachable_tool_names() == _legacy_reachable_tool_names()

    def test_every_tool_the_production_registry_offers_is_reachable(self):
        """The registry is what `WorkflowRunner` offers the model; the domain
        tables are what dispatch can reach. A name in the first and not the
        second is a tool the model can propose and the runtime cannot run."""
        registered = frozenset(spec.name for spec in build_product_tool_registry().list_all())
        assert registered <= reachable_tool_names()
        assert registered == _legacy_reachable_tool_names()


# --- AC2: a non-product domain gets a subject-generic context -------------------


def test_non_product_domain_receives_subject_generic_context():
    """A run whose subject is a SKU set calls the test-only `inventory`
    domain's READ tool, and the handler is handed a context carrying THAT
    subject and no product id."""
    recorder = InventoryToolRecorder()
    registry = ToolRegistry()
    register_inventory_tools(registry)
    subject = RunSubject(subject_type=SKU_SET_SUBJECT_TYPE, subject_ref="sku-set-7")

    with tool_domain_registered_for_test(make_inventory_domain(recorder)):
        executor = DomainToolExecutor(registry=registry, subject=subject)
        result = executor.execute(
            tool_name=TEST_INVENTORY_READ_TOOL,
            params=_sample_params(registry.get(TEST_INVENTORY_READ_TOOL).input_model),
        )

    assert result == {"subject_type": SKU_SET_SUBJECT_TYPE, "subject_ref": "sku-set-7"}

    (context,) = recorder.contexts
    assert isinstance(context, ToolContext)
    assert context.subject == subject
    # ABSENT, not present-and-None: a context that still carries a product id
    # for a run about a SKU set is the product assumption this slice removes,
    # and `is None` would pass on one that still had the field.
    assert not hasattr(context, "product_id")
    assert context.binding is None


class TestNonProductDomainReceivesSubjectGenericContext:
    """The two halves the criterion above depends on: the subject comes from
    the run, and the product domain still gets its own bound context."""

    def test_the_subject_comes_from_the_run_not_from_params(self):
        """A `params` object carrying its own subject cannot move the context.

        The seam is owned directly rather than relying on the coincidence
        that no real input model declares a subject field today — the same
        reason `test_agent_runner_tool_executor.py` owns the product-id
        version of this assertion.
        """

        class _ParamsWithConflictingSubject(BaseModel):
            subject_type: str
            subject_ref: str

        recorder = InventoryToolRecorder()
        registry = ToolRegistry()
        register_inventory_tools(registry)
        subject = RunSubject(subject_type=SKU_SET_SUBJECT_TYPE, subject_ref="sku-set-7")

        with tool_domain_registered_for_test(make_inventory_domain(recorder)):
            executor = DomainToolExecutor(registry=registry, subject=subject)
            executor.execute(
                tool_name=TEST_INVENTORY_READ_TOOL,
                params=_ParamsWithConflictingSubject(
                    subject_type="product", subject_ref="attacker-product"
                ),
            )

        (context,) = recorder.contexts
        assert context.subject == subject

    def test_the_product_domain_still_receives_its_own_bound_context(self):
        """The other half of AC2: migrating the context did not change what a
        PRODUCT handler is handed."""
        products = _FakeProductsResource()
        registry = build_product_tool_registry()
        executor = ProductToolExecutor(
            registry=registry, **_executor_kwargs(products, resourced=True)
        )

        bound = executor._binding()
        assert isinstance(bound, ProductToolContext)
        assert bound.product_id == _BOUND_PRODUCT_ID
        assert executor.subject == RunSubject(
            subject_type=PRODUCT_DOMAIN, subject_ref=_BOUND_PRODUCT_ID
        )


# --- AC3: a domainless spec is refused ------------------------------------------


def _domainless_spec_kwargs() -> dict[str, Any]:
    class _In(BaseModel):
        pass

    class _Out(BaseModel):
        pass

    return {
        "name": "a_tool_with_no_domain",
        "description": "A tool nobody gave a domain.",
        "seller_rationale_vi": "Công cụ không có miền (test-only).",
        "input_model": _In,
        "output_model": _Out,
        "classification": ToolClassification.READ,
        "policy": ToolPolicy.AUTO,
        "timeout_seconds": 10,
    }


def test_domainless_spec_is_refused():
    """Refused at CONSTRUCTION, which for a module-level spec is import time
    — the moment the module registering it is loaded, not the first dispatch
    that reaches it in a seller's run."""
    with pytest.raises(DomainlessToolError, match="declares no domain"):
        ToolSpec(**_domainless_spec_kwargs())


class TestDomainlessSpecIsRefused:
    """The registry's own door, and the real registry's conformance."""

    def test_an_empty_domain_string_is_refused_too(self):
        with pytest.raises(DomainlessToolError):
            ToolSpec(domain="", **_domainless_spec_kwargs())

    def test_the_registry_refuses_a_domainless_spec_that_evaded_construction(self):
        """The registry is the second closed door.

        A frozen dataclass can be mutated through `object.__setattr__`, so
        `__post_init__` alone is not the whole guard: a name in the registry
        is a name `WorkflowRunner` offers the model.
        """
        spec = ToolSpec(domain=PRODUCT_DOMAIN, **_domainless_spec_kwargs())
        object.__setattr__(spec, "domain", "")

        registry = ToolRegistry()
        with pytest.raises(DomainlessToolError, match="declares no domain"):
            registry.register(spec)

    def test_every_production_spec_names_a_registered_domain(self):
        """`registry.py` cannot check this itself (importing the domain
        registry from it would be a cycle), so it is checked here, against
        the real registry."""
        for spec in build_product_tool_registry().list_all():
            assert get_tool_domain(spec.domain).name == spec.domain


# --- the cross-domain refusal: named error, never a silent no-op ----------------


class TestAToolFromAnotherDomainIsRefusedByName:
    def test_a_product_tool_is_refused_on_a_run_bound_to_a_sku_set(self):
        """The safety property: a run whose subject is not a product cannot
        reach a product tool, and is told so by name."""
        registry = build_product_tool_registry()
        product_spec = next(spec for spec in registry.list_all() if spec.domain == PRODUCT_DOMAIN)
        executor = DomainToolExecutor(
            registry=registry,
            subject=RunSubject(subject_type=SKU_SET_SUBJECT_TYPE, subject_ref="sku-set-7"),
            read_resources=_read_resources(_FakeProductsResource()),
            write_resources=_write_resources(_FakeProductsResource()),
        )

        with pytest.raises(ToolDomainBindingError) as excinfo:
            executor.execute(
                tool_name=product_spec.name,
                params=_sample_params(product_spec.input_model),
            )

        message = str(excinfo.value)
        assert PRODUCT_DOMAIN in message
        assert SKU_SET_SUBJECT_TYPE in message

    def test_the_wrong_subject_is_refused_on_domain_grounds_not_on_missing_resources(self):
        """Ordering matters, because the message is the whole point.

        An executor bound to a SKU set typically also carries no product
        resource bundle, and the resource check would happily refuse the call
        first — truthfully, but for the wrong reason, and naming neither the
        domain nor the subject. The domain check runs first.
        """
        registry = build_product_tool_registry()
        product_spec = next(spec for spec in registry.list_all() if spec.domain == PRODUCT_DOMAIN)
        executor = DomainToolExecutor(
            registry=registry,
            subject=RunSubject(subject_type=SKU_SET_SUBJECT_TYPE, subject_ref="sku-set-7"),
        )

        with pytest.raises(ToolDomainBindingError) as excinfo:
            executor.execute(
                tool_name=product_spec.name,
                params=_sample_params(product_spec.input_model),
            )

        assert "read_resources" not in str(excinfo.value)
        assert SKU_SET_SUBJECT_TYPE in str(excinfo.value)

    def test_a_product_tool_is_refused_when_no_product_binding_is_bound(self):
        """The second cause, and the one a subclass-less executor hits: the
        subject kind is right but nothing supplied the domain's bound state."""
        registry = build_product_tool_registry()
        product_spec = next(spec for spec in registry.list_all() if spec.domain == PRODUCT_DOMAIN)
        executor = DomainToolExecutor(
            registry=registry,
            subject=RunSubject(subject_type=PRODUCT_DOMAIN, subject_ref="p1"),
            read_resources=_read_resources(_FakeProductsResource()),
            write_resources=_write_resources(_FakeProductsResource()),
        )

        with pytest.raises(ToolDomainBindingError, match="no product binding"):
            executor.execute(
                tool_name=product_spec.name,
                params=_sample_params(product_spec.input_model),
            )

    def test_a_tool_declaring_a_domain_that_does_not_register_it_is_refused(self):
        """A tool that resolved to the WRONG domain. Before #1704 this was
        invisible: anything not READ-classified fell through to the product
        WRITE table."""
        recorder = InventoryToolRecorder()
        registry = ToolRegistry()
        misfiled = replace(
            build_product_tool_registry().get("check_product_status"),
            domain=TEST_INVENTORY_DOMAIN,
        )
        registry.register(misfiled)

        with tool_domain_registered_for_test(make_inventory_domain(recorder)):
            executor = DomainToolExecutor(
                registry=registry,
                subject=RunSubject(subject_type=SKU_SET_SUBJECT_TYPE, subject_ref="sku-set-7"),
            )
            with pytest.raises(ToolNotInDomainError) as excinfo:
                executor.execute(
                    tool_name=misfiled.name, params=_sample_params(misfiled.input_model)
                )

        message = str(excinfo.value)
        assert misfiled.name in message
        assert TEST_INVENTORY_DOMAIN in message
        assert recorder.contexts == [], "no handler may run for a mis-filed tool"

    def test_a_tool_naming_an_unregistered_domain_is_refused(self):
        registry = ToolRegistry()
        orphan = replace(
            build_product_tool_registry().get("check_product_status"),
            domain="no_such_domain",
        )
        registry.register(orphan)
        executor = DomainToolExecutor(
            registry=registry,
            subject=RunSubject(subject_type=PRODUCT_DOMAIN, subject_ref="p1"),
        )

        with pytest.raises(UnregisteredToolDomainError, match="no_such_domain"):
            executor.execute(tool_name=orphan.name, params=_sample_params(orphan.input_model))


# --- AC4: CONFIRM is a property of the policy, never of the domain --------------


class _SteppingClock:
    def __init__(self, *, step: float, start: float = 0.0) -> None:
        self._value = start
        self._step = step

    def __call__(self) -> float:
        value = self._value
        self._value += self._step
        return value


class _NullPublisher:
    async def publish(self, channel: str, message: str) -> None:
        return None


def _turn(*blocks) -> AssistantTurn:
    return AssistantTurn(blocks=tuple(blocks), usage=Usage(input_tokens=1, output_tokens=1))


def _inventory_playbook() -> Playbook:
    """A playbook granting the TEST domain's two tools.

    It borrows Optimize Product's `workflow_key`/`version` so `compose()`
    resolves a real prose binding — per-workflow prompt bindings are #1705's
    (P-SHARED-5) — exactly as `test_agent_runner_pause_resume.py`'s own
    narrowed playbook does.
    """
    return Playbook(
        workflow_key=OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key,
        version=OPTIMIZE_PRODUCT_PLAYBOOK.version,
        steps=(
            PlaybookStep(
                step_id="read",
                intent="Count the stock on hand.",
                tools=(TEST_INVENTORY_READ_TOOL,),
                policy=ToolPolicy.AUTO,
            ),
            PlaybookStep(
                step_id="write",
                intent="Set the stock level.",
                tools=(TEST_INVENTORY_WRITE_TOOL,),
                policy=ToolPolicy.CONFIRM,
            ),
        ),
        termination_policy=replace(OPTIMIZE_PRODUCT_TERMINATION_POLICY, terminal_tools=()),
    )


async def _seed_workflow_run(session: AsyncSession) -> uuid.UUID:
    user = User(id=uuid.uuid4(), phone=f"+8490{uuid.uuid4().int % 10_000_000:07d}")
    shop = Shop(id=uuid.uuid4(), user_id=user.id, shop_name="Domain Dispatch Shop")
    product = Product(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_product_id="tt-1704",
        name="Domain Dispatch Product",
        status="active",
        update_time=datetime.now(UTC),
    )
    run = WorkflowRun(
        id=uuid.uuid4(),
        shop_id=shop.id,
        product_id=product.id,
        state=RunState().to_dict(),
        status="running",
        prompt_version="optimize_product.v1",
        prompt_sha256="0" * 64,
    )
    session.add_all([user, shop, product, run])
    await session.flush()
    return run.id


@pytest.mark.asyncio
async def test_confirm_policy_is_domain_independent(engine: AsyncEngine):
    """A WRITE-CONFIRM tool in the TEST domain pauses the run at CONFIRM
    exactly as a product write does: `waiting_approval`,
    `stop_reason=paused_for_confirmation`, and a `run_confirmations` row —
    and the handler never runs, because consent precedes execution.

    Driven through the REAL `WorkflowRunner`, the REAL `ToolRegistry` and
    the REAL `DomainToolExecutor`, with only the LLM faked.
    """
    recorder = InventoryToolRecorder()
    registry = ToolRegistry()
    register_inventory_tools(registry)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        run_id = await _seed_workflow_run(session)
        await session.commit()

    with tool_domain_registered_for_test(make_inventory_domain(recorder)):
        async with factory() as session:
            runner = WorkflowRunner(
                llm_service=FakeLLMService(
                    script=[
                        _turn(
                            ToolCallBlock(
                                call_id="c1",
                                tool_name=TEST_INVENTORY_READ_TOOL,
                                arguments={},
                            )
                        ),
                        _turn(
                            ToolCallBlock(
                                call_id="c2",
                                tool_name=TEST_INVENTORY_WRITE_TOOL,
                                arguments={"units": 12},
                            )
                        ),
                    ]
                ),
                tool_executor=DomainToolExecutor(
                    registry=registry,
                    subject=RunSubject(subject_type=SKU_SET_SUBJECT_TYPE, subject_ref="sku-set-7"),
                ),
                event_sink=InMemoryEventSink(),
                conversation_store=JsonbConversationStore(session),
                registry=registry,
                playbook=_inventory_playbook(),
                clock=_SteppingClock(start=1000.0, step=2.0),
            )
            result = await runner.run(run_id, product_ref="sku-set-7")
            await session.commit()

    assert result.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION

    async with factory() as session:
        run = await session.get(WorkflowRun, run_id)
        assert run is not None
        assert run.status == "waiting_approval"
        confirmations = (
            (
                await session.execute(
                    select(RunConfirmation).where(RunConfirmation.workflow_run_id == run_id)
                )
            )
            .scalars()
            .all()
        )

    assert len(confirmations) == 1, "a CONFIRM tool must persist exactly one pending row"

    # The READ ran; the CONFIRM write did NOT — consent precedes execution,
    # and it does so for a domain the product executor knows nothing about.
    assert [c.subject.subject_type for c in recorder.contexts] == [SKU_SET_SUBJECT_TYPE]


# --- #1702's handover coupling, made executable ---------------------------------


def test_bindable_subject_types_and_the_approval_wire_widen_together():
    """#1702's handover named a pair that must move together:
    `approval._BINDABLE_SUBJECT_TYPES` and `ApprovalResult.product_id`,
    which is a NON-optional `uuid.UUID` because only a product subject is
    bindable, and `DemoDecisionApproveData.product_id` on the wire is
    non-optional for the same reason.

    #1704 does not widen either — the runtime still registers exactly one
    subject-bound tool domain, so there is no subject kind a run could be
    bound to and then have a tool to act on, and a run created with a NULL
    `product_id` would fail in `workers/tasks/agent_workflow.py::_load_context`,
    which still loads a `Product` unconditionally. This test is the tripwire
    that keeps the halves from being widened one at a time later.

    **#1703 added a THIRD copy of the same fact while this branch was open**:
    `services/action_cards/subjects.py::BINDABLE_SUBJECT_TYPES`, the set the
    card PRODUCER may emit, whose own comment says it is "kept identical to
    `_BINDABLE_SUBJECT_TYPES`" and names widening as #1704's seam. Prose is
    not a mechanism — three hand-maintained frozensets of the same fact are
    exactly the duplicated-fact drift ADR-085 rejects — so this test now
    binds all three. Producing a subject kind approve cannot bind, or binding
    one no tool domain can act on, are both live failure modes the moment any
    one of them moves alone.
    """
    import typing

    from juli_backend.services.action_cards import subjects as card_subjects

    bindable = approval_module._BINDABLE_SUBJECT_TYPES
    domain_subjects = bindable_subject_types()
    emittable = card_subjects.BINDABLE_SUBJECT_TYPES

    assert bindable == domain_subjects == emittable == frozenset({PRODUCT_DOMAIN}), (
        "a subject kind became bindable, emittable, or a second subject-bound "
        "tool domain was registered. These four move together or not at all: "
        "approval._BINDABLE_SUBJECT_TYPES, "
        "action_cards.subjects.BINDABLE_SUBJECT_TYPES (the producer, #1703), "
        "the registered tool domains' own subject_types, and the wire — "
        "ApprovalResult.product_id (-> uuid.UUID | None) with "
        "DemoDecisionApproveData.product_id — plus _load_context's "
        "unconditional Product load."
    )

    product_id_type = typing.get_type_hints(approval_module.ApprovalResult)["product_id"]
    assert product_id_type is uuid.UUID, (
        "ApprovalResult.product_id widened while _BINDABLE_SUBJECT_TYPES did not"
    )


# --- the domain registry's own contract ----------------------------------------


class TestToolDomainRegistryContract:
    def test_it_refuses_to_shadow_a_registered_domain(self):
        recorder = InventoryToolRecorder()
        product_shaped = ToolDomain(
            name=PRODUCT_DOMAIN,
            handlers={"whatever": recorder.read_handler},
        )
        with pytest.raises(ValueError, match="already registered"):
            with tool_domain_registered_for_test(product_shaped):
                pass  # pragma: no cover - the contextmanager raises on entry

    def test_a_test_domain_is_removed_again_when_the_block_exits(self):
        recorder = InventoryToolRecorder()
        with tool_domain_registered_for_test(make_inventory_domain(recorder)):
            assert get_tool_domain(TEST_INVENTORY_DOMAIN).name == TEST_INVENTORY_DOMAIN
        with pytest.raises(UnregisteredToolDomainError):
            get_tool_domain(TEST_INVENTORY_DOMAIN)

    def test_a_subject_agnostic_domain_declares_none_not_an_empty_set(self):
        recorder = InventoryToolRecorder()
        with pytest.raises(ValueError, match="subject-agnostic"):
            ToolDomain(
                name="empty_subjects",
                handlers={"t": recorder.read_handler},
                subject_types=frozenset(),
            )

    def test_the_terminal_domain_is_subject_agnostic_and_resource_free(self):
        """Which is exactly what reproduces the pre-#1704 branch order: the
        terminal table was checked FIRST, so a terminal tool never touched
        `read_resources` and never failed on their absence."""
        terminal = get_tool_domain(
            build_product_tool_registry().get("conclude_without_changes").domain
        )
        assert terminal.subject_types is None
        assert terminal.takes_resources is False

        executor = ProductToolExecutor(
            registry=build_product_tool_registry(),
            product_id=_BOUND_PRODUCT_ID,
        )
        result = executor.execute(
            tool_name="conclude_without_changes",
            params=ConcludeWithoutChangesInput(reason="nothing to do"),
        )
        assert result == {"acknowledged": True}
