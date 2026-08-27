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

**Sanitization is wired in here (ADR-070, phase P5 / #990-995, integrated
#996 W1 close).** Every field a handler in this module returns is shaped
through `services/agent/sanitize`: vendor-sourced free text (title,
description, SEO words/suggestions) is wrapped in a `VendorText` provenance
envelope (decision 3) and cut with `cap_text`/`cap_list` (decision 2);
timestamps are absolute ISO-8601 UTC via `iso_utc_timestamp` (decision 4);
SKU prices are `Money` (amount + currency, decision 4); images collapse to
`{count, dimensions}` via `sanitize_images` (decision 2). No raw vendor
identifier (product id, SKU id, warehouse id, image URI, request id) is read
by any handler in this module (decision 1) — enforced by
`test_agent_tools_product_read.py::TestOutputModelNeverCarriesRawVendorId`.
The inbound fail-closed banned-pattern chokepoint
(`guard_inbound_tool_result`, decision 6(a)) is **not** called inside these
handlers — it is a boundary seam applied once, by whatever dispatches a tool
call against this handler (a test-only dispatcher for this wave;
`WorkflowRunner` in W3-A), the same way it would bracket any tool's result
regardless of how much shaping that tool's own handler already did.
`check_product_status`'s single `status` field is a plain machine value
(not free text, not a timestamp, not a list) and needs no shaping beyond
that boundary guard.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from juli_backend.integrations.tiktok import (
    ProductionReadResources,
    SandboxWriteResources,
)
from juli_backend.services.agent.sanitize import (
    Money,
    VendorText,
    cap_list,
    cap_text,
    iso_utc_timestamp,
    sanitize_images,
    to_json_safe,
)
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
    # `product_detail` -- the full product information fetched by a prior
    # `get_product_information` call, threaded forward so
    # `update_product_listing` can derive required fields (category_id,
    # skus, package_weight) from the product's current values (ADR-070 decision 1's
    # reserved per-step extension, issue #1389). Never LLM-supplied: the
    # model cannot fetch product details, only the run executor can.
    product_detail: Mapping[str, Any] | None = None
    # `image_inspector` -- the vision collaborator `inspect_product_image` uses
    # (#1208). Injected, not imported, so this READ handler carries no LLM
    # dependency and tests supply a deterministic double. `None` means "no
    # inspector configured", which the handler reports as `inspected=False`
    # rather than raising.
    image_inspector: Any | None = None


# --- sanitize helpers, shared by the READ handlers below (ADR-070) -----------


def _vendor_text_field(value: str | None) -> dict[str, Any] | None:
    """Cap + provenance-wrap one vendor-sourced free-text field.

    `None` (the field absent on the raw payload) passes through as `None` —
    `cap_text` requires a string, and a genuinely absent field is not the
    same thing as an empty one. Combines `cap_text` (decision 2) with
    `VendorText`/`to_json_safe` (decision 3) exactly as the golden-file gate
    (#995) established: capping never re-tags provenance, and provenance
    never caps.
    """
    if value is None:
        return None
    capped = cap_text(value)
    payload: dict[str, Any] = to_json_safe(VendorText(text=capped.text))
    if capped.truncated:
        payload["truncated"] = True
        payload["omitted_count"] = capped.omitted_count
    return payload


def _vendor_text_list(items: list[str]) -> dict[str, Any]:
    """Provenance-wrap each string in a vendor-sourced list, then cap the list.

    Used for SEO words and title/description suggestions — each entry is its
    own piece of vendor free text (decision 3); the list itself is capped to
    `LIST_ITEM_CAP` in the caller's own order (decision 2).
    """
    payloads = [to_json_safe(VendorText(text=item)) for item in items]
    return cap_list(payloads).to_dict()


def _iso_from_epoch(value: int | None) -> str | None:
    """Absolute ISO-8601 UTC timestamp from a vendor epoch-seconds int, or
    `None` when the raw payload carries no value for this field (decision 4).
    """
    if value is None:
        return None
    return iso_utc_timestamp(datetime.fromtimestamp(value, tz=UTC))


def _money_amount(raw: str) -> int | float:
    """Vendor prices arrive as decimal strings (`"72000"`); `Money.amount`
    must be a bare number (decision 4). VND has no minor subunit, so a
    whole-VND price is emitted as `int`; anything with a fractional
    remainder as `float`.
    """
    value = float(raw)
    as_int = int(value)
    return as_int if as_int == value else value


def _sku_price(sku: Mapping[str, Any]) -> dict[str, Any]:
    price = sku.get("price") or {}
    raw_amount = price.get("tax_exclusive_price")
    amount = _money_amount(raw_amount) if raw_amount is not None else 0
    currency = price.get("currency") or "VND"
    return Money(amount=amount, currency=currency).to_dict()


# --- get_product_information -------------------------------------------------


class GetProductInformationInput(BaseModel):
    # Rationale for the empty schema (bound product identity, never model
    # input) is documented in this module's docstring, "Context-bound
    # identity" section — kept out of the model-facing docstring below so it
    # never ships into the LLM's context (issue #1014).
    """No parameters — reads the product already selected for this run."""


class GetProductInformationOutput(BaseModel):
    """ADR-070-shaped: `title`/`description` are provenance envelopes
    (`{"source": "vendor", "text": ..., ["truncated", "omitted_count"]}`);
    `create_time`/`update_time` are absolute ISO-8601 UTC strings, or `None`
    when the raw payload carries no value; `sku_prices`/`images` are capped
    envelopes (`sku_prices` from `cap_list` over `Money` values, `images`
    from `sanitize_images`); `sku_count`/`total_inventory_quantity` are
    computed from the *full* SKU list before capping, mirroring the "count
    is always the true total" convention `CappedImages` already uses."""

    title: dict[str, Any] | None = None
    description: dict[str, Any] | None = None
    status: str | None = None
    create_time: str | None = None
    update_time: str | None = None
    sku_count: int = 0
    total_inventory_quantity: int = 0
    sku_prices: dict[str, Any] = Field(default_factory=dict)
    images: dict[str, Any] = Field(default_factory=dict)


def handle_get_product_information(
    resources: ProductionReadResources | SandboxWriteResources,
    context: ProductToolContext,
    params: GetProductInformationInput,
) -> GetProductInformationOutput:
    del params  # No fields: nothing to consume.
    raw = resources.products.get_details(context.product_id)

    skus = raw.get("skus") or []
    total_inventory_quantity = 0
    for sku in skus:
        for inventory_entry in sku.get("inventory") or []:
            total_inventory_quantity += int(inventory_entry.get("quantity") or 0)
    capped_sku_prices = cap_list([_sku_price(sku) for sku in skus])
    capped_images = sanitize_images(raw.get("main_images") or [])

    return GetProductInformationOutput(
        title=_vendor_text_field(raw.get("title")),
        description=_vendor_text_field(raw.get("description")),
        status=raw.get("status"),
        create_time=_iso_from_epoch(raw.get("create_time")),
        update_time=_iso_from_epoch(raw.get("update_time")),
        sku_count=len(skus),
        total_inventory_quantity=total_inventory_quantity,
        sku_prices=capped_sku_prices.to_dict(),
        images=capped_images.to_dict(),
    )


GET_PRODUCT_INFORMATION_SPEC = ToolSpec(
    name="get_product_information",
    description=(
        "Read the bound product's listing: title, description, status, "
        "last-updated time, SKU count and prices, total inventory, and image sizes."
    ),
    input_model=GetProductInformationInput,
    output_model=GetProductInformationOutput,
    classification=ToolClassification.READ,
    policy=ToolPolicy.AUTO,
    timeout_seconds=10,
)


# --- get_seo_keywords ---------------------------------------------------------


class GetSeoKeywordsInput(BaseModel):
    # Rationale: see module docstring, "Context-bound identity" section.
    """No parameters — reads SEO keyword data for the product already
    selected for this run."""


class GetSeoKeywordsOutput(BaseModel):
    """ADR-070-shaped: each field is a capped, provenance-wrapped envelope
    (`{"items": [{"source": "vendor", "text": ...}, ...], ["truncated",
    "omitted_count"]}`) — every SEO word / suggested title / suggested
    description is vendor-sourced free text (decision 3), and the list
    itself is capped to `LIST_ITEM_CAP` in the vendor's own order
    (decision 2)."""

    seo_words: dict[str, Any] = Field(default_factory=dict)
    suggested_titles: dict[str, Any] = Field(default_factory=dict)
    suggested_descriptions: dict[str, Any] = Field(default_factory=dict)


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
    resources: ProductionReadResources | SandboxWriteResources,
    context: ProductToolContext,
    params: GetSeoKeywordsInput,
) -> GetSeoKeywordsOutput:
    del params  # No fields: nothing to consume.
    seo_words_raw = resources.products.get_seo_words(product_ids=[context.product_id])
    suggestions_raw = resources.products.get_suggestions(product_ids=[context.product_id])
    return GetSeoKeywordsOutput(
        seo_words=_vendor_text_list(
            _extract_seo_words(seo_words_raw, product_id=context.product_id)
        ),
        suggested_titles=_vendor_text_list(
            _extract_suggestion_texts(suggestions_raw, product_id=context.product_id, field="TITLE")
        ),
        suggested_descriptions=_vendor_text_list(
            _extract_suggestion_texts(
                suggestions_raw, product_id=context.product_id, field="DESCRIPTION"
            )
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
    # Rationale: see module docstring, "Context-bound identity" section.
    """No parameters — checks the status of the product already selected
    for this run."""


class CheckProductStatusOutput(BaseModel):
    status: str | None = None


def handle_check_product_status(
    resources: ProductionReadResources | SandboxWriteResources,
    context: ProductToolContext,
    params: CheckProductStatusInput,
) -> CheckProductStatusOutput:
    del params  # No fields: nothing to consume.
    raw = resources.products.get_details(context.product_id)
    return CheckProductStatusOutput(status=raw.get("status"))


CHECK_PRODUCT_STATUS_SPEC = ToolSpec(
    name="check_product_status",
    description=(
        "Get an in-run snapshot of the bound product's current status. This snapshot is "
        "not authoritative — the confirmed status arrives later, outside this tool call."
    ),
    input_model=CheckProductStatusInput,
    output_model=CheckProductStatusOutput,
    classification=ToolClassification.READ,
    policy=ToolPolicy.AUTO,
    timeout_seconds=10,
)


# --- inspect_product_image ----------------------------------------------------


class InspectProductImageInput(BaseModel):
    # Rationale: see module docstring, "Context-bound identity" section. No
    # image field exists because the model must never receive or emit an image
    # reference (ADR-070 decision 2) -- the photo is resolved server-side from
    # the bound product.
    """No parameters -- inspects the main photo of the product already
    selected for this run."""


class InspectProductImageFinding(BaseModel):
    aspect: str = ""
    observed: str = ""
    conflicts_with: str | None = None
    severity: str = "low"


class InspectProductImageEdit(BaseModel):
    intent: str = ""
    subject: str = ""
    instruction: str = ""
    priority: str = "low"


class InspectProductImageOutput(BaseModel):
    """Whether the product photo matches the listing copy.

    Deliberately an *edit intent* rather than prose (issue #1208): when image
    generation lands, `recommended_edits` becomes its instruction payload
    unchanged, and `verdict` becomes the inspect -> edit -> re-inspect loop's
    termination condition. No vendor asset URI appears here -- the image URL is
    held server-side and never surfaces to the model.
    """

    verdict: str = "partial"
    confidence: str = "low"
    inspected: bool = True
    findings: list[InspectProductImageFinding] = Field(default_factory=list)
    recommended_edits: list[InspectProductImageEdit] = Field(default_factory=list)


def handle_inspect_product_image(
    resources: ProductionReadResources | SandboxWriteResources,
    context: ProductToolContext,
    params: InspectProductImageInput,
) -> InspectProductImageOutput:
    """Fetch the bound product, hand its hero photo + copy to the inspector.

    Re-reads the product rather than reusing an earlier tool result: the CDN
    URL is pre-signed and short-lived, so it must never be cached or threaded
    forward. `inspected=False` (rather than an exception) when there is no
    image or no inspector configured -- a missing inspection is a missing
    finding, not a reason to end a healthy run. That distinction is what #1208
    was about: `upload_product_image` raised into the task and the run was
    mislabelled `worker_lost`.
    """
    del params  # No fields: nothing to consume.
    if context.image_inspector is None:
        return InspectProductImageOutput(inspected=False)

    raw = resources.products.get_details(context.product_id)
    images = raw.get("main_images") or []
    urls = (images[0].get("urls") if images else None) or []
    if not urls:
        return InspectProductImageOutput(inspected=False)

    result = context.image_inspector(
        image_url=urls[0],
        title=str(raw.get("title") or ""),
        description=str(raw.get("description") or ""),
    )
    return InspectProductImageOutput(
        verdict=result.get("verdict", "partial"),
        confidence=result.get("confidence", "low"),
        inspected=True,
        findings=[InspectProductImageFinding(**f) for f in result.get("findings", [])],
        recommended_edits=[
            InspectProductImageEdit(**e) for e in result.get("recommended_edits", [])
        ],
    )


INSPECT_PRODUCT_IMAGE_SPEC = ToolSpec(
    name="inspect_product_image",
    description=(
        "Check whether the product's main photo matches its title and description. "
        "Returns findings and recommended image edits -- it does not change the photo. "
        "A photo dominated by promotional banners or price overlays is a finding even "
        "when the product shown is correct."
    ),
    input_model=InspectProductImageInput,
    output_model=InspectProductImageOutput,
    classification=ToolClassification.READ,
    policy=ToolPolicy.AUTO,
    # 30s, deliberately the same as the WRITE step it replaces, so the
    # documented worst-case wall-clock bound (test_agent_runner_termination.py's
    # TestWallClockOvershootBound) is unchanged. Measured vision calls returned
    # in ~5-10s against real product images, so this is ample headroom without
    # widening a safety bound as a side effect of a tool swap.
    timeout_seconds=30,
)


# --- registration + handler lookup --------------------------------------------

PRODUCT_READ_TOOL_HANDLERS: dict[
    str,
    Callable[[ProductionReadResources | SandboxWriteResources, ProductToolContext, Any], BaseModel],
] = {
    GET_PRODUCT_INFORMATION_SPEC.name: handle_get_product_information,
    GET_SEO_KEYWORDS_SPEC.name: handle_get_seo_keywords,
    CHECK_PRODUCT_STATUS_SPEC.name: handle_check_product_status,
    INSPECT_PRODUCT_IMAGE_SPEC.name: handle_inspect_product_image,
}


def register_product_read_tools(registry: ToolRegistry) -> None:
    """Register the three Optimize Product READ capabilities."""
    registry.register(GET_PRODUCT_INFORMATION_SPEC)
    registry.register(GET_SEO_KEYWORDS_SPEC)
    registry.register(CHECK_PRODUCT_STATUS_SPEC)
    registry.register(INSPECT_PRODUCT_IMAGE_SPEC)
