"""Agent tool registry core (ADR-069 decision 3, issue #980 / W1-A).

Holds `ToolSpec` capability definitions for the LLM-driven agent execution
loop and derives the model-facing JSON schema shown to the LLM directly from
each definition's declared Pydantic input model via `model_json_schema()` —
never hand-written, so what the model is shown and what the platform
validates against cannot drift.

Scope of this slice: registry + rendering only. No marketplace client, no
marketplace I/O, and no real capability handlers live here — domain-grouped
handlers (e.g. `product.py`) register `ToolSpec`s into a `ToolRegistry`
instance in a later slice. This module must never import anything from
`juli_backend.integrations.tiktok` or any other vendor/marketplace surface;
`test_agent_tool_registry.py::TestNoMarketplaceImports` enforces that via an
AST import check.

Distinct from the legacy Celery tool registry (`services/execution/runner.py`),
which is name -> callable with no metadata and stays untouched (ADR-069).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel


class ToolClassification(str, Enum):
    """Whether an agent tool reads state or mutates it (ADR-068 decision 3/4)."""

    READ = "read"
    WRITE = "write"


class ToolPolicy(str, Enum):
    """Execution policy for an agent tool (ADR-068 decision 4).

    AUTO tools run without a pause; CONFIRM tools pause the run for seller
    approval before executing. NEVER-class operations have no member here —
    per ADR-068/069 they are structurally never registered as tools at all.
    """

    AUTO = "auto"
    CONFIRM = "confirm"


class DuplicateToolError(ValueError):
    """Raised by `ToolRegistry.register` when the tool name is already registered."""


class DomainlessToolError(ValueError):
    """The spec names no domain (issue #1704, W9-A/P-SHARED-4).

    Raised by `ToolSpec.__post_init__` -- so a module-level spec fails at
    IMPORT time, the moment the module registering it is loaded, rather
    than on the first dispatch that reaches it in a seller's run -- and
    re-asserted by `ToolRegistry.register` so a spec that reached the
    registry by some other route (a frozen dataclass mutated through
    `object.__setattr__`, say) still cannot be registered.

    A tool with no domain has no handler table to resolve against: every
    dispatch is domain-first since #1704, so registering one would put a
    name in the registry that `WorkflowRunner` will offer the model and
    `ProductToolExecutor` can never run.
    """


class UnknownToolError(KeyError):
    """Raised by `ToolRegistry.get` when the tool name has never been registered."""


@dataclass(frozen=True)
class ToolSpec:
    """An agent-callable capability definition (ADR-069 decision 3).

    Carries the nine business-semantic attributes an agent tool needs:
    `name` (business-semantic English snake_case — never a vendor endpoint
    name), model-facing English `description`, the seller-facing Vietnamese
    `seller_rationale_vi`, declared `input_model` / `output_model` (Pydantic;
    `input_model` is the sole source the rendered JSON schema is derived
    from), read|write `classification`, auto|confirm `policy`,
    `timeout_seconds`, and the `domain` whose handler table dispatch resolves
    against.

    **`domain` (issue #1704, W9-A/P-SHARED-4).** The name of the
    `ToolDomain` (`domains.py`, registered in `domain_registry.py`) that owns
    this tool's handler and knows which run subjects it can act on.
    Dispatch is domain-first: `runner/tool_executor.py` resolves
    `domain` → `ToolDomain` → handler, rather than falling through an
    if/elif over `PRODUCT_READ_TOOL_HANDLERS`/`PRODUCT_WRITE_TOOL_HANDLERS`/
    `TERMINAL_TOOL_HANDLERS` as it did before. It is declared last and
    defaults to the empty string *only* so the refusal below can be a
    precise, named `DomainlessToolError` instead of a bare `TypeError` about
    a missing argument — an empty domain is never a registrable state.
    This module does not import the domain registry (that would be a cycle:
    a domain artifact imports the specs it dispatches), so the check here is
    "names *a* domain"; "names a *registered* domain" is asserted against
    the real registry by `tests/unit/test_tool_dispatcher_domains.py`.

    **`description` vs. `seller_rationale_vi` (issue #1904, W6-FIX).**
    `description` is the LLM-facing tool description the model reads every
    turn — English, and never shown to a seller. `seller_rationale_vi` is a
    deterministic, dictionary-governed Vietnamese string
    (`dictionary.md`, key `run.option_rationale.<name>`) that
    `_pause_pending_confirmation` (`runner/core.py`) passes as a CONFIRM
    option's `rationale` instead. Before this field existed,
    `_pause_pending_confirmation` passed `spec.description` itself onto the
    `workflow.approval_required` event and into the persisted
    `run_confirmations` row — an English, model-facing string a Vietnamese
    seller was asked to authorize a real mutation against. The two fields
    must never be confused: `description` stays exactly what it always was
    (the model's view does not move), and `seller_rationale_vi` is the only
    field a seller-facing surface may read.
    """

    name: str
    description: str
    seller_rationale_vi: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    classification: ToolClassification
    policy: ToolPolicy
    timeout_seconds: int
    domain: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("ToolSpec.name must be a non-empty string")
        if not self.domain:
            raise DomainlessToolError(
                f"ToolSpec {self.name!r} declares no domain; every tool belongs to a "
                "tool domain (services/agent/tools/domains.py) and dispatch resolves "
                "the handler through it"
            )
        if not self.description:
            raise ValueError("ToolSpec.description must be a non-empty string")
        if not self.seller_rationale_vi:
            raise ValueError("ToolSpec.seller_rationale_vi must be a non-empty string")
        if not isinstance(self.classification, ToolClassification):
            raise TypeError(
                "ToolSpec.classification must be a ToolClassification member, "
                f"got {self.classification!r}"
            )
        if not isinstance(self.policy, ToolPolicy):
            raise TypeError(f"ToolSpec.policy must be a ToolPolicy member, got {self.policy!r}")
        if not (isinstance(self.input_model, type) and issubclass(self.input_model, BaseModel)):
            raise TypeError("ToolSpec.input_model must be a Pydantic BaseModel subclass")
        if not (isinstance(self.output_model, type) and issubclass(self.output_model, BaseModel)):
            raise TypeError("ToolSpec.output_model must be a Pydantic BaseModel subclass")
        if not isinstance(self.timeout_seconds, int) or isinstance(self.timeout_seconds, bool):
            raise TypeError("ToolSpec.timeout_seconds must be an int")
        if self.timeout_seconds <= 0:
            raise ValueError("ToolSpec.timeout_seconds must be positive")

    def render_input_schema(self) -> dict[str, Any]:
        """The model-facing JSON schema, derived from `input_model`.

        Exactly `input_model.model_json_schema()` — never hand-written — so
        the schema shown to the LLM and the shape `input_model` validates
        against cannot drift apart.
        """
        return self.input_model.model_json_schema()


class ToolRegistry:
    """Explicit name -> `ToolSpec` registry. No implicit/decorator registration."""

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        # #1704: re-asserted here as well as in `ToolSpec.__post_init__` so
        # the registry itself is the closed door. A domainless spec cannot be
        # dispatched, and a name in this registry is a name `WorkflowRunner`
        # will offer the model.
        if not spec.domain:
            raise DomainlessToolError(
                f"Tool {spec.name!r} declares no domain and cannot be registered"
            )
        if spec.name in self._specs:
            raise DuplicateToolError(f"Tool already registered: {spec.name!r}")
        self._specs[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._specs[name]
        except KeyError:
            raise UnknownToolError(f"Unknown tool: {name!r}") from None

    def list_all(self) -> list[ToolSpec]:
        return list(self._specs.values())
