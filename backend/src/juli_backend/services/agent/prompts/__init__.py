"""Version-addressed prompt prose files + the deterministic composer.

`optimize_product/vN.md` (issue #1037) holds the hand-written workflow prose
and `shared/<name>/vN.md` (issue #1705) the workflow-invariant sections every
workflow prompt composes from; this package's `composer.py` (issue #1038,
ADR-072 decisions 1, 2, 4 and 6) is the one place that prose joins the typed
`Playbook` artifact (#1036, resolved through #1702's playbook registry) into a
composed system prompt. Public API re-exported from `composer.py`.
"""

from __future__ import annotations

from juli_backend.services.agent.prompts.composer import (
    PROMPT_TOKEN_BUDGET_CEILING,
    SHARED_SECTION_NAMES,
    SHARED_SECTIONS,
    ComposeIntegrityError,
    UnknownWorkflowKeyError,
    UnreleasedPromptVersionError,
    compose,
    production_version,
    prompt_sha256,
    prompt_version,
    registered_workflow_keys,
    released_versions,
    shared_section_text,
    token_budget_ceiling,
)

__all__ = [
    "PROMPT_TOKEN_BUDGET_CEILING",
    "SHARED_SECTIONS",
    "SHARED_SECTION_NAMES",
    "ComposeIntegrityError",
    "UnknownWorkflowKeyError",
    "UnreleasedPromptVersionError",
    "compose",
    "production_version",
    "prompt_sha256",
    "prompt_version",
    "registered_workflow_keys",
    "released_versions",
    "shared_section_text",
    "token_budget_ceiling",
]
