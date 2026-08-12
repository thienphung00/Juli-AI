"""Product READ agent-tool capabilities — issue #981 (W1-A, ADR-069 decision 1).

The first domain-grouped handler module referenced by `registry.py`'s
docstring. Registers the three READ capabilities for Optimize Product against
a `ToolRegistry` (from `registry.py`, #980 — untouched here) and implements
their handlers:

- `get_product_information` wraps `products.get_details`.
- `get_seo_keywords` bundles `get_seo_words` + `get_suggestions` — the only
  permitted bundle (ADR-069 decision 1: no decision point sits between the
  two calls) — and returns one combined result.
- `check_product_status` wraps `products.get_details`'s status field as an
  in-run snapshot; the authoritative confirmation of a status change is the
  product-status webhook arriving later via `WorkflowWebhookSignal` — this
  tool never blocks a run on TikTok re-review (ADR-069 decision 1, step 6.5).

All three are READ / AUTO (ADR-068 decision 4).

**Context-bound identity (ADR-070 decision 1).** None of the three input
models declares an identifier field — the LLM never sees nor supplies a raw
vendor product id. Handlers instead take a `ProductToolContext` carrying the
bound `product_id`, injected by the tool executor from the approved run
context. `ProductToolContext` is a slice-local stand-in for the general
"run context" / "run state" object described in ADR-070 decision 1 and
ADR-073 decision 1 — no concrete `RunContext` type exists anywhere in the
codebase yet (the executor loop that would construct and pass one,
`services/agent/runner.py`, is not built). When that lands, the executor
is expected to construct a `ProductToolContext` (or its generalized
successor) from the authoritative run state and call these handlers with it;
nothing here should need to change.

**Marketplace access (ADR-068 decision 3, ADR-069 decision 3).** Handlers
receive an already-built `ProductionReadResources` — the guarded-factory
output — and only ever call `resources.products.*`. This module never
imports `TikTokClient`, `GuardedTikTokClient`, or the factory classes that
construct a transport (`test_agent_tools_product_read.py
::TestNoDirectClientConstruction` enforces this via an AST check).

**Sanitization is out of scope here (ADR-070, phase P5 / #990-995).** Output
models declare business-semantic shapes only; no caps, truncation, source-role
tagging, or banned-pattern guard is implemented in this slice.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from juli_backend.integrations.tiktok import ProductionReadResources
from juli_backend.services.agent.tools.registry import (
    ToolClassification,
    ToolPolicy,
    ToolRegistry,
    ToolSpec,
)


@dataclass(frozen=True)
class ProductToolContext:
    """The bound product identity for a single Optimize Product tool call.

    Injected by the tool executor from the approved run context (ADR-070
    decision 1) — never constructed from model input. See module docstring
    for why this is a slice-local placeholder rather than an import of a
    shared `RunContext` type.

    **Extended for WRITE capabilities (#982, ADR-070 decision 1's reserved
    per-step extension).** `product_id` stays the only field READ handlers
    use. The three fields below exist solely so WRITE handlers
    (`product_write.py`) never take a raw vendor SKU ID, a raw vendor asset
    URI, or raw image bytes from the LLM — those values live here,
    server-side, instead:

    - `sku_refs` — a closed per-run map from an agent-supplied opaque
      `sku_ref` (e.g. `"S1"`) to the real vendor SKU id. Populating this map
      from real run state is the not-yet-built run executor's job (ADR-073 /
      W3-A), exactly as `product_id` itself isn't populated by anything in
      this repo yet (see above) — tests construct it directly.
    - `staged_image_uri` — the vendor asset URI produced by a prior
      `upload_product_image` call, threaded forward so
      `update_product_listing` can attach it without ever exposing the URI
      to the model (ADR-070 decision 2: "images surface as `{count,
      dimensions}` with server-held references").
    - `pending_image_bytes` — the seller-supplied raw image bytes
      `upload_product_image` screens and uploads. Never LLM-supplied: the
      model cannot emit image content as output tokens (ADR-070 decision 1).

    All three default empty/`None` so #981's `ProductToolContext(product_id=...)`
    construction is unaffected.
    """

    product_id: str
    sku_refs: Mapping[str, str] = field(default_factory=dict)
    staged_image_uri: str | None = None
    pending_image_bytes: bytes | None = None


# --- get_product_information -------------------------------------------------


class GetProductInformationInput(BaseModel):
    """No fields. The bound product identity comes from `ProductToolContext`,
    never from model input (ADR-070 decision 1)."""


class GetProductInformationOutput(BaseModel):
    title: str | None = None
    status: str | None = None
    create_time: int | None = None
    update_time: int | None = None


def handle_get_product_information(
    resources: ProductionReadResources,
    context: ProductToolContext,
    params: GetProductInformationInput,
) -> GetProductInformationOutput:
    del params  # No fields: nothing to consume.
    raw = resources.products.get_details(context.product_id)
    return GetProductInformationOutput(
        title=raw.get("title"),
        status=raw.get("status"),
        create_time=raw.get("create_time"),
        update_time=raw.get("update_time"),
    )


GET_PRODUCT_INFORMATION_SPEC = ToolSpec(
    name="get_product_information",
    description="Get the current title and listing status for the bound product.",
    input_model=GetProductInformationInput,
    output_model=GetProductInformationOutput,
    classification=ToolClassification.READ,
    policy=ToolPolicy.AUTO,
    timeout_seconds=10,
)


# --- get_seo_keywords ---------------------------------------------------------


class GetSeoKeywordsInput(BaseModel):
    """No fields. The bound product identity comes from `ProductToolContext`,
    never from model input (ADR-070 decision 1)."""


class GetSeoKeywordsOutput(BaseModel):
    seo_words: list[str] = Field(default_factory=list)
    suggested_titles: list[str] = Field(default_factory=list)
    suggested_descriptions: list[str] = Field(default_factory=list)


def _extract_seo_words(raw: dict[str, Any], *, product_id: str) -> list[str]:
    for product in raw.get("products") or []:
        if str(product.get("id")) != product_id:
            continue
        words = product.get("seo_words") or []
        return [word if isinstance(word, str) else str(word.get("word") or word) for word in words]
    return []


def _extract_suggestion_texts(raw: dict[str, Any], *, product_id: str, field: str) -> list[str]:
    for product in raw.get("products") or []:
        if str(product.get("id")) != product_id:
            continue
        for suggestion in product.get("suggestions") or []:
            if suggestion.get("field") != field:
                continue
            texts: list[str] = []
            for item in suggestion.get("items") or []:
                if isinstance(item, dict):
                    text = item.get("text") or item.get("value") or item.get("name")
                else:
                    text = item
                if text:
                    texts.append(str(text))
            return texts
    return []


def handle_get_seo_keywords(
    resources: ProductionReadResources,
    context: ProductToolContext,
    params: GetSeoKeywordsInput,
) -> GetSeoKeywordsOutput:
    del params  # No fields: nothing to consume.
    seo_words_raw = resources.products.get_seo_words(product_ids=[context.product_id])
    suggestions_raw = resources.products.get_suggestions(product_ids=[context.product_id])
    return GetSeoKeywordsOutput(
        seo_words=_extract_seo_words(seo_words_raw, product_id=context.product_id),
        suggested_titles=_extract_suggestion_texts(
            suggestions_raw, product_id=context.product_id, field="TITLE"
        ),
        suggested_descriptions=_extract_suggestion_texts(
            suggestions_raw, product_id=context.product_id, field="DESCRIPTION"
        ),
    )


GET_SEO_KEYWORDS_SPEC = ToolSpec(
    name="get_seo_keywords",
    description=(
        "Get SEO keyword suggestions and title/description suggestions for the "
        "bound product, combined into one result."
    ),
    input_model=GetSeoKeywordsInput,
    output_model=GetSeoKeywordsOutput,
    classification=ToolClassification.READ,
    policy=ToolPolicy.AUTO,
    timeout_seconds=15,
)


# --- check_product_status -----------------------------------------------------


class CheckProductStatusInput(BaseModel):
    """No fields. The bound product identity comes from `ProductToolContext`,
    never from model input (ADR-070 decision 1)."""


class CheckProductStatusOutput(BaseModel):
    status: str | None = None


def handle_check_product_status(
    resources: ProductionReadResources,
    context: ProductToolContext,
    params: CheckProductStatusInput,
) -> CheckProductStatusOutput:
    del params  # No fields: nothing to consume.
    raw = resources.products.get_details(context.product_id)
    return CheckProductStatusOutput(status=raw.get("status"))


CHECK_PRODUCT_STATUS_SPEC = ToolSpec(
    name="check_product_status",
    description=(
        "Get an in-run snapshot of the bound product's current status. Not the "
        "authoritative confirmation of a status change — that arrives later via "
        "the product-status webhook."
    ),
    input_model=CheckProductStatusInput,
    output_model=CheckProductStatusOutput,
    classification=ToolClassification.READ,
    policy=ToolPolicy.AUTO,
    timeout_seconds=10,
)


# --- registration + handler lookup --------------------------------------------

PRODUCT_READ_TOOL_HANDLERS: dict[
    str, Callable[[ProductionReadResources, ProductToolContext, Any], BaseModel]
] = {
    GET_PRODUCT_INFORMATION_SPEC.name: handle_get_product_information,
    GET_SEO_KEYWORDS_SPEC.name: handle_get_seo_keywords,
    CHECK_PRODUCT_STATUS_SPEC.name: handle_check_product_status,
}


def register_product_read_tools(registry: ToolRegistry) -> None:
    """Register the three Optimize Product READ capabilities."""
    registry.register(GET_PRODUCT_INFORMATION_SPEC)
    registry.register(GET_SEO_KEYWORDS_SPEC)
    registry.register(CHECK_PRODUCT_STATUS_SPEC)
