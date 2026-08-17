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

-- directly, unrestricted, and expose plain functions a cross-package
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

**Marketplace resources (issue #1173 rework, review round 1).** The initial
cut of this module left `read_resources`/`write_resources` unbuilt, citing
`ProductToolExecutor`'s own docstring ("building those from real shop
credentials is not this seam's job"). Review correctly read that line as
scoped to the *transport-guard* construction (`ProductionReadClientFactory`/
`SandboxWriteClientFactory` themselves, genuinely a different package's
concern) -- not as license to leave a composed run's first tool call
crashing uncaught (`ToolExecutionError` from `runner/tool_executor.py`,
`"requires read_resources, but this run's executor left it unset"`). This
issue's own scope bullet ("the real ADR-069 registry with guarded factories
`ProductionReadResources` / `SandboxWriteResources`") already named this
work; `build_read_resources`/`build_write_resources` below close it.

- `build_read_resources` mirrors `workers/services/polling/orchestrate.py`'s
  own `_factory_config` + `ProductionReadClientFactory().create_resources(...)`
  composition (that module's established idiom for this exact factory),
  resolving the singleton Fujiwa production-read credential via
  `resolve_production_read_credential` -- re-exported at `core.security`'s
  own depth-2 facade (`credential_resolver.py`'s `import *` there), so this
  stays a compliant depth-2 cross-package reach, not a new deep-import debt
  entry alongside `sandbox_guard.py`/`orchestrate.py`'s own grandfathered
  `core.security.credential_resolver` deep imports
  (`docs/architecture/import-boundary-baseline.json`).
- `build_write_resources` reuses `services/execution/sandbox_guard.py`'s
  `load_sandbox_write_resources` byte-for-byte -- the same call
  `services/execution/listing_handlers.py`'s `_load_listing_resources`
  already makes for its own CONFIRM-policy write tools -- rather than
  re-deriving `resolve_sandbox_write_credential` + `SandboxWriteClientFactory`
  composition a second time (same-top-level-package import, `services` ->
  `services`, unrestricted regardless of depth).
- Both need the shared TikTok Partner app credentials
  (`TIKTOK_APP_KEY`/`TIKTOK_APP_SECRET`) -- read via `require_env`, the same
  fail-closed idiom `build_llm_service` above and
  `api/routes/webhook_tiktok.py::_resolve_tiktok_credentials` already use,
  for consistency across every seam in this module (`services/execution/
  listing_handlers.py`'s own `_tiktok_app_credentials` predates that
  convention and uses `os.getenv` + a manual raise; not mirrored here).
  A missing credential *row* (no `TikTokCredential` yet provisioned for the
  Fujiwa production-read or SANDBOX_VN write merchant) fails closed via
  `resolve_production_read_credential`/`resolve_sandbox_write_credential`'s
  own `NotFound` (`juli_backend.database.exceptions`) -- no second error
  type invented here.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.config import require_env
from juli_backend.core.security import resolve_production_read_credential
from juli_backend.integrations.tiktok import (
    PRODUCTION_AUTH_ID,
    ClientFactoryConfig,
    ProductionReadClientFactory,
    ProductionReadResources,
    SandboxWriteResources,
)
from juli_backend.services.agent.llm import LLMService, resolve_llm_config
from juli_backend.services.agent.llm.openai_adapter import OpenAIResponsesAdapter
from juli_backend.services.agent.tools import ToolRegistry
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools
from juli_backend.services.execution.sandbox_guard import load_sandbox_write_resources


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


def _tiktok_app_credentials() -> tuple[str, str]:
    """The shared TikTok Partner app credentials, fail-closed via
    `require_env` -- see module docstring's "Marketplace resources"
    section for why this uses `require_env` rather than
    `services/execution/listing_handlers.py`'s older `os.getenv` idiom."""
    return require_env("TIKTOK_APP_KEY"), require_env("TIKTOK_APP_SECRET")


async def build_read_resources(session: AsyncSession) -> ProductionReadResources:
    """The real ADR-069 guarded production-read resources (issue #1173
    rework) -- the Fujiwa merchant, read-only transport guard (ADR-068:
    production credential is read-only), built the same way
    `workers/services/polling/orchestrate.py`'s own `_factory_config` +
    `ProductionReadClientFactory().create_resources(...)` composition
    already does for Fujiwa polling. Fails closed twice, in order:
    `_tiktok_app_credentials()` (`require_env`) before any DB query, then
    `resolve_production_read_credential`'s own `NotFound` when no Fujiwa
    production-read credential row has been provisioned yet.
    """
    app_key, app_secret = _tiktok_app_credentials()
    credential = await resolve_production_read_credential(session)
    return ProductionReadClientFactory().create_resources(
        ClientFactoryConfig(
            app_key=app_key,
            app_secret=app_secret,
            access_token=credential.access_token,
            merchant_auth_id=PRODUCTION_AUTH_ID,
            shop_cipher=credential.shop_cipher,
        )
    )


async def build_write_resources(session: AsyncSession) -> SandboxWriteResources:
    """The real ADR-069 guarded SANDBOX_VN write resources (issue #1173
    rework) -- reuses `services/execution/sandbox_guard.py`'s
    `load_sandbox_write_resources` outright (same credential resolution +
    `SandboxWriteClientFactory` composition `services/execution/
    listing_handlers.py`'s own CONFIRM-policy write tools already go
    through), rather than re-deriving it. ADR-068: sandbox-only for writes,
    enforced by `load_sandbox_write_resources`'s own `SANDBOX_AUTH_ID`
    assertion, not re-checked here. Fails closed the same two ways as
    `build_read_resources` above.
    """
    app_key, app_secret = _tiktok_app_credentials()
    return await load_sandbox_write_resources(session, app_key=app_key, app_secret=app_secret)
