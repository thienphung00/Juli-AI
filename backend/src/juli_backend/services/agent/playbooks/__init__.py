"""Typed frozen `Playbook` artifacts (ADR-072 decision 2) — issue #1036 (W2-A).

Public API re-exported from `base.py` plus the concrete Optimize Product
playbook (`optimize_product.py`) -- the only playbook registered in this
repo today. Re-exporting it here (rather than requiring callers to import
`optimize_product.py` directly) is the depth-2 public surface a
cross-top-level package (e.g. `workers/`) needs: the MMU-2 import-boundary
contract (`.importlinter.toml`, `max_cross_package_depth=2`) caps such a
caller at `juli_backend.services.agent`, matching the `runner`/`events`
sibling packages' own facade pattern (`from juli_backend.services.agent
import playbooks`, then `playbooks.OPTIMIZE_PRODUCT_TERMINATION_POLICY`).
Termination values are READ off this object everywhere they are needed
(the runner, #1120's in-loop termination, #1130's reaper) -- a literal
constant reproducing one of its fields anywhere else is a defect this
re-export exists to make unnecessary.

Importing this package still has no side effects beyond what importing
`optimize_product.py` always had: it validates its own tool names against
the real `ToolRegistry` at import time (fail loudly on a typo), no network
access, no I/O.
"""

from __future__ import annotations

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
    "validate_playbook_tools",
]
