"""A real, second `ToolDomain` for tests that need the tool registry to hold
more than the product domain (issue #1704, W9-A/P-SHARED-4).

Every acceptance criterion of #1704 is of the form "a test-only `inventory`
domain with one tool, beside the real product one". Until a second
production domain exists there is nothing to be the second entry, so tests
build one here and register it through the registry's own
`domain_registry.tool_domain_registered_for_test` contextmanager -- the SAME
`_TOOL_DOMAIN_REGISTRY` `DomainToolExecutor.execute` reads. A test that
resolved against its own dict would prove nothing about the executor.

This is the sibling of `tests/support/workflow_registry.py`, which does the
same job for #1702's playbook registry, and it follows the same two rules:

* it does not build a `**kwargs`-accepting double. `ToolDomain`, `ToolSpec`
  and `RunSubject` are frozen dataclasses with real `__post_init__`
  validation, and what is returned here is the real thing -- the W9-A
  architect lock ("bind to real objects, never `**kwargs` doubles") and
  #1365's consumer-without-producer finding are the reason.
* it does not reuse a production name. The domain is `inventory`, which no
  production module registers, and both tools are named for a subject kind
  (`sku_set`) that no registered playbook can bind today, so a row or a
  registry entry carrying either can only have come from a test.

The READ tool's handler RECORDS the context object it was handed rather than
summarising it, because the thing under test is that object's shape: #1704's
criterion is that a non-product handler receives a context carrying the run's
subject and carrying no product id AT ALL -- absent, not present-and-None --
and only the object itself can answer that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from juli_backend.services.agent.tools.domains import ToolDomain
from juli_backend.services.agent.tools.registry import (
    ToolClassification,
    ToolPolicy,
    ToolRegistry,
    ToolSpec,
)

#: The test-only domain's name. Not a domain any production module registers.
TEST_INVENTORY_DOMAIN = "inventory"

#: The subject kind the test-only domain acts on: a set of SKUs, the
#: non-product subject ADR-087 d.5 and ADR-091 name for Clear Excess.
SKU_SET_SUBJECT_TYPE = "sku_set"

TEST_INVENTORY_READ_TOOL = "count_stock_on_hand"
TEST_INVENTORY_WRITE_TOOL = "set_stock_level"


class CountStockOnHandInput(BaseModel):
    """No identifier field, for the same reason no product READ tool has one
    (ADR-070 decision 1): the subject comes from the run, never the model."""


class CountStockOnHandOutput(BaseModel):
    subject_type: str = Field(description="Echoed from the context the handler received.")
    subject_ref: str = Field(description="Echoed from the context the handler received.")


class SetStockLevelInput(BaseModel):
    units: int = Field(description="The stock level to set, in units.")


class SetStockLevelOutput(BaseModel):
    units: int


@dataclass
class InventoryToolRecorder:
    """Captures the context object each test-domain handler was handed."""

    contexts: list[Any] = field(default_factory=list)
    resources: list[Any] = field(default_factory=list)

    def read_handler(
        self, resources: Any, context: Any, params: CountStockOnHandInput
    ) -> CountStockOnHandOutput:
        self.contexts.append(context)
        self.resources.append(resources)
        return CountStockOnHandOutput(
            subject_type=context.subject.subject_type,
            subject_ref=context.subject.subject_ref,
        )

    def write_handler(
        self, resources: Any, context: Any, params: SetStockLevelInput
    ) -> SetStockLevelOutput:
        self.contexts.append(context)
        self.resources.append(resources)
        return SetStockLevelOutput(units=params.units)


COUNT_STOCK_ON_HAND_SPEC = ToolSpec(
    name=TEST_INVENTORY_READ_TOOL,
    description="Count the stock on hand for the SKUs this run is about (test-only).",
    seller_rationale_vi="Đếm tồn kho của các SKU trong phiên này (test-only).",
    input_model=CountStockOnHandInput,
    output_model=CountStockOnHandOutput,
    classification=ToolClassification.READ,
    policy=ToolPolicy.AUTO,
    timeout_seconds=10,
    domain=TEST_INVENTORY_DOMAIN,
)

SET_STOCK_LEVEL_SPEC = ToolSpec(
    name=TEST_INVENTORY_WRITE_TOOL,
    description="Set the stock level for the SKUs this run is about (test-only).",
    seller_rationale_vi="Đặt mức tồn kho cho các SKU trong phiên này (test-only).",
    input_model=SetStockLevelInput,
    output_model=SetStockLevelOutput,
    classification=ToolClassification.WRITE,
    policy=ToolPolicy.CONFIRM,
    timeout_seconds=20,
    domain=TEST_INVENTORY_DOMAIN,
)


def make_inventory_domain(
    recorder: InventoryToolRecorder,
    *,
    takes_resources: bool = False,
) -> ToolDomain:
    """A real `ToolDomain` whose handlers report to `recorder`.

    `bind_context` is left at the default (`subject_generic_context`), so the
    handlers receive the subject-generic `ToolContext` itself -- the whole
    point of the criterion this supports. `takes_resources` defaults to False
    because a test domain has no marketplace bundle of its own and must not
    be made to fail on the absence of the product one.
    """
    return ToolDomain(
        name=TEST_INVENTORY_DOMAIN,
        handlers={
            COUNT_STOCK_ON_HAND_SPEC.name: recorder.read_handler,
            SET_STOCK_LEVEL_SPEC.name: recorder.write_handler,
        },
        subject_types=frozenset({SKU_SET_SUBJECT_TYPE}),
        takes_resources=takes_resources,
    )


def register_inventory_tools(registry: ToolRegistry) -> None:
    """Register the test-only domain's two capabilities into `registry`."""
    registry.register(COUNT_STOCK_ON_HAND_SPEC)
    registry.register(SET_STOCK_LEVEL_SPEC)
