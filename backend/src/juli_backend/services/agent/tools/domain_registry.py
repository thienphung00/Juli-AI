"""The tool domain registry -- issue #1704 (W9-A/P-SHARED-4, spec P0-3).

`_TOOL_DOMAIN_REGISTRY` below is one explicit dict literal: `domain name ->
`ToolDomain`. Every tool dispatch in the runtime goes through it --
`runner/tool_executor.py` resolves the domain named on the tool's own spec
and calls that domain's handler, instead of falling through an if/elif over
three module-level dicts imported at the top of the executor.

This is deliberately the same shape as `playbooks/__init__.py`, the exemplar
this wave copies: import the concrete artifact module above and add one line
to the dict literal. There is no auto-discovery, no import-time
self-registration and no entry-point scan -- the registered set is readable
in one place and diffable in one line, and import order cannot change it.
The functions below all read the dict at call time, so a test that registers
a second domain (`tool_domain_registered_for_test`) exercises the same
lookup production does, not a parallel one.

**What "registering a tool" now means, end to end.** A new WRITE-CONFIRM
capability is: one handler in its domain module's table, and one spec whose
`domain` names that domain. Nothing in `runner/` moves, and the CONFIRM
pause is unchanged -- `WorkflowRunner` pauses on `ToolSpec.policy`, which is
a property of the tool and never of its domain (ADR-075's consent binding;
a per-domain confirm rule would fork the consent model).

Importing this package has no side effects beyond what importing the domain
modules always had: no network access, no I/O.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from types import MappingProxyType

from juli_backend.services.agent.tools.domains import (
    ToolDomain,
    UnregisteredToolDomainError,
)
from juli_backend.services.agent.tools.product_domain import PRODUCT_TOOL_DOMAIN
from juli_backend.services.agent.tools.terminal import TERMINAL_TOOL_DOMAIN

#: The registered tool domains, `name -> ToolDomain`. ONE explicit dict
#: literal, no discovery: a later domain adds its import above and one line
#: here. `ToolDomain.name` is used as the key rather than a hand-written
#: string so the registry and the artifact cannot disagree.
_TOOL_DOMAIN_REGISTRY: dict[str, ToolDomain] = {
    PRODUCT_TOOL_DOMAIN.name: PRODUCT_TOOL_DOMAIN,
    TERMINAL_TOOL_DOMAIN.name: TERMINAL_TOOL_DOMAIN,
}


def get_registered_tool_domains() -> Mapping[str, ToolDomain]:
    """Every registered domain, keyed by name.

    A read-only *live view* of the registry, not a snapshot copy -- callers
    cannot mutate the registry through it, and a caller that holds it across
    a `tool_domain_registered_for_test` block sees the same set the
    resolution functions do.
    """
    return MappingProxyType(_TOOL_DOMAIN_REGISTRY)


def is_tool_domain_registered(name: str) -> bool:
    """Whether `name` has a registered domain."""
    return name in _TOOL_DOMAIN_REGISTRY


def get_tool_domain(name: str) -> ToolDomain:
    """The `ToolDomain` registered under `name`.

    Raises `UnregisteredToolDomainError` naming the domain and the
    registered set -- never falls back to the product domain.
    """
    try:
        return _TOOL_DOMAIN_REGISTRY[name]
    except KeyError as exc:
        raise UnregisteredToolDomainError(
            f"tool domain {name!r} is not registered; registered domains are "
            f"{sorted(_TOOL_DOMAIN_REGISTRY)}"
        ) from exc


def reachable_tool_names() -> frozenset[str]:
    """Every tool name any registered domain can dispatch.

    DERIVED from the registered domains' own handler tables, never a second
    hand-maintained list: a tool becomes reachable purely by being in its
    domain's table, and a tool that drops out of one becomes unreachable
    here in the same breath. Tests assert reachability against this rather
    than against a literal set of names, because a hand-listed expectation
    cannot notice a tool that quietly stopped being dispatchable.
    """
    names: set[str] = set()
    for domain in _TOOL_DOMAIN_REGISTRY.values():
        names |= set(domain.handlers)
    return frozenset(names)


def bindable_subject_types() -> frozenset[str]:
    """Every subject kind some registered domain can act on.

    A run whose subject is outside this set has no tool that could touch it.
    Derived, for the same reason `reachable_tool_names` is: the runtime's
    idea of "a subject we can act on" must move when a domain is registered
    or removed, not when someone remembers to edit a constant.

    A subject-agnostic domain (`subject_types is None`, the terminal domain)
    contributes nothing: it can end any run, which is not the same as being
    able to act on any subject.
    """
    kinds: set[str] = set()
    for domain in _TOOL_DOMAIN_REGISTRY.values():
        if domain.subject_types is not None:
            kinds |= set(domain.subject_types)
    return frozenset(kinds)


@contextmanager
def tool_domain_registered_for_test(domain: ToolDomain) -> Iterator[ToolDomain]:
    """Register `domain` for the duration of the block, then remove it.

    TEST SEAM, and deliberately a supported one rather than a private-dict
    poke in `tests/`: the acceptance criteria of #1704 are all of the form
    "a registry with two domains (the real product one and a test-only
    `inventory`)", and every later slice that adds a domain needs the same
    setup before its own domain exists. Handing tests this contextmanager
    means they drive the *real* registry the real dispatch reads, which is
    the whole point -- a test that resolved against its own dict would prove
    nothing about `ProductToolExecutor`.

    Refuses to shadow an already-registered name: a test that silently
    replaced `product` would be asserting against a stand-in while reading
    like it asserted against production.
    """
    name = domain.name
    if name in _TOOL_DOMAIN_REGISTRY:
        raise ValueError(
            f"tool domain {name!r} is already registered; "
            "tool_domain_registered_for_test never shadows a registered domain"
        )
    _TOOL_DOMAIN_REGISTRY[name] = domain
    try:
        yield domain
    finally:
        del _TOOL_DOMAIN_REGISTRY[name]


__all__ = [
    "bindable_subject_types",
    "get_registered_tool_domains",
    "get_tool_domain",
    "is_tool_domain_registered",
    "reachable_tool_names",
    "tool_domain_registered_for_test",
]
