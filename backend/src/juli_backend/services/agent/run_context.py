"""Opening context message and initial run state (issue #1188).

Two things every agent run needs before `WorkflowRunner.run()` can execute,
neither of which existed in production code until this module:

**1. A complete `RunState` blob.** `runner/core.py`'s first statement is
`conversation_store.load()`, which calls `RunState.from_dict(run.state)`.
That deserializer requires all seven `_KNOWN_FIELDS` and raises
`RunStateFieldMissingError` otherwise -- deliberately, per ADR-073 decision
5: "a corrupted or truncated blob must never be mistaken for a fresh run."
An empty `{}` therefore cannot mean "fresh run"; it can only mean
corruption. A fresh run has to be *written* complete, which is what
`initial_run_state` produces. Note what this module does NOT do: it does not
relax `from_dict`. Making the reader lenient would collapse the two cases
back together and discard exactly the guarantee ADR-073 asked for.

**2. The opening `source: "juli"` context message.**
`prompts/optimize_product/v1.md` Sec.3-4 makes this message part of the
prompt contract: the system prompt tells the model that signals, the
ActionCard rationale, and the product binding "arrive in the opening
context message", and that this is "the only place run data appears; never
woven into this prompt's own text". Without it the model is instructed to
ground its work in context it never receives -- a silent correctness
failure rather than a loud one.

The prompt's own rule governs how this module fills the message: "the real
message may omit a field with no value -- never fabricate one that is
missing." So `signals` is omitted entirely when there are none rather than
sent as `[]`, and `expected_impact` is omitted unless a real ActionCard
carries one. The rationale is taken from the ActionCard that raised the
work when one exists; when a run is started directly against a product with
no card, that fact is stated plainly instead of inventing a motive.
"""

from __future__ import annotations

import json
from typing import Any

from juli_backend.services.agent.runner import RunState

#: The `source` tag the prompt's Sec.3 source-role rules assign to Juli's
#: own server-assembled context. Never `vendor` (data, never instructions)
#: and never `seller` (preference within policy) -- see ADR-070 decision 3.
JULI_SOURCE = "juli"

#: Rationale used when a run is started directly against a product rather
#: than from an ActionCard. Honest about its own provenance: the model is
#: told this is a routine check, not given a fabricated business trigger.
DIRECT_RUN_RATIONALE = (
    "Started directly for this product rather than from a surfaced ActionCard -- "
    "treat this as a routine listing health check, with no prior signal behind it."
)


def build_opening_context_message(
    *,
    workflow_key: str,
    rationale: str,
    signals: list[dict[str, Any]] | None = None,
    expected_impact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The opening `source: "juli"` context message for a run.

    Shape follows `prompts/optimize_product/v1.md` Sec.4 exactly.
    `signals` and `expected_impact` are omitted from the result when absent,
    per that section's "never fabricate one that is missing" -- an empty
    list would read to the model as "we looked and there are none", which is
    a different claim from "no signal data accompanies this run".
    """
    message: dict[str, Any] = {
        "source": JULI_SOURCE,
        "action_card": {"workflow_key": workflow_key, "rationale": rationale},
        "product_binding": {"note": "confirms product binding; no raw vendor identifier"},
    }
    if signals:
        message["signals"] = signals
    if expected_impact:
        message["action_card"]["expected_impact"] = expected_impact
    return message


def initial_run_state(opening_context: dict[str, Any]) -> dict[str, Any]:
    """A complete `workflow_runs.state` blob for a brand-new run.

    Built from a default-constructed `RunState` so the field set can never
    drift from `RunState`'s own definition: adding a field to the dataclass
    adds it here automatically, whereas a hand-written literal would silently
    start producing blobs that `from_dict` rejects -- the exact failure this
    module exists to fix.

    The opening context travels as the first `user` message because that is
    the shape `LLMService.complete(messages=...)` consumes; its `source`
    tag lives inside the JSON payload, where the prompt's source-role rules
    look for it.
    """
    return RunState(
        conversation_window=[{"role": "user", "content": json.dumps(opening_context)}]
    ).to_dict()
