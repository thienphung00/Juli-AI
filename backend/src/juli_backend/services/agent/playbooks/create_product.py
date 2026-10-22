"""The sandbox-only "Tạo sản phẩm" `Playbook` (fast track P64, D73.3 / D73.4).

A partner reviewer on Juli's own TikTok Shop SANDBOX shop approves a "Tạo sản phẩm" card;
the run creates one new listing from the shop's own best-selling product (the card's
subject), through the real agent loop: the model reads the source listing and TikTok's
category candidates, picks a category and drafts a Vietnamese title / description, checks
the category's requirements, and -- after the reviewer's confirmation -- creates the
listing and reads it back (``services/agent/tools/catalog_create.py``).

Sandbox only: ``services/agent/approval`` refuses a ``create_product`` card on any shop
that is not the sandbox-write shop; ``create_product``'s handler refuses non-sandbox
resources; no other playbook lists these tools. Data-only, like ``optimize_product.py``.
"""

from __future__ import annotations

from dataclasses import replace

from juli_backend.services.agent.playbooks.base import (
    Playbook,
    PlaybookStep,
    TerminationPolicy,
    validate_playbook_tools,
)
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_TERMINATION_POLICY,
)
from juli_backend.services.agent.tools.catalog_create import (
    CHECK_LISTING_REQUIREMENTS_TOOL,
    CREATE_PRODUCT_TOOL,
    GET_CATEGORY_CANDIDATES_TOOL,
    register_catalog_create_tools,
)
from juli_backend.services.agent.tools.registry import ToolPolicy, ToolRegistry
from juli_backend.services.agent.tools.terminal import register_terminal_tools

#: The workflow key of the card, the run and the prompt binding.
CREATE_PRODUCT_WORKFLOW_KEY = "create_product"
#: The card's lever code (``recommendation_payload.diagnosis.lever.code``).
CREATE_PRODUCT_LEVER = "create_product"

CREATE_PRODUCT_TERMINATION_POLICY: TerminationPolicy = replace(
    OPTIMIZE_PRODUCT_TERMINATION_POLICY,
    # candidates + (up to two) checks + the create, plus the model's own turns.
    max_iterations=8,
    max_extensions=1,
    required_steps=(CREATE_PRODUCT_TOOL,),
    terminal_tools=("conclude_without_changes",),
)

CREATE_PRODUCT_PLAYBOOK = Playbook(
    workflow_key=CREATE_PRODUCT_WORKFLOW_KEY,
    version=1,
    steps=(
        PlaybookStep(
            step_id="1",
            intent=(
                "Read the source product and TikTok's category candidates; choose the new "
                "listing's category_id from the candidates only."
            ),
            tools=(GET_CATEGORY_CANDIDATES_TOOL,),
            policy=ToolPolicy.AUTO,
        ),
        PlaybookStep(
            step_id="2",
            intent=(
                "Check the chosen category's listing requirements; if the id is refused as "
                "not a candidate, choose again once, else stop honestly."
            ),
            tools=(CHECK_LISTING_REQUIREMENTS_TOOL,),
            policy=ToolPolicy.AUTO,
        ),
        PlaybookStep(
            step_id="3",
            intent=(
                "Create the new listing with the drafted Vietnamese title and description "
                "once the reviewer approves, then report TikTok's read-back status."
            ),
            tools=(CREATE_PRODUCT_TOOL,),
            policy=ToolPolicy.CONFIRM,
        ),
    ),
    termination_policy=CREATE_PRODUCT_TERMINATION_POLICY,
)


def _build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_catalog_create_tools(registry)
    register_terminal_tools(registry)
    return registry


validate_playbook_tools(CREATE_PRODUCT_PLAYBOOK, _build_registry())

__all__ = [
    "CREATE_PRODUCT_LEVER",
    "CREATE_PRODUCT_PLAYBOOK",
    "CREATE_PRODUCT_TERMINATION_POLICY",
    "CREATE_PRODUCT_WORKFLOW_KEY",
]
