"""Terminal tool for completing a run without proposing changes (ADR-088 decision 1).

The `conclude_without_changes` tool is a side-effect-free terminal tool that allows
the model to explicitly end a run when it has determined that no action is needed,
while still satisfying required_steps constraints through the forced-retry mechanism
in `runner/core.py`.

This tool is registered for playbooks whose `TerminationPolicy` declares
`required_steps` — it makes the forced retry (invoked when a text-only turn leaves
required steps incomplete) safe by providing an honest alternative to emitting a
bogus write.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from juli_backend.services.agent.tools.registry import (
    ToolClassification,
    ToolPolicy,
    ToolRegistry,
    ToolSpec,
)


class ConcludeWithoutChangesInput(BaseModel):
    """Input for the conclude_without_changes terminal tool."""

    reason: str = Field(
        ...,
        description=(
            "A brief, honest explanation of why no action is needed for this product "
            "right now (e.g., 'The current listing is already well-optimized', "
            "'The product needs more data before recommendations can be made', etc.)"
        ),
    )


class ConcludeWithoutChangesOutput(BaseModel):
    """Output of the conclude_without_changes terminal tool.

    Always succeeds — the tool has no side effects and cannot fail. The presence
    of this tool call in the conversation window is what marks the run terminal
    with `stop_reason=concluded_without_changes`.
    """

    acknowledged: bool = Field(
        default=True,
        description="Always true — this tool always succeeds.",
    )


def handle_conclude_without_changes(
    resources,  # Unused: this tool has no resource dependencies
    context,  # Unused: this tool has no product context dependencies
    params: ConcludeWithoutChangesInput,
) -> ConcludeWithoutChangesOutput:
    """Strictly side-effect-free terminal tool handler.

    Takes the provided reason string and returns success. The tool has no
    external effects and performs no writes of any kind. Its only purpose
    is to provide a legitimate way for the model to end a run when the
    forced-retry mechanism is invoked but no action is actually needed.

    Signature matches ProductToolExecutor's expected handler interface:
    (resources, context, params) -> BaseModel.
    """
    # Intentionally do nothing with the reason or context — it is logged in the
    # conversation window by the runner, and the tool's only purpose is
    # to provide a callable endpoint. All side-effect-free by construction.
    return ConcludeWithoutChangesOutput(acknowledged=True)


CONCLUDE_WITHOUT_CHANGES_SPEC = ToolSpec(
    name="conclude_without_changes",
    description=(
        "Conclude this optimization run without proposing any changes. Use this "
        "when you have completed your analysis and determined that the product "
        "is already well-optimized, or when you need more information to make "
        "a recommendation. Provide a brief, honest reason for your conclusion."
    ),
    input_model=ConcludeWithoutChangesInput,
    output_model=ConcludeWithoutChangesOutput,
    classification=ToolClassification.READ,
    policy=ToolPolicy.AUTO,
    timeout_seconds=1,
)


# Mirrors PRODUCT_READ_TOOL_HANDLERS' shape (tools/product.py) so the executor
# can dispatch all three families uniformly. The first two positions are the
# resources and product context every product handler takes; a terminal tool
# needs neither, which is exactly what makes it side-effect-free, so they are
# typed `Any` and ignored rather than narrowed to something this tool would
# then be tempted to use.
TERMINAL_TOOL_HANDLERS: dict[str, Callable[[Any, Any, Any], BaseModel]] = {
    CONCLUDE_WITHOUT_CHANGES_SPEC.name: handle_conclude_without_changes,
}


def register_terminal_tools(registry: ToolRegistry) -> None:
    """Register terminal tools for runs with required_steps constraints."""
    registry.register(CONCLUDE_WITHOUT_CHANGES_SPEC)
