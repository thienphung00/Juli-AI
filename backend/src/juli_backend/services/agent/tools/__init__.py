"""Agent tool registry package (ADR-069 decision 3).

Public API re-exported from `registry.py` — see that module's docstring for
scope. Domain-grouped tool handlers live in `product.py`/`product_write.py`
(the product domain, assembled in `product_domain.py`) and `terminal.py`.

**Deliberately NOT re-exported here (issue #1704).** The tool-domain surface
— `domains.py`'s `ToolDomain`/`ToolContext`/`RunSubject` and
`domain_registry.py`'s resolution functions — is imported from those modules
directly, not through this facade. Re-exporting it would make importing
`ToolSpec` pull in `product_domain.py`, and through it `product.py`'s
`juli_backend.integrations.tiktok` import, putting a marketplace dependency
behind the one package the registry's own no-vendor-imports rule exists to
keep clean.
"""

from __future__ import annotations

from juli_backend.services.agent.tools.registry import (
    DomainlessToolError,
    DuplicateToolError,
    ToolClassification,
    ToolPolicy,
    ToolRegistry,
    ToolSpec,
    UnknownToolError,
)

__all__ = [
    "DomainlessToolError",
    "DuplicateToolError",
    "ToolClassification",
    "ToolPolicy",
    "ToolRegistry",
    "ToolSpec",
    "UnknownToolError",
]
