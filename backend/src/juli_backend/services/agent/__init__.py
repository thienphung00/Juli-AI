"""Agent workflow execution package (ADR-068, ADR-071).

Parent package for the agent-loop modules landing across the
`docs/product/agent-workflow-execution/PLAN.md` phases — `llm/` (this slice,
#985) first, with tool registry, loop, and storage modules to follow as
their phases land. No provider or vendor SDK code belongs directly under
this package; each subordinate module owns its own containment boundary.
"""

from __future__ import annotations
