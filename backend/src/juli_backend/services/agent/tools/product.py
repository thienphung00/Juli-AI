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

import hashlib
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from juli_backend.integrations.tiktok import (
    ProductionReadResources,
    SandboxWriteResources,
    TikTokAPIError,
    TransportGuardError,
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
from juli_backend.services.agent.tools.diagnosis_labels import (
    diagnosis_label_vi,
    is_diagnosis_code,
)
from juli_backend.services.agent.tools.domains import PRODUCT_DOMAIN
from juli_backend.services.agent.tools.registry import (
    ToolClassification,
    ToolPolicy,
    ToolRegistry,
    ToolSpec,
)

logger = logging.getLogger(__name__)


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
    # `restore_main_image_uris` -- fast track P8-C: set only on a "Hoàn tác"
    # run whose original write changed the listing's photos. The image URIs
    # the listing had before Juli's write, server-held (never LLM-supplied),
    # which `update_product_listing` sends back as `main_images`.
    restore_main_image_uris: tuple[str, ...] | None = None
    # `on_image_staged` -- fast track P10-B: told the TikTok image URI an
    # `upload_product_image` call produced, so the executor can attach it in
    # this leg and the worker can keep it (server-side, never model-visible)
    # for the write that follows the seller's consent on the resume leg.
    on_image_staged: Callable[[str], None] | None = None


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
    # dictionary.md `run.option_rationale.get_product_information` (issue
    # #1904, W6-FIX) -- seller-facing, distinct from `description` above,
    # which the model reads and which stays unchanged.
    seller_rationale_vi="Xem thông tin hiện tại của sản phẩm này.",
    input_model=GetProductInformationInput,
    output_model=GetProductInformationOutput,
    classification=ToolClassification.READ,
    policy=ToolPolicy.AUTO,
    timeout_seconds=10,
    domain=PRODUCT_DOMAIN,
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
    # dictionary.md `run.option_rationale.get_seo_keywords` (issue #1904, W6-FIX).
    seller_rationale_vi="Tra cứu từ khoá SEO gợi ý cho sản phẩm này.",
    input_model=GetSeoKeywordsInput,
    output_model=GetSeoKeywordsOutput,
    classification=ToolClassification.READ,
    policy=ToolPolicy.AUTO,
    timeout_seconds=15,
    domain=PRODUCT_DOMAIN,
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
    # dictionary.md `run.option_rationale.check_product_status` (issue #1904, W6-FIX).
    seller_rationale_vi="Kiểm tra trạng thái hiện tại của sản phẩm này.",
    input_model=CheckProductStatusInput,
    output_model=CheckProductStatusOutput,
    classification=ToolClassification.READ,
    policy=ToolPolicy.AUTO,
    timeout_seconds=10,
    domain=PRODUCT_DOMAIN,
)


# --- get_product_diagnoses ----------------------------------------------------


class GetProductDiagnosesInput(BaseModel):
    # Rationale: see module docstring, "Context-bound identity" section.
    """No parameters — reads TikTok's listing diagnoses for the product
    already selected for this run."""


class GetProductDiagnosesOutput(BaseModel):
    """`codes` lists each diagnosis TikTok raised for the listing, as
    `{code, label_vi, field, how_to_solve}`: `code` is TikTok's machine code
    (validated as an upper-case token, anything else dropped), `label_vi` the
    short Vietnamese label, `field` the listing field TikTok attached it to
    (a plain machine value), `how_to_solve` TikTok's advice as a provenance
    envelope (vendor free text, decision 3) or `None`. `count` is the number
    of codes. An empty `codes` means TikTok flagged nothing."""

    codes: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    # True when TikTok could not be read (error / not authorised): `codes` is
    # empty because nothing was read, NOT because TikTok flagged nothing.
    unavailable: bool = False


def _diagnosis_entries(raw: dict[str, Any], *, product_id: str) -> list[dict[str, Any]]:
    """The `diagnoses` entries for this product from the endpoint payload."""
    entries: list[dict[str, Any]] = []
    for product in raw.get("products") or []:
        if not isinstance(product, dict) or str(product.get("id")) != product_id:
            continue
        entries.extend(d for d in product.get("diagnoses") or [] if isinstance(d, dict))
    return entries


def handle_get_product_diagnoses(
    resources: ProductionReadResources | SandboxWriteResources,
    context: ProductToolContext,
    params: GetProductDiagnosesInput,
) -> GetProductDiagnosesOutput:
    del params  # No fields: nothing to consume.
    try:
        raw = resources.products.get_diagnoses([context.product_id])
    except (TikTokAPIError, TransportGuardError) as exc:
        # Advisory first step: a shop whose diagnoses endpoint is unavailable
        # or unauthorised must still get a run. Vendor/guard errors only --
        # programming errors still propagate.
        logger.warning(
            "get_product_diagnoses_unavailable",
            extra={"exception_type": type(exc).__name__, "detail": str(exc)[:300]},
        )
        return GetProductDiagnosesOutput(unavailable=True)

    codes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in _diagnosis_entries(raw, product_id=context.product_id):
        field_name = entry.get("field")
        for result in entry.get("diagnosis_results") or []:
            if not isinstance(result, dict):
                continue
            code = result.get("code")
            if not is_diagnosis_code(code) or code in seen:
                continue
            seen.add(code)
            how_to_solve = result.get("how_to_solve")
            codes.append(
                {
                    "code": code,
                    "label_vi": diagnosis_label_vi(code),
                    "field": field_name if is_diagnosis_code(field_name) else None,
                    "how_to_solve": (
                        _vendor_text_field(how_to_solve) if isinstance(how_to_solve, str) else None
                    ),
                }
            )
    capped = cap_list(codes)
    return GetProductDiagnosesOutput(codes=list(capped.items), count=len(codes))


GET_PRODUCT_DIAGNOSES_SPEC = ToolSpec(
    name="get_product_diagnoses",
    description=(
        "Read the diagnosis codes TikTok has raised for the bound product's listing, "
        "each with a short Vietnamese label. An empty list means TikTok flagged no issue. "
        "Read this before the listing itself."
    ),
    seller_rationale_vi="Xem TikTok đã chỉ ra vấn đề nào ở sản phẩm này.",
    input_model=GetProductDiagnosesInput,
    output_model=GetProductDiagnosesOutput,
    classification=ToolClassification.READ,
    policy=ToolPolicy.AUTO,
    timeout_seconds=10,
    domain=PRODUCT_DOMAIN,
)


# --- find_product_promotions -------------------------------------------------
#
# Fast track P10-B (contract §5, D13): the read-only check behind "Tôi đã áp
# dụng". Juli never writes a promotion to TikTok; it only looks for the one the
# seller created on Seller Center. Two reads: Search Activities (one page per
# matching activity type) and Get Activity for each candidate, whose
# ``products[]`` says whether the bound product is in it.

#: ADR-106 promotion lever code -> TikTok ``activity_type`` values it covers.
PROMOTION_ACTIVITY_TYPES: Mapping[str, tuple[str, ...]] = {
    "product_discount": ("FIXED_PRICE", "DIRECT_DISCOUNT"),
    "flash_sale": ("FLASHSALE",),
    "shipping_discount": ("SHIPPING_DISCOUNT",),
    "buy_more_save_more": ("BUY_MORE_SAVE_MORE",),
}

#: Vietnamese names of the four promotion levers (the Seller Center names).
PROMOTION_TYPE_LABELS_VI: Mapping[str, str] = {
    "product_discount": "Giảm giá sản phẩm",
    "flash_sale": "Flash sale",
    "shipping_discount": "Giảm phí vận chuyển",
    "buy_more_save_more": "Mua nhiều giảm nhiều",
}

#: Activity statuses that cannot be the promotion the seller just applied.
_PROMOTION_SKIPPED_STATUSES = frozenset({"DRAFT", "DEACTIVATED", "NOT_EFFECTIVE", "EXPIRED"})
_PROMOTION_MAX_DETAILS = 20
_SHOP_UTC_OFFSET = timedelta(hours=7)


class FindProductPromotionsInput(BaseModel):
    """Which of the four Seller Center promotion types to look for on the
    product already selected for this run."""

    promotion_type: Literal[
        "product_discount", "flash_sale", "shipping_discount", "buy_more_save_more"
    ]


class FoundPromotion(BaseModel):
    """One promotion of the requested type that includes the bound product.

    ``ref`` is an opaque fingerprint (not TikTok's activity id) so a later
    check can tell a new promotion from one that already existed. Dates are the
    shop's local dates (UTC+7); ``end_date`` is ``None`` when open-ended.
    """

    ref: str
    type_label: str
    status: str
    begin_date: str | None = None
    end_date: str | None = None


class FindProductPromotionsOutput(BaseModel):
    promotion_type: str
    promotions: list[FoundPromotion] = Field(default_factory=list)
    # True when TikTok could not be read: an empty list then means "unknown".
    unavailable: bool = False


def _promotion_ref(activity_id: str) -> str:
    return hashlib.sha256(f"promotion:{activity_id}".encode()).hexdigest()[:16]


def _promotion_date(value: object) -> str | None:
    try:
        seconds = int(str(value))
    except ValueError:
        return None
    if seconds <= 0:
        return None
    seconds = seconds // 1000 if seconds > 10**11 else seconds
    return (datetime.fromtimestamp(seconds, tz=UTC) + _SHOP_UTC_OFFSET).date().isoformat()


def _unwrap(payload: object, key: str) -> Any:
    data = payload.get("data") if isinstance(payload, Mapping) else None
    source = data if isinstance(data, Mapping) else payload
    return source.get(key) if isinstance(source, Mapping) else None


def _activity_includes(detail: object, product_id: str) -> bool:
    products = _unwrap(detail, "products")
    if isinstance(products, list) and products:
        return any(
            isinstance(product, Mapping) and str(product.get("id")) == product_id
            for product in products
        )
    # A shop-wide activity (no product list) applies to every product.
    return str(_unwrap(detail, "product_level") or "").upper() == "SHOP"


def handle_find_product_promotions(
    resources: ProductionReadResources | SandboxWriteResources,
    context: ProductToolContext,
    params: FindProductPromotionsInput,
) -> FindProductPromotionsOutput:
    """Read-only: the promotions of ``params.promotion_type`` that include the product."""
    label = PROMOTION_TYPE_LABELS_VI[params.promotion_type]
    found: list[FoundPromotion] = []
    try:
        candidates: list[Mapping[str, Any]] = []
        for activity_type in PROMOTION_ACTIVITY_TYPES[params.promotion_type]:
            page = resources.promotion.search_activities(activity_type=activity_type, page_size=100)
            activities = _unwrap(page, "activities")
            for activity in activities if isinstance(activities, list) else []:
                if not isinstance(activity, Mapping) or not activity.get("id"):
                    continue
                if str(activity.get("status") or "").upper() in _PROMOTION_SKIPPED_STATUSES:
                    continue
                candidates.append(activity)
        for activity in candidates[:_PROMOTION_MAX_DETAILS]:
            activity_id = str(activity["id"])
            detail = resources.promotion.get_activity(activity_id)
            if not _activity_includes(detail, context.product_id):
                continue
            body = detail.get("data") if isinstance(detail, Mapping) else None
            body = body if isinstance(body, Mapping) else detail
            merged = {**activity, **(body if isinstance(body, Mapping) else {})}
            found.append(
                FoundPromotion(
                    ref=_promotion_ref(activity_id),
                    type_label=label,
                    status=str(merged.get("status") or ""),
                    begin_date=_promotion_date(merged.get("begin_time")),
                    end_date=_promotion_date(merged.get("end_time")),
                )
            )
    except (TikTokAPIError, TransportGuardError) as exc:
        logger.warning(
            "find_product_promotions_unavailable",
            extra={"exception_type": type(exc).__name__, "detail": str(exc)[:300]},
        )
        return FindProductPromotionsOutput(promotion_type=params.promotion_type, unavailable=True)
    return FindProductPromotionsOutput(promotion_type=params.promotion_type, promotions=found)


FIND_PRODUCT_PROMOTIONS_SPEC = ToolSpec(
    name="find_product_promotions",
    description=(
        "Look up, read-only, the promotions of one Seller Center type (product discount, "
        "flash sale, shipping discount, buy more save more) that include the bound product. "
        "Juli never creates or changes promotions; this only checks what the seller applied."
    ),
    seller_rationale_vi="Kiểm tra trên TikTok khuyến mãi bạn đã áp dụng cho sản phẩm này.",
    input_model=FindProductPromotionsInput,
    output_model=FindProductPromotionsOutput,
    classification=ToolClassification.READ,
    policy=ToolPolicy.AUTO,
    timeout_seconds=20,
    domain=PRODUCT_DOMAIN,
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
    # dictionary.md `run.option_rationale.inspect_product_image` (issue #1904, W6-FIX).
    seller_rationale_vi="Kiểm tra xem ảnh sản phẩm có khớp với nội dung mô tả không.",
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
    domain=PRODUCT_DOMAIN,
)


# --- registration + handler lookup --------------------------------------------

PRODUCT_READ_TOOL_HANDLERS: dict[
    str,
    Callable[[ProductionReadResources | SandboxWriteResources, ProductToolContext, Any], BaseModel],
] = {
    GET_PRODUCT_INFORMATION_SPEC.name: handle_get_product_information,
    GET_SEO_KEYWORDS_SPEC.name: handle_get_seo_keywords,
    CHECK_PRODUCT_STATUS_SPEC.name: handle_check_product_status,
    GET_PRODUCT_DIAGNOSES_SPEC.name: handle_get_product_diagnoses,
    INSPECT_PRODUCT_IMAGE_SPEC.name: handle_inspect_product_image,
    FIND_PRODUCT_PROMOTIONS_SPEC.name: handle_find_product_promotions,
}


def register_product_read_tools(registry: ToolRegistry) -> None:
    """Register the Optimize Product READ capabilities."""
    registry.register(GET_PRODUCT_INFORMATION_SPEC)
    registry.register(GET_SEO_KEYWORDS_SPEC)
    registry.register(CHECK_PRODUCT_STATUS_SPEC)
    registry.register(GET_PRODUCT_DIAGNOSES_SPEC)
    registry.register(INSPECT_PRODUCT_IMAGE_SPEC)
    registry.register(FIND_PRODUCT_PROMOTIONS_SPEC)
