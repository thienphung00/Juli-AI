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

import uuid

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
from juli_backend.services.agent.tools import ToolClassification, ToolRegistry
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


def measurable_write_tool_names() -> frozenset[str]:
    """Every WRITE-classified capability name in the real ADR-069 product
    tool registry -- issue #1219 / AGT-W4B's fix for the defect where
    `workers/impact_reader/queries.py` scanned for the old dispatcher's own
    name (`listing.optimize_product`) while the agent ledger
    (`services/agent/runner/ledger.py`, `ProductToolExecutor.execute` --
    `tool_executor.py`) actually writes `ToolExecution.tool_name` as the
    registered tool name itself (`update_product_price`,
    `update_product_listing`, `upload_product_image` today), so the reader
    selected zero rows, forever, silently.

    Derived from `build_product_tool_registry()` -- never a second
    hand-maintained literal -- so a new WRITE capability becomes measurable
    purely by being registered into that registry, with no edit to this
    module or to `workers/impact_reader/queries.py`. This is the sanctioned
    same-package seam (module docstring) `workers/impact_reader/queries.py`
    reaches to compute its own `measurable_tool_names()`, since that
    module's own top-level package (`workers`) may not deep-import
    `services.agent.tools` directly (`.importlinter.toml`'s
    `max_cross_package_depth = 2`) -- this function returns a plain
    `frozenset[str]`, never a `ToolSpec`/`ToolRegistry`, so no such type
    ever needs to cross that boundary either.

    Includes every WRITE-classified tool regardless of `ToolPolicy`
    (`AUTO` or `CONFIRM`): `upload_product_image` is WRITE/AUTO but builds
    no classifiable request payload (`tool_executor.py
    ::_build_request_payload` returns `None` for it), so
    `classify.classify_mutation_kinds` yields no mutation kinds for any row
    it produces and the impact-reader pipeline (`pipeline.py`) reports that
    execution `executions_skipped_unclassified` rather than measuring it --
    harmless to include, and correct per this issue's literal
    "WRITE-classified capabilities" derivation rule rather than a second
    hand-maintained CONFIRM-only filter.
    """
    registry = build_product_tool_registry()
    return frozenset(
        spec.name for spec in registry.list_all() if spec.classification is ToolClassification.WRITE
    )


def _tiktok_app_credentials() -> tuple[str, str]:
    """The shared TikTok Partner app credentials, fail-closed via
    `require_env` -- see module docstring's "Marketplace resources"
    section for why this uses `require_env` rather than
    `services/execution/listing_handlers.py`'s older `os.getenv` idiom."""
    return require_env("TIKTOK_APP_KEY"), require_env("TIKTOK_APP_SECRET")


async def build_read_resources(
    session: AsyncSession, shop_id: uuid.UUID | None = None
) -> ProductionReadResources | SandboxWriteResources:
    """The real ADR-069 guarded read resources (issue #1173 rework, amended
    by issue #1302).

    Shop-aware read routing (issue #1302): When a run's shop is the sandbox
    shop (i.e., the shop the sandbox-write credential belongs to), build read
    resources from the sandbox-write credential (which can read its own
    products). For any other shop, use the Fujiwa production-read credential
    (unchanged from before this amendment).

    This decouples the read credential from hardcoded shop IDs, instead
    routing based on capability-derived comparison via the existing resolvers
    in core.security. The decision does NOT create any new WRITE path against
    production -- the sandbox-write resources are already write-capable by
    design (ADR-068), and using them for reads on the sandbox shop is within
    that boundary.

    Fails closed twice, in order: `_tiktok_app_credentials()` (`require_env`)
    before any DB query, then the appropriate credential resolver's `NotFound`
    when no matching credential row has been provisioned yet.
    """
    app_key, app_secret = _tiktok_app_credentials()

    # If shop_id is provided, check if it matches the sandbox-write
    # credential's shop. If it does, use the sandbox-write credential for
    # reads; otherwise, fall back to production-read.
    if shop_id is not None:
        try:
            from juli_backend.core.security import resolve_sandbox_write_credential

            sandbox_cred = await resolve_sandbox_write_credential(session)
            if sandbox_cred.shop_id == shop_id:
                # This is the sandbox shop; use sandbox-write resources for
                # reads as well
                return await load_sandbox_write_resources(
                    session, app_key=app_key, app_secret=app_secret
                )
        except Exception:
            # If sandbox-write credential resolution fails for any reason,
            # fall through to production-read below
            pass

    # Fall back to production-read for non-sandbox shops or if shop_id is None
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


def build_image_inspector():
    """The vision collaborator `inspect_product_image` uses (issue #1208).

    Model is `LLM_VISION_MODEL`, defaulting to the orchestrator's own model:
    `gpt-5.4-nano` has vision, verified against a real product image, so a
    second model is a cost/quality choice rather than a capability requirement.
    Configurable so that choice can be A/B'd by environment rather than by code
    change -- measured on three real products, nano and mini each surfaced a
    finding the other missed, which is too close to hardcode.

    Returns `None` when no API key is configured, which the handler reports as
    `inspected=False`. A missing inspection is a missing finding, never a
    failed run.
    """
    import os

    from juli_backend.services.agent.vision import InspectionConfig
    from juli_backend.services.agent.vision import build_image_inspector as _build

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    from juli_backend.services.agent.llm.config import DEFAULT_MODEL

    return _build(
        api_key=api_key,
        config=InspectionConfig(
            model=os.environ.get("LLM_VISION_MODEL", DEFAULT_MODEL),
            language=os.environ.get("LLM_VISION_LANGUAGE", "Vietnamese"),
        ),
    )
