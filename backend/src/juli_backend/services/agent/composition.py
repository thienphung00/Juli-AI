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

- `build_read_resources` builds `ProductionReadClientFactory().create_resources(...)`
  from **the run's shop's own** read credential
  (`resolve_read_credential_for_shop`, re-exported at `core.security`'s
  depth-2 facade) and that credential's merchant authorization id (P61-A,
  D71.1 -- it used to resolve the singleton production merchant for every
  non-sandbox shop, so every shop read Fujiwa's catalogue).
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
  A missing credential *row* fails closed via `NotFound`
  (`NoReadCredentialForShop` for the shop's read credential,
  `resolve_sandbox_write_credential`'s for the SANDBOX_VN write merchant).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.config import require_env
from juli_backend.core.security import (
    SandboxCredentialRefused,
    resolve_read_credential_for_shop,
    resolve_sandbox_write_credential,
)
from juli_backend.database.exceptions import NotFound
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.integrations.tiktok import (
    ClientFactoryConfig,
    ProductionReadClientFactory,
    ProductionReadResources,
    ProductionWriteResources,
    SandboxWriteResources,
    is_read_capability,
)
from juli_backend.models.models import WRITE_MODE_LIVE, WRITE_MODE_SIMULATED, TikTokCredential
from juli_backend.services.agent.llm import LLMService, resolve_llm_config
from juli_backend.services.agent.llm.openai_adapter import OpenAIResponsesAdapter
from juli_backend.services.agent.tools import ToolClassification, ToolRegistry
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools
from juli_backend.services.agent.tools.terminal import register_terminal_tools
from juli_backend.services.execution.sandbox_guard import load_sandbox_write_resources

logger = logging.getLogger(__name__)

# Public alias for callers in packages that may not import `integrations`
# directly (the `workers` package has no allowed edge to `integrations` at
# any depth — see `workers/tasks/agent_workflow.py`'s module docstring).
# `services` -> `integrations` is an allowed edge, so the union lives here.
AgentReadResources = ProductionReadResources | SandboxWriteResources
#: Fast track P61-B: a write goes to the sandbox merchant or -- only after every
#: ADR-085 gate passed for that shop and mutation -- to the shop's own listing.
AgentWriteResources = SandboxWriteResources | ProductionWriteResources


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
    # ADR-088: terminal tools are offered alongside the playbook's own, so the
    # model always has a legitimate way to end a run it has nothing to propose
    # for -- which is what makes the forced retry's tool_choice="required" safe.
    # `_tool_definitions` resolves `TerminationPolicy.terminal_tools` against
    # THIS registry, so omitting them here raises UnknownToolError at runtime
    # on the first run that reaches the retry. It did: run ffc8fd40 crashed with
    # `Unknown tool: 'conclude_without_changes'` and was recorded worker_lost.
    register_terminal_tools(registry)
    # Fast track P14-E: the content run's read-only tools (`content` domain).
    from juli_backend.services.content_cards.tools import register_content_read_tools

    register_content_read_tools(registry)
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


class AgentReadShopRequired(ValueError):
    """An agent read was asked for without naming the shop (P61-A, D71.1).

    Before P61-A a missing ``shop_id`` silently fell back to the configured
    production merchant, so the run read that merchant's catalogue. There is
    no "default shop" for a read: the caller must say whose data it wants.
    """


class AgentReadCredentialMismatch(RuntimeError):
    """The resolved read credential is not a usable read credential owned by
    the shop the run is for (P61-A). Never expected -- the resolver only
    returns the shop's own read rows -- so it is an invariant breach, raised
    before any client is built.
    """


def assert_agent_read_credential_for(credential: TikTokCredential, shop_id: uuid.UUID) -> None:
    """Refuse a credential that is not a read credential owned by ``shop_id``
    and carrying its own merchant id (mirrors
    `services/shop_diagnosis_daily/job.py::assert_read_credential_for`)."""
    if credential.shop_id != shop_id:
        raise AgentReadCredentialMismatch(
            f"agent read for shop {shop_id} resolved a credential owned by {credential.shop_id}"
        )
    capability = credential.capability
    if capability is None or not is_read_capability(capability):
        raise AgentReadCredentialMismatch(
            f"agent read for shop {shop_id} needs a read-capable credential; "
            f"got capability {capability!r}"
        )
    if not credential.merchant_authorization_id:
        raise AgentReadCredentialMismatch(
            f"agent read for shop {shop_id}: its read credential carries no merchant id"
        )


async def _is_sandbox_shop(session: AsyncSession, shop_id: uuid.UUID) -> bool:
    """Whether ``shop_id`` owns the sandbox-write credential (issue #1302)."""
    try:
        sandbox_cred = await resolve_sandbox_write_credential(session)
    except (NotFound, SandboxCredentialRefused):
        # No sandbox credential provisioned (or one refused as ambiguous with a production
        # credential, P61-G): this shop is not the sandbox shop;
        # it goes down the per-shop read path, which fails closed on its own.
        # Only NotFound (P61-B): a database or refresh error is not "no sandbox
        # credential" and must raise, not be logged as a fallback.
        logger.warning(
            "agent_read_resources_sandbox_fallback",
            extra={"shop_id": str(shop_id), "reason": "sandbox_resolution_failed"},
            exc_info=True,
        )
        return False
    return sandbox_cred.shop_id == shop_id


async def build_read_resources(
    session: AsyncSession, shop_id: uuid.UUID
) -> ProductionReadResources | SandboxWriteResources:
    """The real ADR-069 guarded read resources **for this shop** (issue #1173
    rework, amended by #1302 and P61-A / D71.1).

    - The sandbox shop (the shop the sandbox-write credential belongs to)
      reads through the sandbox-write resources, as before (#1302).
    - Every other shop reads through **its own** read credential
      (`resolve_read_credential_for_shop`: PRODUCTION_READ or SELLER_CONNECT
      owned by that shop) with **that credential's** merchant authorization
      id and shop cipher. There is no fallback to the configured production
      merchant: before P61-A every non-sandbox shop read that merchant's
      catalogue.

    Fails closed, in order: `_tiktok_app_credentials()` (`require_env`);
    `AgentReadShopRequired` when ``shop_id`` is ``None``;
    `NoReadCredentialForShop` (a `NotFound`) when the shop has no usable read
    credential; `AgentReadCredentialMismatch` if the resolved row is not the
    shop's own read credential.
    """
    app_key, app_secret = _tiktok_app_credentials()
    if shop_id is None:
        raise AgentReadShopRequired(
            "build_read_resources needs the run's shop_id; there is no default shop for a read"
        )

    if await _is_sandbox_shop(session, shop_id):
        return await load_sandbox_write_resources(session, app_key=app_key, app_secret=app_secret)

    # The credential table is RLS-scoped by shop (`tiktok_credentials_select_
    # public`); the read and any lazy refresh run under this shop's scope.
    async with with_shop_scope(session, shop_id):
        credential = await resolve_read_credential_for_shop(session, shop_id)
        assert_agent_read_credential_for(credential, shop_id)
        config = ClientFactoryConfig(
            app_key=app_key,
            app_secret=app_secret,
            access_token=credential.access_token,
            merchant_auth_id=str(credential.merchant_authorization_id),
            shop_cipher=credential.shop_cipher,
            credential_capability=credential.capability,
        )
    return ProductionReadClientFactory().create_resources(config)


async def build_write_resources(
    session: AsyncSession,
    shop_id: uuid.UUID | None = None,
    capability: Mapping[str, Any] | None = None,
) -> AgentWriteResources:
    """The real ADR-069 guarded write resources (issue #1173 rework; per shop
    since fast track P61-B, D71.2).

    ``capability`` is what `services/execution/production_write_resolver.py::
    resolve_write_capability` answered for this shop and mutation:

    - its production marker (every ADR-085 gate passed, the authorization was
      consumed and the allowed attempt audited) -> the shop's OWN write
      resources (`production_write.load_production_write_resources`: the
      shop's own credential, re-checked against ``shop_id``, behind
      `ProductionWriteGuard`). ``shop_id`` is required and must be the shop the
      marker was issued for;
    - anything else -- including no capability at all, which is every caller
      that does not resolve one (the agent run, `run_changes/live.py`) -> the
      SANDBOX_VN write resources exactly as before:
      `sandbox_guard.load_sandbox_write_resources`, whose credential must carry
      the `sandbox_write` capability (no merchant id is configured, P61-G).

    Fails closed the same two ways as `build_read_resources` above.
    """
    from juli_backend.services.execution.production_write import (
        is_production_capability,
        load_production_write_resources,
    )

    app_key, app_secret = _tiktok_app_credentials()
    if capability is not None and is_production_capability(capability):
        if shop_id is None:
            raise ValueError("A production write capability needs the shop it was issued for")
        return await load_production_write_resources(
            session,
            shop_id=shop_id,
            capability=capability,
            app_key=app_key,
            app_secret=app_secret,
        )
    return await load_sandbox_write_resources(session, app_key=app_key, app_secret=app_secret)


def write_mode_of(resources: object) -> str:
    """Where writes through ``resources`` land (fast track P61-B): ``live`` only
    for a shop's own production write resources; everything else -- the sandbox
    merchant, a test double -- is ``simulated``, so nothing is ever presented
    as a change on the seller's shop unless it went through the production path."""
    if isinstance(resources, ProductionWriteResources):
        return WRITE_MODE_LIVE
    return WRITE_MODE_SIMULATED


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
