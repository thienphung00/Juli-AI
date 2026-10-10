"""The content-run playbooks (fast track P14-E, D24.18).

Declared here, beside Optimize Product's, so the registry imports no service
package: the run's planner and tools live in ``services/content_cards``, and
only their names are needed here (``content_cards.constants``). The tool names
are checked against the real registry by ``test_p14_content_flow.py``.

Order: read the content performance → the listing → SEO words (video) / the
running flash sales (LIVE) → draft → wait for the seller → wait for the video /
the LIVE → look for it read-only → measure. No CONFIRM step: nothing is written.
"""

from __future__ import annotations

from dataclasses import replace

from juli_backend.services.agent.playbooks.base import Playbook, PlaybookStep, TerminationPolicy
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_TERMINATION_POLICY,
)
from juli_backend.services.agent.tools.registry import ToolPolicy
from juli_backend.services.content_cards.constants import (
    CHOICE_WAIT_HOURS,
    CONTENT_LIVE_WORKFLOW_KEY,
    CONTENT_PERFORMANCE_TOOL,
    CONTENT_VIDEO_WORKFLOW_KEY,
    FIND_NEW_CONTENT_TOOL,
    PUBLISH_WAIT_HOURS,
)

READ_TOOL = "get_product_information"
SEO_TOOL = "get_seo_keywords"
PROMOTIONS_TOOL = "find_product_promotions"

CONTENT_TERMINATION_POLICY: TerminationPolicy = replace(
    OPTIMIZE_PRODUCT_TERMINATION_POLICY,
    # Reads (4) + rules + 2 drafts + 3 suspensions + detection + the close.
    max_iterations=24,
    max_extensions=0,
    required_steps=(CONTENT_PERFORMANCE_TOOL,),
    terminal_tools=(),
    external_wait_timeout_h=PUBLISH_WAIT_HOURS,
)
#: The reaper's policy while the run waits for the seller's choice (3 days) ...
CHOICE_WAIT_POLICY = replace(CONTENT_TERMINATION_POLICY, external_wait_timeout_h=CHOICE_WAIT_HOURS)
#: ... and while it waits for the video / the LIVE (7 days).
PUBLISH_WAIT_POLICY = CONTENT_TERMINATION_POLICY


def _playbook(workflow_key: str, *, video: bool) -> Playbook:
    second = SEO_TOOL if video else PROMOTIONS_TOOL
    return Playbook(
        workflow_key=workflow_key,
        version=1,
        steps=(
            PlaybookStep(
                step_id="content-1",
                intent=(
                    "Read the product's video (or LIVE) performance, its listing and its "
                    + ("SEO words." if video else "running flash sales.")
                ),
                tools=(CONTENT_PERFORMANCE_TOOL, READ_TOOL, second),
                policy=ToolPolicy.AUTO,
            ),
            PlaybookStep(
                step_id="content-2",
                intent=(
                    "After the seller posts the video / goes live, look for it on TikTok, "
                    "read-only."
                ),
                tools=(FIND_NEW_CONTENT_TOOL,),
                policy=ToolPolicy.AUTO,
            ),
        ),
        termination_policy=CONTENT_TERMINATION_POLICY,
    )


CONTENT_VIDEO_PLAYBOOK = _playbook(CONTENT_VIDEO_WORKFLOW_KEY, video=True)
CONTENT_LIVE_PLAYBOOK = _playbook(CONTENT_LIVE_WORKFLOW_KEY, video=False)

__all__ = [
    "CHOICE_WAIT_POLICY",
    "CONTENT_LIVE_PLAYBOOK",
    "CONTENT_TERMINATION_POLICY",
    "CONTENT_VIDEO_PLAYBOOK",
    "PROMOTIONS_TOOL",
    "PUBLISH_WAIT_POLICY",
    "READ_TOOL",
    "SEO_TOOL",
]
