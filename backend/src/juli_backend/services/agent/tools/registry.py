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


class UnknownToolError(KeyError):
    """Raised by `ToolRegistry.get` when the tool name has never been registered."""


@dataclass(frozen=True)
class ToolSpec:
    """An agent-callable capability definition (ADR-069 decision 3).

    Carries the seven business-semantic attributes an agent tool needs:
    `name` (business-semantic English snake_case — never a vendor endpoint
    name), model-facing English `description`, declared `input_model` /
    `output_model` (Pydantic; `input_model` is the sole source the rendered
    JSON schema is derived from), read|write `classification`, auto|confirm
    `policy`, and `timeout_seconds`.
    """

    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    classification: ToolClassification
    policy: ToolPolicy
    timeout_seconds: int

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("ToolSpec.name must be a non-empty string")
        if not self.description:
            raise ValueError("ToolSpec.description must be a non-empty string")
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
