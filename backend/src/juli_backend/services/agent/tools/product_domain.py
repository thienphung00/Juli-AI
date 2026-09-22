"""The product tool domain -- issue #1704 (W9-A/P-SHARED-4, spec P0-3).

One `ToolDomain` artifact covering every Optimize Product capability: the
four READ handlers `product.py` registers and the three WRITE handlers
`product_write.py` registers, in one table, plus the rule that turns the
subject-generic `ToolContext` into the `ProductToolContext` those handlers
have always taken.

**Why this module exists rather than a table in the registry.** The domain
artifact belongs to the domain, the way `OPTIMIZE_PRODUCT_PLAYBOOK` belongs
to `playbooks/optimize_product.py` and not to the registry that lists it.
The product domain's handlers are split across two modules for historical
reasons (READ landed in #981, WRITE in #982) and `product_write.py` already
imports `product.py`, so this is the first place both halves are in scope at
once. A later domain that lives in one module declares its own `ToolDomain`
there and needs no module like this one.

**Behaviour preservation (#1704's acceptance criterion).** The handler this
domain resolves for a given tool name is the same object the pre-change
if/elif in `runner/tool_executor.py` would have resolved: terminal tools
first, then `PRODUCT_READ_TOOL_HANDLERS` for a READ-classified name, then
`PRODUCT_WRITE_TOOL_HANDLERS`. Because the two product tables have disjoint
key sets -- asserted at import time below, not assumed -- merging them and
keying on the name alone cannot reach a different handler than keying on the
name *and* the classification did.
"""

from __future__ import annotations

from juli_backend.services.agent.tools.domains import (
    PRODUCT_DOMAIN,
    ToolContext,
    ToolDomain,
    ToolDomainBindingError,
    ToolHandler,
)
from juli_backend.services.agent.tools.product import (
    PRODUCT_READ_TOOL_HANDLERS,
    ProductToolContext,
)
from juli_backend.services.agent.tools.product_write import PRODUCT_WRITE_TOOL_HANDLERS

#: The subject kind a product tool acts on -- `workflow_runs.subject_type`
#: `'product'` (#1701). A run bound to any other kind of subject is refused
#: by name at dispatch rather than silently reaching a product handler with
#: a product id invented from somewhere else; inventing one is the
#: substitution #1702 deleted from the approve path and it must not
#: reappear here as a context fallback.
PRODUCT_SUBJECT_TYPES = frozenset({"product"})

_DUPLICATE_NAMES = sorted(set(PRODUCT_READ_TOOL_HANDLERS) & set(PRODUCT_WRITE_TOOL_HANDLERS))
if _DUPLICATE_NAMES:  # pragma: no cover - a wiring defect, loud at import
    raise RuntimeError(
        "PRODUCT_READ_TOOL_HANDLERS and PRODUCT_WRITE_TOOL_HANDLERS share tool "
        f"names {_DUPLICATE_NAMES}; merging them into one domain table would "
        "silently drop one handler"
    )

#: `tool_name -> handler` for the whole product domain. Derived from the two
#: existing tables rather than re-listed, so a capability added to either one
#: is reachable here with no edit to this module.
PRODUCT_TOOL_HANDLERS: dict[str, ToolHandler] = {
    **PRODUCT_READ_TOOL_HANDLERS,
    **PRODUCT_WRITE_TOOL_HANDLERS,
}


def bind_product_context(context: ToolContext) -> ProductToolContext:
    """The `ProductToolContext` this domain's handlers take.

    Unwrapped from `ToolContext.binding`, which `ProductToolExecutor` fills
    with server-held run state bound at construction time. Refuses by name
    when the binding is absent or of another type -- an executor that was
    never given a product identity must not reach a product handler with a
    half-built context.
    """
    binding = context.binding
    if not isinstance(binding, ProductToolContext):
        raise ToolDomainBindingError(
            f"tool domain {PRODUCT_DOMAIN!r} needs a ProductToolContext bound to the "
            f"run, but this run (subject {context.subject.subject_type!r}="
            f"{context.subject.subject_ref!r}) carries "
            f"{type(binding).__name__ if binding is not None else 'no product binding'}"
        )
    return binding


PRODUCT_TOOL_DOMAIN = ToolDomain(
    name=PRODUCT_DOMAIN,
    handlers=PRODUCT_TOOL_HANDLERS,
    subject_types=PRODUCT_SUBJECT_TYPES,
    bind_context=bind_product_context,
)


__all__ = [
    "PRODUCT_SUBJECT_TYPES",
    "PRODUCT_TOOL_DOMAIN",
    "PRODUCT_TOOL_HANDLERS",
    "bind_product_context",
]
