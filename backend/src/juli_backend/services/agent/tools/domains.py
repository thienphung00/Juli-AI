"""Tool domain types -- issue #1704 (W9-A/P-SHARED-4, spec P0-3).

A **tool domain** is the family of tools that share one handler table, one
rule for which run subjects they can act on, and one way of turning the
subject-generic `ToolContext` into whatever object their handlers actually
take. `product` is the first one; it is no longer the only one the runtime
can express.

This module is the *types* half of the pattern `playbooks/` already
establishes: `playbooks/base.py` holds `Playbook`/`TerminationPolicy` and
`playbooks/__init__.py` holds the one dict literal that registers them.
Here, `domains.py` holds `ToolDomain`/`ToolContext`/`RunSubject` and
`domain_registry.py` holds the dict literal. The split is not cosmetic: a
domain artifact (`product_domain.py`'s `PRODUCT_TOOL_DOMAIN`) has to import
`ToolDomain`, and the registry has to import the artifact, so the types
cannot live in the registry without a cycle.

**Why a subject-generic context at all.** Before this slice the only context
a handler could receive was `ProductToolContext`, built inside
`runner/tool_executor.py` from a constructor-bound `product_id`. A tool
about a dispatch window or a SKU set had nowhere to put its subject, so it
could not be written at all. `ToolContext` carries the *run's* subject
(`RunSubject`, the `workflow_runs.subject_type`/`subject_ref` pair #1701
added) plus the already-guarded marketplace resources for this call, and
nothing else. Anything domain-specific travels in `binding`, opaque to this
module and to the executor, and is unwrapped by the domain's own
`bind_context`.

**The subject never comes from the model.** `RunSubject` is server-held run
state threaded in at executor construction, exactly as `product_id` always
was (see `runner/tool_executor.py`'s docstring on why the bound context is
constructor state). A subject read out of a tool argument would be a
prompt-injection surface; nothing here reads `params`.

**Failures are named, never silent.** Every way a dispatch can fail to
resolve raises one of the three errors below, each naming the domain, the
tool and the run's subject. A tool that resolves to a domain it does not
belong to is a wiring defect and must be loud: the failure mode this slice
exists to prevent is a tool that quietly stops being reachable, or one that
quietly becomes reachable from a domain it should not be.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

#: The product domain: every Optimize Product READ and WRITE capability
#: (`product.py`, `product_write.py`). Named here rather than spelled inline
#: in each spec so the specs and the registry cannot disagree about the
#: string, and so this module stays a leaf both the spec modules and the
#: registry can import.
PRODUCT_DOMAIN = "product"

#: The terminal domain: side-effect-free tools that end a run rather than
#: acting on its subject (`terminal.py`, ADR-088 decision 1). Subject-agnostic
#: and resource-free -- see `ToolDomain.subject_types` / `takes_resources`.
TERMINAL_DOMAIN = "terminal"

#: A tool handler, in the shape every handler in this package already has:
#: `(resources, context, params) -> BaseModel`. The middle argument is
#: whatever the domain's `bind_context` produced, which is why it is `Any`
#: here and a `ProductToolContext` inside `product.py`.
ToolHandler = Callable[[Any, Any, Any], BaseModel]

#: Turns the subject-generic `ToolContext` into the object a domain's own
#: handlers take.
ContextBinder = Callable[["ToolContext"], Any]


class ToolDomainError(RuntimeError):
    """Base for every domain-resolution failure.

    A `RuntimeError` for the same reason `runner/tool_executor.py`'s
    `ToolExecutionError` is one: these are wiring defects surfacing at
    dispatch, not ordinary runtime outcomes, and the caller that drives
    `WorkflowRunner` already treats an unhandled exception out of `execute`
    as a failed run. They are deliberately NOT subclasses of
    `ToolExecutionError`: that class lives in `runner/`, which imports this
    package, and the reverse edge would be a cycle.
    """


class UnregisteredToolDomainError(ToolDomainError):
    """The spec's `domain` has no entry in `domain_registry.py`.

    Names the domain and the registered set, the way
    `playbooks.UnregisteredWorkflowError` does -- never falls back to the
    product domain. Substituting the one domain that exists for an
    unrecognised one is the tool-dispatch form of the defect #1365
    catalogued as F3 in the playbook registry.
    """


class ToolNotInDomainError(ToolDomainError):
    """The tool name is not in that domain's handler table.

    Reached when a spec declares a domain whose handler table does not
    contain it -- a tool that resolved to the WRONG domain. Before this
    slice the equivalent mistake was invisible: the executor's if/elif fell
    through to the product WRITE table for anything not READ-classified, so
    a mis-declared tool either ran a product handler or vanished.
    """


class ToolDomainBindingError(ToolDomainError):
    """This run cannot supply what the domain needs.

    Two causes, both fail-closed refusals at the same point, and the message
    names which: the run's subject is a kind this domain does not act on
    (a product tool reached from a run bound to a SKU set), or the domain's
    bound state is absent or of the wrong type (a product tool reached from
    an executor that was never given a product binding).
    """


@dataclass(frozen=True)
class RunSubject:
    """What a run is about -- `workflow_runs.subject_type`/`subject_ref`.

    The polymorphic subject #1701 added and #1702 stamps from the approved
    card. `subject_ref` is text rather than a UUID because a non-product
    subject may carry no single UUID primary key (ADR-087 decision 1).
    """

    subject_type: str
    subject_ref: str

    def __post_init__(self) -> None:
        if not self.subject_type:
            raise ValueError("RunSubject.subject_type must be a non-empty string")
        if not self.subject_ref:
            raise ValueError("RunSubject.subject_ref must be a non-empty string")


@dataclass(frozen=True)
class ToolContext:
    """The subject-generic per-call tool context (spec P0-3).

    Deliberately carries no product id, and no field naming any other single
    subject kind: a context that still has a `product_id` attribute for a run
    about a SKU set is the product assumption this slice removes, not a
    harmless extra. A domain that needs more than the subject puts it in
    `binding` and unwraps it in its own `bind_context`.
    """

    #: The run's subject, from server-held run state -- never from `params`.
    subject: RunSubject
    #: The already-guarded marketplace resource bundle selected for this call
    #: by the tool's own classification, or `None` for a domain that takes no
    #: resources. Building the bundle is not this seam's job.
    resources: Any | None = None
    #: The domain's own bound state, opaque here. `None` for a domain whose
    #: handlers need nothing beyond the subject.
    binding: Any | None = None


def subject_generic_context(context: ToolContext) -> ToolContext:
    """The default `bind_context`: hand the handler the generic context.

    A domain whose handlers read the subject directly needs no binding step
    at all, so this is the identity. It is a named module-level function
    rather than a lambda so a `ToolDomain` is comparable and its repr is
    readable.
    """
    return context


@dataclass(frozen=True)
class ToolDomain:
    """One domain's handler table and its binding rules.

    Registering a WRITE-CONFIRM tool is one entry in `handlers` plus one
    spec carrying this domain's `name` -- both in the domain's own module,
    with no edit anywhere in `runner/`.
    """

    name: str
    #: `tool_name -> handler`. The executor resolves through THIS table and
    #: no other, so a tool absent from it is unreachable by construction and
    #: raises `ToolNotInDomainError` rather than falling through.
    handlers: Mapping[str, ToolHandler]
    #: The subject kinds this domain acts on, or `None` for subject-agnostic
    #: (the terminal domain ends a run whatever the run is about).
    subject_types: frozenset[str] | None = None
    #: Whether handlers take a marketplace resource bundle. `False` for a
    #: domain whose tools are side-effect-free by construction, which is what
    #: lets a terminal tool run on an executor built with no resources at all.
    takes_resources: bool = True
    bind_context: ContextBinder = subject_generic_context

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("ToolDomain.name must be a non-empty string")
        if not self.handlers:
            raise ValueError(f"ToolDomain {self.name!r} must register at least one handler")
        if self.subject_types is not None and not self.subject_types:
            raise ValueError(
                f"ToolDomain {self.name!r} declares an empty subject_types set; use None "
                "for a subject-agnostic domain so 'acts on nothing' cannot read as 'acts "
                "on anything'"
            )

    def handler_for(self, tool_name: str) -> ToolHandler:
        """This domain's handler for `tool_name`.

        Raises `ToolNotInDomainError` naming the domain, the tool and the
        domain's own tool names -- the "resolved to the wrong domain" case.
        """
        try:
            return self.handlers[tool_name]
        except KeyError as exc:
            raise ToolNotInDomainError(
                f"tool {tool_name!r} declares domain {self.name!r} but that domain "
                f"registers no handler for it; its tools are {sorted(self.handlers)}"
            ) from exc

    def check_subject(self, subject: RunSubject) -> None:
        """Refuse, by name, a run whose subject this domain does not act on.

        Called by the executor BEFORE it selects a resource bundle, so a run
        bound to a SKU set asking for a product tool is told that — rather
        than being told, misleadingly, that the executor has no
        `read_resources`, which is true but not the reason. A
        subject-agnostic domain (`subject_types is None`) never refuses here.
        """
        if self.subject_types is not None and subject.subject_type not in self.subject_types:
            raise ToolDomainBindingError(
                f"tool domain {self.name!r} acts on subject kinds "
                f"{sorted(self.subject_types)}, but this run's subject is "
                f"{subject.subject_type!r}"
            )

    def context_for(self, context: ToolContext) -> Any:
        """The object this domain's handlers take, built from `context`.

        Re-checks the subject before unwrapping, so this method is safe on
        its own and does not depend on the caller having called
        `check_subject` first — the subject test is a cheap set membership
        and running it twice is cheaper than a seam that is only correct in
        one call order.
        """
        self.check_subject(context.subject)
        return self.bind_context(context)


__all__ = [
    "PRODUCT_DOMAIN",
    "TERMINAL_DOMAIN",
    "ContextBinder",
    "RunSubject",
    "ToolContext",
    "ToolDomain",
    "ToolDomainBindingError",
    "ToolDomainError",
    "ToolHandler",
    "ToolNotInDomainError",
    "UnregisteredToolDomainError",
    "subject_generic_context",
]
