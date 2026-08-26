"""Optimize Product `Playbook` — issue #1036 (W2-A, ADR-072 decision 2).

The single source three consumers read: ADR-069's two-way cross-validation,
the (not-yet-built) run executor's run allowlist, and the (not-yet-built)
prompt composer's `{playbook}` slot. Because all three read this one
artifact, the text the model sees and the allowlist the executor enforces
cannot disagree.

Covers all six Optimize Product capabilities registered by W1-A
(`register_product_read_tools`, `register_product_write_tools`), in
ADR-069 decision 1's documented order, with its policy column reproduced
exactly:

| Step   | Tool                      | Class / policy                |
|--------|---------------------------|--------------------------------|
| 1      | get_product_information   | READ / AUTO                    |
| 2+3    | get_seo_keywords          | READ / AUTO (bundled)          |
| 4, 4.5 | inspect_product_image     | READ / AUTO (#1208)            |
| 5      | update_product_listing    | WRITE / CONFIRM                |
| 6      | update_product_price      | WRITE / CONFIRM (independent)  |
| 6.5    | check_product_status      | READ / AUTO                    |

Every `tools` entry below is validated against the *real* registry at
import time (`validate_playbook_tools`, called at the bottom of this
module) — a typo'd tool name fails loudly here, naming the offending step,
rather than silently later. Building the registry is pure in-memory
construction (`register_product_read_tools`/`register_product_write_tools`
declare `ToolSpec`s only — no marketplace client, no I/O); importing this
module has no side effects and no network access.

**Safety surface (ADR-072 d.2).** This module is data-only: a `Playbook`
literal plus the import-time validation call. No logic here that a future
prompt-tuning loop could redirect.
"""

from __future__ import annotations

from juli_backend.services.agent.playbooks.base import (
    Playbook,
    PlaybookStep,
    TerminationPolicy,
    validate_playbook_tools,
)
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools
from juli_backend.services.agent.tools.registry import ToolPolicy, ToolRegistry
from juli_backend.services.agent.tools.terminal import register_terminal_tools

# System-wide workflow key (ADR-069's `WORKFLOW_TOOL_CATALOG` key, also what
# ADR-077 decision 5's `WORKFLOW_OUTCOME_SUCCESS_CRITERIA` uses) -- distinct
# from the *prompt directory* name `optimize_product` (ADR-072 decision 2:
# `services/agent/prompts/optimize_product/v1.md`). The two namespaces look
# alike but are not the same thing: a future prompt composer maps this
# workflow_key to that prompt directory explicitly rather than deriving one
# from the other. `TestWorkflowKeyMatchesCatalog` (tests/unit) pins this so
# it can't silently drift back to the prompt-directory spelling.
WORKFLOW_KEY = "optimize_product_2"

# ADR-073 decision 2: Optimize Product v1 termination values. "Did the job"
# is defined by the two seller-confirmed writes -- the listing content change
# and the price change -- even though either is independently rejectable
# (a final_response with only one, or neither, confirmed is honest outcome
# data for the execution-quality metric, not a synthetic failure).
# ADR-088 decision 1: terminal_tools added to allow the model to explicitly
# conclude without changes when the forced-retry mechanism is invoked.
OPTIMIZE_PRODUCT_TERMINATION_POLICY = TerminationPolicy(
    max_iterations=6,
    max_extensions=1,
    extension_iterations=2,
    wall_clock_timeout_s=300,
    approval_timeout_h=4,
    required_steps=("update_product_listing", "update_product_price"),
    terminal_tools=("conclude_without_changes",),
)

OPTIMIZE_PRODUCT_PLAYBOOK = Playbook(
    workflow_key=WORKFLOW_KEY,
    version=1,
    steps=(
        PlaybookStep(
            step_id="1",
            intent=(
                "Read the product's current listing -- title, description, price, "
                "and images -- so every recommendation is grounded in what the "
                "seller already has, not invented."
            ),
            tools=("get_product_information",),
            policy=ToolPolicy.AUTO,
        ),
        PlaybookStep(
            step_id="2+3",
            intent=(
                "Gather SEO keyword ideas and suggested title/description phrasing "
                "to inform the improved listing copy."
            ),
            tools=("get_seo_keywords",),
            policy=ToolPolicy.AUTO,
        ),
        PlaybookStep(
            step_id="4, 4.5",
            intent=(
                "Check whether the product's main photo actually matches its title "
                "and description, and note any image changes worth making -- looking "
                "only, nothing is changed."
            ),
            tools=("inspect_product_image",),
            policy=ToolPolicy.AUTO,
        ),
        PlaybookStep(
            step_id="5",
            intent=(
                "Publish the improved title, description, and staged photo to the "
                "live listing, once the seller approves the change."
            ),
            tools=("update_product_listing",),
            policy=ToolPolicy.CONFIRM,
        ),
        PlaybookStep(
            step_id="6",
            intent=(
                "Update the product's price to the recommended value, once the "
                "seller approves it -- a separate decision from the listing "
                "content change, and rejectable on its own."
            ),
            tools=("update_product_price",),
            policy=ToolPolicy.CONFIRM,
        ),
        PlaybookStep(
            step_id="6.5",
            intent=(
                "Check the product's listing status right after the update, so the "
                "seller knows whether it's live or still under review."
            ),
            tools=("check_product_status",),
            policy=ToolPolicy.AUTO,
        ),
    ),
    termination_policy=OPTIMIZE_PRODUCT_TERMINATION_POLICY,
)


def _build_registry() -> ToolRegistry:
    """The full current universe of registered agent capabilities (W1-A),
    built fresh (no shared/default registry instance exists yet) purely to
    validate this playbook's tool names at import time. Pure in-memory
    construction -- no marketplace client, no I/O, no network access."""
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    register_terminal_tools(registry)
    return registry


# Fail loudly at import time if a step names a tool that doesn't resolve.
validate_playbook_tools(OPTIMIZE_PRODUCT_PLAYBOOK, _build_registry())
