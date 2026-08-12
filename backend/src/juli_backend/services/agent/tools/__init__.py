"""Agent tool registry package (ADR-069 decision 3).

Public API re-exported from `registry.py` — see that module's docstring for
scope. Domain-grouped tool handlers (e.g. `product.py`) land in this package
in a later slice; none exist yet.
"""

from __future__ import annotations

from juli_backend.services.agent.tools.registry import (
    DuplicateToolError,
    ToolClassification,
    ToolPolicy,
    ToolRegistry,
    ToolSpec,
    UnknownToolError,
)

__all__ = [
    "DuplicateToolError",
    "ToolClassification",
    "ToolPolicy",
    "ToolRegistry",
    "ToolSpec",
    "UnknownToolError",
]
