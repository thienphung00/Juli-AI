"""Composition-root helpers for the two `services/agent` collaborators that
deliberately live deeper than their own package's depth-2 public facade --
issue #1173, closing the gap `workers/tasks/agent_workflow.py`'s own module
docstring names as "a small composition-root addition inside services/agent
... outside #1145's write-path allowlist, so not attempted here".

**Why this module, and why it lives here.** `.importlinter.toml`'s MMU-2
cross-package depth cap (`max_cross_package_depth = 2`) only restricts
imports that CROSS a top-level package boundary (e.g. `workers` -> the
`services` row in `[allowed_edges]`) -- `agent-runtime/scripts/ci/
check_import_boundaries.py::check_import`'s own first check
(`importer_package == target_package: return None`) never applies that cap
to an import between two files inside the SAME top-level package. This
module lives inside `services.agent` (top-level package `services`)
specifically so it can import the two depth-3+ collaborators a real
Optimize Product run needs --

- `services.agent.llm.openai_adapter.OpenAIResponsesAdapter` -- deliberately
  **not** re-exported at `services.agent.llm`'s own public facade (that
  package's `MODULE.md`: "nothing depends on a concrete adapter by
  accident"), so no depth-2 facade trick can reach it; a same-package
  import is the only sanctioned way in;
- `services.agent.tools.product.register_product_read_tools` /
  `services.agent.tools.product_write.register_product_write_tools` --
  one level below `services.agent.tools`'s own public facade, which
  re-exports only the empty `ToolRegistry` machinery itself, not the
  domain-grouped handler modules that populate one;

-- directly, unrestricted, and expose two plain functions a cross-package
caller (`workers/`) reaches through the ordinary depth-2 facade idiom this
codebase already uses everywhere else for this same package
(`from juli_backend.services.agent import composition as composition_module`,
then `composition_module.build_llm_service()` -- see
`workers/tasks/agent_workflow.py`'s own `_default_playbook`/`_construct_runner`
and `api/routes/agent_runs.py::_resolve_optimize_product_prompt_pin` for the
identical existing idiom applied to `runner`/`playbooks`/`prompts`). The
`OPTIMIZE_PRODUCT_PLAYBOOK` seam needs no such indirection -- unlike the two
above, it is already re-exported at `services.agent.playbooks`'s own
depth-2 facade (that package's own docstring), so a caller reaches it
directly via that existing facade, no composition helper required.

Nothing here constructs marketplace credentials or a `ProductionReadResources`/
`SandboxWriteResources` bundle -- `services/agent/runner/tool_executor.py`'s
own `ProductToolExecutor` docstring is explicit that building those "from
real shop credentials is not this seam's job" either; `read_resources`/
`write_resources` stay `None` on the `ProductToolExecutor`
`_construct_runner` builds, unchanged by this issue.
"""

from __future__ import annotations

from juli_backend.services.agent.llm import LLMService, resolve_llm_config
from juli_backend.services.agent.llm.openai_adapter import OpenAIResponsesAdapter
from juli_backend.services.agent.tools import ToolRegistry
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools


def build_llm_service() -> LLMService:
    """The real ADR-071 `LLMService`: the OpenAI Responses adapter.

    Fails closed *at construction time*, not on first use: `resolve_llm_config()`
    calls `require_env("OPENAI_API_KEY")` (`llm/config.py`) and raises a precise
    `RuntimeError` naming the missing variable when it is absent or blank,
    before `OpenAIResponsesAdapter` is ever built. The resolved `LLMConfig` is
    discarded here -- this function's contract is "prove the key is present",
    not "thread config into the adapter" (`OpenAIResponsesAdapter` itself
    takes no `LLMConfig` at construction; `WorkflowRunner` resolves per-call
    config separately) -- so a caller wanting env-driven model/timeout
    overrides (`LLM_MODEL` etc.) applied to the run still needs to pass its
    own `llm_config=` to `WorkflowRunner`, which `_construct_runner` does not
    do today (a narrower, separately reportable gap, not this seam's job).
    """
    resolve_llm_config()
    return OpenAIResponsesAdapter()


def build_product_tool_registry() -> ToolRegistry:
    """The real ADR-069 `ToolRegistry`, populated with all six Optimize
    Product capabilities -- the three READ specs (`tools/product.py`) and
    the three WRITE specs (`tools/product_write.py`) -- exactly as
    `ProductToolExecutor`'s dispatch (`PRODUCT_READ_TOOL_HANDLERS`/
    `PRODUCT_WRITE_TOOL_HANDLERS`) expects to find them. No credentials are
    resolved here; each handler receives its already-guarded
    `ProductionReadResources`/`SandboxWriteResources` bundle from whatever
    constructs the `ProductToolExecutor` that calls it, not from this
    registry.
    """
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    return registry
