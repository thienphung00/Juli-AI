"""A real, second `Playbook` for tests that need the registry to hold more
than one workflow (issue #1702, W9-A/P-SHARED-2).

Every acceptance criterion of #1702 is of the form "a registry with two keys
(the real one and a test-only playbook)". Until a second production workflow
exists there is nothing to be the second key, so tests build one here and
register it through the registry's own
`playbooks.playbook_registered_for_test` contextmanager -- the SAME
`_PLAYBOOK_REGISTRY` `approve_action_card`, `workers/tasks/agent_workflow.py`
and the reaper all read. A test that resolved against its own dict would
prove nothing about any of them.

What this module deliberately does NOT do:

* it does not build a `**kwargs`-accepting double. `Playbook`,
  `PlaybookStep` and `TerminationPolicy` are frozen dataclasses with real
  `__post_init__` validation, and what is returned here is the real thing --
  the W9-A architect lock ("bind to real objects, never `**kwargs` doubles")
  and #1365's consumer-without-producer finding are the reason.
* it does not invent tool names. The default first step names
  `check_product_status`, a tool the production `ToolRegistry` really
  registers, so a playbook built here would survive
  `validate_playbook_tools` against the real registry. It is deliberately
  NOT `get_product_information` -- Optimize Product's first step -- because
  the whole point of the #1702 tests is to tell the two playbooks apart by
  the step that actually runs.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from juli_backend.services.agent.playbooks.base import (
    Playbook,
    PlaybookStep,
    TerminationPolicy,
)
from juli_backend.services.agent.tools.registry import ToolPolicy

#: The workflow key the test-only playbook registers under. Not a plausible
#: production key, and not one any catalog names, so a row carrying it can
#: only have come from a test.
TEST_WORKFLOW_KEY = "test_only_workflow_1702"

#: The test playbook's first step's tool. Real, registered, and NOT Optimize
#: Product's first step (`get_product_information`) -- see the module
#: docstring.
TEST_FIRST_TOOL = "check_product_status"


def make_test_playbook(
    *,
    workflow_key: str = TEST_WORKFLOW_KEY,
    first_tool: str = TEST_FIRST_TOOL,
    wall_clock_timeout_s: int = 300,
    approval_timeout_h: int = 4,
    required_steps: tuple[str, ...] = (TEST_FIRST_TOOL,),
) -> Playbook:
    """A real `Playbook` for `workflow_key`, distinguishable from Optimize
    Product by its first step and (when the caller moves them) by its
    termination numbers."""
    return Playbook(
        workflow_key=workflow_key,
        version=1,
        steps=(
            PlaybookStep(
                step_id="1",
                intent="Check whether the listing is still live before doing anything else",
                tools=(first_tool,),
                policy=ToolPolicy.AUTO,
            ),
        ),
        termination_policy=TerminationPolicy(
            max_iterations=6,
            max_extensions=1,
            extension_iterations=2,
            wall_clock_timeout_s=wall_clock_timeout_s,
            approval_timeout_h=approval_timeout_h,
            required_steps=required_steps,
        ),
    )


@contextmanager
def prompt_binding_registered_for_test(playbook: Playbook) -> Iterator[None]:
    """Give `playbook` a prompt binding and a production version pin for the
    duration of the block.

    The playbook registry and the PROMPT binding registry
    (`services/agent/prompts/composer.py`) are two separate maps on purpose
    (ADR-072 d.2: the workflow-key namespace and the prompt-directory
    namespace are not derived from one another), and #1705 kept them apart
    when it gave each workflow its own binding entry. So a test-only
    playbook still has no prose directory of its own, and
    `approve_action_card` cannot compute its `(prompt_version,
    prompt_sha256)` pin without one.

    This borrows Optimize Product's prose directory so the pin is
    computable. The prose CONTENT is irrelevant to everything these tests
    assert -- they assert which playbook and which subject the run carries,
    never what the prompt says -- and nothing here writes a file or mutates
    a released prompt. Since #1705 the binding carries no `Playbook` of its
    own: `compose()` resolves it from the playbook registry, so this helper
    requires `playbook` to be registered there (via
    `playbooks.playbook_registered_for_test`) for the pin to compute. The
    borrowed prose therefore renders the TEST playbook's steps and the pin
    differs from Optimize Product's, which is honest: it is a different
    prompt.
    """
    from juli_backend.services.agent.prompts import composer

    key = playbook.workflow_key
    assert key not in composer._WORKFLOW_BINDINGS, (
        f"workflow_key {key!r} already has a prompt binding; this helper "
        "never shadows a released one"
    )
    optimize_product_binding = composer._WORKFLOW_BINDINGS["optimize_product_2"]
    composer._WORKFLOW_BINDINGS[key] = composer._WorkflowPromptBinding(
        prompt_dir=optimize_product_binding.prompt_dir,
        production_version=optimize_product_binding.production_version,
    )
    try:
        yield
    finally:
        del composer._WORKFLOW_BINDINGS[key]
