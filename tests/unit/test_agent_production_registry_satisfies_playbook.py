"""The production tool registry must satisfy the production playbook.

DEFECT THIS PINS. `runner/core.py::_tool_definitions` resolves two sources
against the registry the runner was handed: every `PlaybookStep.tools` name,
and every `TerminationPolicy.terminal_tools` name (ADR-088). The registry the
worker actually hands it is built by
`services/agent/composition.py::build_product_tool_registry`.

When ADR-088 added `conclude_without_changes`, that production builder was not
updated -- only the playbook's own import-time validation helper and the test
registries were. Every unit and integration test passed, because each one
builds its own registry and each was taught to register the terminal tool. The
first real run to reach the forced retry crashed:

    UnknownToolError: "Unknown tool: 'conclude_without_changes'"

(run `ffc8fd40-5ec7-46a8-8d2a-f2de104fbb12`, recorded `worker_lost`).

So the failure mode is specifically that **tests which construct their own
registry cannot see a gap in the production one**. This module therefore builds
nothing: it asserts the real builder against the real playbook. Any future tool
added to a step or to `terminal_tools` without being registered in
`build_product_tool_registry` fails here rather than in production.
"""

from __future__ import annotations

import pytest

from juli_backend.services.agent.composition import build_product_tool_registry
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_PLAYBOOK,
)
from juli_backend.services.agent.tools.registry import UnknownToolError


def _names_the_runner_will_request() -> list[str]:
    """Exactly what `_tool_definitions` walks: step tools, then terminal tools."""
    names: list[str] = []
    for step in OPTIMIZE_PRODUCT_PLAYBOOK.steps:
        names.extend(step.tools)
    names.extend(OPTIMIZE_PRODUCT_PLAYBOOK.termination_policy.terminal_tools)
    return names


def test_production_registry_resolves_every_tool_the_runner_will_request():
    registry = build_product_tool_registry()
    unresolved: list[str] = []
    for name in _names_the_runner_will_request():
        try:
            registry.get(name)
        except UnknownToolError:
            unresolved.append(name)
    assert not unresolved, (
        f"build_product_tool_registry() does not register {unresolved!r}, but "
        "_tool_definitions will ask for them. This raises UnknownToolError at "
        "runtime on the first run that reaches those tools -- it cannot be "
        "caught by a test that builds its own registry."
    )


def test_terminal_tools_are_declared_and_registered():
    """Non-vacuity: the assertion above is only meaningful while the playbook
    actually declares terminal tools. If `terminal_tools` were emptied, the
    loop would pass over nothing and prove nothing."""
    terminal = OPTIMIZE_PRODUCT_PLAYBOOK.termination_policy.terminal_tools
    assert terminal, "playbook declares no terminal_tools -- the guard above is vacuous"
    registry = build_product_tool_registry()
    for name in terminal:
        assert registry.get(name).name == name


def test_registry_lookup_raises_for_a_genuinely_unknown_tool():
    """The guard relies on `registry.get` raising rather than returning a
    placeholder; pin that so the two tests above cannot silently pass."""
    with pytest.raises(UnknownToolError):
        build_product_tool_registry().get("no_such_tool_exists")
