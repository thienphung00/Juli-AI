"""Version-addressed prompt prose files + the deterministic composer.

`optimize_product/vN.md` (issue #1037) holds the hand-written prose; this
package's `composer.py` (issue #1038, ADR-072 decisions 2 and 4) is the one
place that prose joins the typed `Playbook` artifact (#1036) into a
composed system prompt. Public API re-exported from `composer.py`.
"""

from __future__ import annotations

from juli_backend.services.agent.prompts.composer import (
    PRODUCTION_PROMPT_VERSION,
    ComposeIntegrityError,
    UnknownWorkflowKeyError,
    UnreleasedPromptVersionError,
    compose,
    production_version,
    prompt_sha256,
    prompt_version,
)

__all__ = [
    "PRODUCTION_PROMPT_VERSION",
    "ComposeIntegrityError",
    "UnknownWorkflowKeyError",
    "UnreleasedPromptVersionError",
    "compose",
    "production_version",
    "prompt_sha256",
    "prompt_version",
]
