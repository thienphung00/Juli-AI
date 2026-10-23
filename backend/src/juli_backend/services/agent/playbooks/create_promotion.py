"""The sandbox-only "Tạo khuyến mãi" `Playbook` (fast track P65, D74).

A partner reviewer on Juli's own TikTok Shop SANDBOX shop approves a "Tạo khuyến mãi
giảm giá" card; the run creates one real product discount on TikTok through the
Promotion API, through the real agent loop: the model reads the bound product, a few
other selling products and the running promotions, chooses 1-2 products, a discount
within the range the shop's rules allow and an end date, checks them, and -- after
the reviewer's confirmation -- creates the activity, adds the products and reads it
back (``services/agent/tools/promotion_create.py``).

Sandbox only: ``services/agent/approval`` refuses a ``create_promotion`` card on any
shop that is not the sandbox-write shop; ``create_product_discount``'s handler refuses
non-sandbox resources; no other playbook lists these tools. Data-only.
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
from juli_backend.services.agent.tools.promotion_create import (
    CHECK_PROMOTION_ELIGIBILITY_TOOL,
    CREATE_PRODUCT_DISCOUNT_TOOL,
    GET_PROMOTION_CANDIDATES_TOOL,
    register_promotion_create_tools,
)
from juli_backend.services.agent.tools.registry import ToolPolicy, ToolRegistry
from juli_backend.services.agent.tools.terminal import register_terminal_tools

#: The workflow key of the card, the run and the prompt binding.
CREATE_PROMOTION_WORKFLOW_KEY = "create_promotion"
#: The card's lever code (``recommendation_payload.diagnosis.lever.code``).
CREATE_PROMOTION_LEVER = "create_promotion"

CREATE_PROMOTION_TERMINATION_POLICY: TerminationPolicy = replace(
    OPTIMIZE_PRODUCT_TERMINATION_POLICY,
    # candidates + (up to two) checks + the create, plus the model's own turns.
    max_iterations=8,
    max_extensions=1,
    required_steps=(CREATE_PRODUCT_DISCOUNT_TOOL,),
    terminal_tools=("conclude_without_changes",),
)

CREATE_PROMOTION_PLAYBOOK = Playbook(
    workflow_key=CREATE_PROMOTION_WORKFLOW_KEY,
    version=1,
    steps=(
        PlaybookStep(
            step_id="1",
            intent=(
                "Read the bound product, the shop's other selling products and the running "
                "promotions; note the allowed discount range and end dates."
            ),
            tools=(GET_PROMOTION_CANDIDATES_TOOL,),
            policy=ToolPolicy.AUTO,
        ),
        PlaybookStep(
            step_id="2",
            intent=(
                "Check the chosen products, discount and end date; if refused, fix the "
                "named value once, else stop honestly."
            ),
            tools=(CHECK_PROMOTION_ELIGIBILITY_TOOL,),
            policy=ToolPolicy.AUTO,
        ),
        PlaybookStep(
            step_id="3",
            intent=(
                "Create the product discount once the reviewer approves, then report "
                "TikTok's read-back."
            ),
            tools=(CREATE_PRODUCT_DISCOUNT_TOOL,),
            policy=ToolPolicy.CONFIRM,
        ),
    ),
    termination_policy=CREATE_PROMOTION_TERMINATION_POLICY,
)


def _build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_promotion_create_tools(registry)
    register_terminal_tools(registry)
    return registry


validate_playbook_tools(CREATE_PROMOTION_PLAYBOOK, _build_registry())

__all__ = [
    "CREATE_PROMOTION_LEVER",
    "CREATE_PROMOTION_PLAYBOOK",
    "CREATE_PROMOTION_TERMINATION_POLICY",
    "CREATE_PROMOTION_WORKFLOW_KEY",
]
