"""Vietnamese seller-facing copy for `workflow.status` `phase_narration`
(issue #1140; ADR-074 decision 2 lists the field explicitly as VI copy;
`events/payloads.py::WorkflowStatusPayload`'s own docstring makes the same
claim). This module is what makes that claim true.

**Why a standalone module, not an inline f-string in `runner/termination.py`.**
`termination.py::extension_grant_narration` is *policy* code -- it decides
*when* a narration fires and reads every number from the caller's
`TerminationPolicy`. The Vietnamese sentence itself is *copy* -- what the
narration says -- and copy is what grows: today there is exactly one
producer (the extension grant), but every future narration the runner adds
belongs here too, as one more function, rather than as one more scattered
f-string next to unrelated gate-evaluation logic. This mirrors
`services/scoring/copy_layer.py`'s split between decision logic (its
`_WORKFLOW_COPY_TEMPLATES` callers) and copy text -- **without importing
that module**: `copy_layer.py` is a different subsystem (the deterministic
rules-based ActionCard copy layer) on a different release cadence, not
consumed by the runner. It is read here only as a register/terminology
reference, never as a dependency.

**Governance (ADR-028, ADR-072 decision 3).** Every string this module
returns must be dictionary-compliant Vietnamese and free of the
`AGENT_OUTPUT_SCOPE` banned patterns (`services/agent/sanitize/banned_patterns.py`)
-- proven by `tests/unit/test_agent_narration_copy.py`, which calls the real
shared loader, never a hand-copied pattern list. This narration is a
system status line about the run's own progress, not a sentence addressing
the seller in second person, so it follows the register of `dictionary.md`'s
third-person status/toast phrases (e.g. `toast.decision.approved`, "Đã phê
duyệt đề xuất.") rather than ADR-072 decision 3's "bạn" rule, which governs
the agent's direct-address final response text. The corresponding
`dictionary.md` phrase key is `agent.narration.extension_grant`.

**What a machine cannot check.** The banned-pattern gate and the dynamic-number
tests below prove the copy is well-formed and safe; neither can judge
Vietnamese register or tone. A human voice review against `dictionary.md`
and `docs/product/design/design-context.md` is still outstanding for the
string in this module (tracked on issue #1140, following #1120's and
#1071's precedent of disclosing this rather than papering over it with a
mechanical "looks Vietnamese" heuristic).

**Number formatting.** Vietnamese carries no plural inflection -- "lượt"
(turn/iteration) reads identically whether the count is 1 or 5, so there is
no Vietnamese equivalent of English's "iteration(s)" to construct and none
is attempted here. The extension-grant fraction is rendered `granted/max`
(e.g. `1/1`) rather than translating the English "extension N of M"
preposition, which has no natural Vietnamese equivalent either. Every
number is a function parameter, sourced by the caller from
`TerminationPolicy` -- this module defines no policy constant of its own.
"""

from __future__ import annotations


def extension_grant_phase_narration(
    *,
    extension_iterations: int,
    extensions_granted_after_grant: int,
    max_extensions: int,
) -> str:
    """Vietnamese `phase_narration` for one iteration-cap extension grant.

    `extension_iterations` -- how many more iterations this grant adds;
    `extensions_granted_after_grant` / `max_extensions` -- the running count
    of grants used so far, out of the policy's total allowance. All three
    are read off `TerminationPolicy` by the caller
    (`runner/termination.py::extension_grant_narration`); this function
    holds no numeric literal of its own.
    """
    return (
        "Đã đạt giới hạn số lượt thực hiện tiêu chuẩn, Juli gia hạn thêm "
        f"{extension_iterations} lượt để hoàn tất công việc "
        f"(lần gia hạn {extensions_granted_after_grant}/{max_extensions})."
    )
