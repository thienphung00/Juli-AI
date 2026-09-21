"""Typed frozen `Playbook` artifacts (ADR-072 decision 2) — issue #1036 (W2-A),
plus the workflow registry that resolves a `workflow_key` to the playbook and
termination policy a run executes (issue #1702, W9-A/P-SHARED-2, ADR-087 d.1).

Public API re-exported from `base.py` plus the concrete Optimize Product
playbook (`optimize_product.py`). Re-exporting them here (rather than
requiring callers to import `optimize_product.py` directly) is the depth-2
public surface a cross-top-level package (e.g. `workers/`) needs: the MMU-2
import-boundary contract (`.importlinter.toml`,
`max_cross_package_depth=2`) caps such a caller at
`juli_backend.services.agent`, matching the `runner`/`events` sibling
packages' own facade pattern (`from juli_backend.services.agent import
playbooks`, then `playbooks.get_termination_policy(key)`).

**The registry (issue #1702).** `_PLAYBOOK_REGISTRY` below is one explicit
dict literal: `workflow_key -> Playbook`. Every resolution in the runtime
goes through it --

- `services/agent/approval.py::approve_action_card` refuses a card whose key
  is absent (`WorkflowNotExecutable`, ADR-084 decision 3) and stamps the key
  it resolved onto the run;
- `workers/tasks/agent_workflow.py::_playbook_for_run` picks the playbook the
  worker actually executes off the run's own `workflow_key`;
- `workers/tasks/reaper.py` judges each run by *that run's* termination
  policy rather than one global constant.

Registering a second workflow is deliberately boring, and this is the shape
every later W9-A slice copies: import the concrete playbook module above and
add one line to the dict literal. There is no auto-discovery, no import-time
self-registration and no entry-point scan -- the registered set is readable
in one place and diffable in one line, and import order cannot change it.
The functions below all read the dict at call time, so a test that registers
a second playbook (`playbook_registered_for_test`) is exercising the same
lookup production does, not a parallel one.

Termination values are READ off the resolved `Playbook` everywhere they are
needed (the runner, #1120's in-loop termination, #1130's reaper) -- a literal
constant reproducing one of its fields anywhere else is a defect this
registry exists to make unnecessary.

Importing this package still has no side effects beyond what importing
`optimize_product.py` always had: it validates its own tool names against
the real `ToolRegistry` at import time (fail loudly on a typo), no network
access, no I/O.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from types import MappingProxyType

from juli_backend.services.agent.playbooks.base import (
    Playbook,
    PlaybookStep,
    PlaybookToolResolutionError,
    TerminationPolicy,
    validate_playbook_tools,
)
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_PLAYBOOK,
    OPTIMIZE_PRODUCT_TERMINATION_POLICY,
)

__all__ = [
    "OPTIMIZE_PRODUCT_PLAYBOOK",
    "OPTIMIZE_PRODUCT_TERMINATION_POLICY",
    "Playbook",
    "PlaybookStep",
    "PlaybookToolResolutionError",
    "TerminationPolicy",
    "UnregisteredWorkflowError",
    "get_playbook",
    "get_registered_playbooks",
    "get_termination_policy",
    "is_workflow_executable",
    "playbook_registered_for_test",
    "validate_playbook_tools",
]


class UnregisteredWorkflowError(LookupError):
    """No `Playbook` is registered for the requested `workflow_key`
    (issue #1702, ADR-087 d.1).

    Raised by `get_playbook`/`get_termination_policy` and never swallowed
    into a default: substituting the one registered playbook for an
    unrecognised key is exactly the defect #1365's audit catalogued as F3
    (approve ran Optimize Product for every card regardless of the card's
    own `workflow_key`). Callers that must not raise -- the reaper, which
    would otherwise kill a run it cannot judge -- catch this explicitly and
    leave the row alone, with a log line naming the key.
    """


#: The registered workflows, `workflow_key -> Playbook`. ONE explicit dict
#: literal, no discovery: a later W9-A workflow adds its import above and one
#: line here. `Playbook.workflow_key` is used as the key rather than a
#: hand-written string so the registry and the artifact cannot disagree.
_PLAYBOOK_REGISTRY: dict[str, Playbook] = {
    OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key: OPTIMIZE_PRODUCT_PLAYBOOK,
}


def get_registered_playbooks() -> Mapping[str, Playbook]:
    """Every registered playbook, keyed by `workflow_key`.

    A read-only *live view* of `_PLAYBOOK_REGISTRY`, not a snapshot copy --
    callers cannot mutate the registry through it, and a caller that holds it
    across a `playbook_registered_for_test` block sees the same set the
    resolution functions do.
    """
    return MappingProxyType(_PLAYBOOK_REGISTRY)


def is_workflow_executable(workflow_key: str) -> bool:
    """Whether `workflow_key` has a registered playbook (ADR-084 decision 3).

    The read-only predicate: `services/demo_decisions/read.py` uses it to
    mark a card executable in the decisions list. The approve transaction
    resolves the playbook itself (`get_playbook`) rather than asking this
    first and looking up second, so the check and the thing checked cannot
    drift apart between the two calls.
    """
    return workflow_key in _PLAYBOOK_REGISTRY


def get_playbook(workflow_key: str) -> Playbook:
    """The `Playbook` registered for `workflow_key`.

    Raises `UnregisteredWorkflowError` naming the key and the registered set
    -- never falls back to Optimize Product (see that exception's docstring).
    """
    try:
        return _PLAYBOOK_REGISTRY[workflow_key]
    except KeyError as exc:
        raise UnregisteredWorkflowError(
            f"workflow_key {workflow_key!r} has no registered playbook; "
            f"registered keys are {sorted(_PLAYBOOK_REGISTRY)}"
        ) from exc


def get_termination_policy(workflow_key: str) -> TerminationPolicy:
    """The `TerminationPolicy` of the playbook registered for `workflow_key`.

    Read off the resolved `Playbook` -- never a module constant -- so the
    reaper's thresholds and the runner's thresholds cannot drift apart for a
    workflow. Raises `UnregisteredWorkflowError` for an unregistered key.
    """
    return get_playbook(workflow_key).termination_policy


@contextmanager
def playbook_registered_for_test(playbook: Playbook) -> Iterator[Playbook]:
    """Register `playbook` for the duration of the block, then remove it.

    TEST SEAM, and deliberately a supported one rather than a private-dict
    poke in `tests/`: the acceptance criteria of #1702 are all of the form
    "a registry with two keys (the real one and a test-only playbook)", and
    every later W9-A slice needs the same two-key setup before its own
    workflow exists. Handing tests this contextmanager means they drive the
    *real* `_PLAYBOOK_REGISTRY` the real resolution functions read, which is
    the whole point -- a test that resolved against its own dict would prove
    nothing about `approve_action_card` or the reaper.

    Refuses to shadow an already-registered key: a test that silently
    replaced `optimize_product_2` would be asserting against a stand-in while
    reading like it asserted against production.
    """
    key = playbook.workflow_key
    if key in _PLAYBOOK_REGISTRY:
        raise ValueError(
            f"workflow_key {key!r} is already registered; "
            "playbook_registered_for_test never shadows a registered playbook"
        )
    _PLAYBOOK_REGISTRY[key] = playbook
    try:
        yield playbook
    finally:
        del _PLAYBOOK_REGISTRY[key]
