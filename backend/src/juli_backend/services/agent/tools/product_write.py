"""Product WRITE agent-tool capabilities — issue #982 (W1-A, ADR-069 decision 1).

The sibling handler module to `product.py` (#981's READ capabilities, left
untouched, except `ProductToolContext`'s additive extension documented on the
class itself). Registers the three WRITE capabilities for Optimize Product
against a `ToolRegistry` (from `registry.py`, #980 — untouched here) and
implements their handlers:

- `upload_product_image` wraps a screened upload (ADR-055 item 20,
  `services/execution/file_screening.py` — reused, not reimplemented) of
  seller-supplied image bytes staged in run context. WRITE / **AUTO**:
  staging only. The upload itself is not yet attached to any listing — the
  listing changes only via `update_product_listing`, whose confirmation diff
  is what actually shows the new image to the seller (ADR-069 decision 1,
  playbook steps 4/4.5).
- `update_product_listing` wraps `products.edit` with agent-authored
  title/description and, when the run staged one, the image the run already
  uploaded. WRITE / **CONFIRM** (playbook step 5).
- `update_product_price` wraps `products.update_prices`. WRITE / **CONFIRM**,
  independently rejectable from the listing edit — a separate capability, not
  a bundled step, because a seller confirming new copy has not thereby
  confirmed a price change (playbook step 6).

**Context-bound identity AND raw-ID-free schemas (ADR-070 decision 1 —
governs over ADR-069's granularity table where the two could be read as
conflicting; ADR-070's text is "no raw vendor ID", not "no product ID").**
None of the three input models declares an identifier field, and none
declares a raw vendor ID or raw vendor asset URI of any kind:

- `upload_product_image` has **zero** LLM-supplied fields, exactly like
  #981's READ inputs — the image bytes it screens and uploads come from
  `context.pending_image_bytes` (seller-supplied, staged server-side), never
  from model output. A model cannot be asked to emit image bytes as output
  tokens.
- `update_product_listing` carries agent-authored `title`/`description` plus
  `attach_staged_image: bool` — never the raw asset URI a prior
  `upload_product_image` call produced. The URI lives in
  `context.staged_image_uri`, threaded forward by the (not-yet-built) run
  executor; the model only ever says "yes, attach it" or "no."
- `update_product_price` carries agent-authored `sku_ref` + price — a
  server-minted opaque token (ADR-070 decision 1's reserved per-step
  extension, e.g. `"S1"`), never the raw vendor SKU id. The handler resolves
  `sku_ref` against `context.sku_refs`, a closed per-run map; an unresolvable
  ref raises `UnresolvedSkuRefError` rather than silently passing the ref
  itself through as if it were a vendor id.

All three still take the bound product identity from `ProductToolContext`
(reused from `product.py` — this module does not invent a second context
type), never from model input.

**Marketplace access (ADR-068 decision 3, ADR-069 decision 3).** Handlers
receive an already-built `SandboxWriteResources` — the guarded-factory
output, imported only from the `juli_backend.integrations.tiktok` package
root — and only ever call `resources.products.*`. This module never imports
`TikTokClient`, `GuardedTikTokClient`, or the factory classes that construct
a transport (`test_agent_tools_product_write.py
::TestNoDirectClientConstruction` enforces this via an AST check).

**Scope boundary (ADR-069 decision 2 + its ADR-073 amendment is NOT this
slice).** CONFIRM here is a declared `ToolPolicy` value on the `ToolSpec`
only. No `ToolExecution` row, no idempotency ledger, no claim-then-execute,
no pause/resume mechanics, and no persistence beyond what `product.py`
already relies on are implemented here — that is W3-A / ADR-073. Handlers in
this module call the guarded resource and return a sanitized-shape result
synchronously, exactly like the READ handlers in `product.py`; the run
executor (not built yet) is what will pause a CONFIRM tool before invoking
its handler, and is also what will populate `ProductToolContext.sku_refs` /
`.staged_image_uri` / `.pending_image_bytes` from real run state between
calls — tests construct that context directly, exactly as #981's tests
construct `product_id` directly.

**Sanitization is out of scope here (ADR-070, phase P5 / #990-995).** Output
models declare business-semantic shapes only; no caps, truncation,
source-role tagging, or banned-pattern guard is implemented in this slice —
except the specific no-raw-ID/no-raw-URI shape ADR-070 decision 1 requires
structurally, which is this module's whole point.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from pydantic import BaseModel, Field

from juli_backend.integrations.tiktok import SandboxWriteResources
from juli_backend.services.agent.tools.product import ProductToolContext
from juli_backend.services.agent.tools.registry import (
    ToolClassification,
    ToolPolicy,
    ToolRegistry,
    ToolSpec,
)
from juli_backend.services.execution.file_screening import screen_and_reencode_image

# Vendor protocol constant from TikTok B-4 (Edit Product / Partial endpoint).
# Section reference: docs/integrations/tiktok_api/contract-collection.md § B-4
# Never hardcode this at call sites; always source it from this constant.
TIKTOK_PRODUCT_EDIT_CATEGORY_VERSION = "v2"


class UnresolvedAgentRefError(ValueError):
    """Raised when an agent-supplied opaque ref cannot be resolved against
    the run context's closed per-run map, or when a handler needs a
    server-staged value run context does not yet hold (ADR-070 decision 1's
    reserved extension). Never falls through to a passthrough or a guessed
    vendor value — the caller must fix the run state and retry."""


class UnresolvedSkuRefError(UnresolvedAgentRefError):
    """`update_product_price` was given a `sku_ref` absent from
    `context.sku_refs`."""


class UnresolvedStagedImageError(UnresolvedAgentRefError):
    """Either `upload_product_image` was called with no
    `context.pending_image_bytes` staged, or `update_product_listing` was
    called with `attach_staged_image=True` but no `context.staged_image_uri`
    staged."""


# --- upload_product_image -----------------------------------------------------


class UploadProductImageInput(BaseModel):
    # Rationale: see module docstring, "Context-bound identity AND
    # raw-ID-free schemas" section — no field exists because a model cannot
    # emit raw image bytes as output tokens.
    """No parameters — uploads the candidate listing image already staged
    for this run."""


class UploadProductImageOutput(BaseModel):
    """No raw vendor asset URI (ADR-070 decision 2: images surface with
    server-held references, not the reference itself). `staged` is the only
    signal the model needs to move on to `update_product_listing`."""

    staged: bool = True


def handle_upload_product_image(
    resources: SandboxWriteResources,
    context: ProductToolContext,
    params: UploadProductImageInput,
) -> UploadProductImageOutput:
    del params  # No fields: nothing to consume.
    if context.pending_image_bytes is None:
        raise UnresolvedStagedImageError(
            "upload_product_image called with no pending_image_bytes staged in run context"
        )
    screened_bytes, safe_filename = screen_and_reencode_image(context.pending_image_bytes)
    resources.products.upload_product_image(image_bytes=screened_bytes, filename=safe_filename)
    # The raw response (including its vendor asset URI) is intentionally
    # discarded here rather than returned: propagating it into the next
    # call's ProductToolContext.staged_image_uri is per-run server-side
    # state construction, the run executor's job (ADR-073 / W3-A) — the
    # model itself never sees the URI (ADR-070 decision 2).
    return UploadProductImageOutput(staged=True)


UPLOAD_PRODUCT_IMAGE_SPEC = ToolSpec(
    name="upload_product_image",
    description=(
        "Screen and upload the seller-supplied candidate listing image staged for this "
        "run. The image is not applied to the listing until update_product_listing is "
        "called with attach_staged_image=True."
    ),
    input_model=UploadProductImageInput,
    output_model=UploadProductImageOutput,
    classification=ToolClassification.WRITE,
    policy=ToolPolicy.AUTO,
    timeout_seconds=30,
)


# --- update_product_listing ----------------------------------------------------


class UpdateProductListingInput(BaseModel):
    # Rationale for the field shape (no identifier, no raw asset URI): see
    # module docstring, "Context-bound identity AND raw-ID-free schemas".
    """New title and/or description to apply to the listing of the product
    already selected for this run, and whether to attach the image already
    uploaded for this run."""

    title: str | None = None
    description: str | None = None
    attach_staged_image: bool = False


class UpdateProductListingOutput(BaseModel):
    title: str | None = None
    description: str | None = None
    image_attached: bool = False


def _extract_leaf_category_id(product_detail: Mapping[str, Any]) -> str:
    """Extract the leaf category ID from product_detail's category_chains.

    Per TikTok contract B-4, category_id is required for product edits and
    must be a leaf category. Fails closed if no leaf category is found.

    Args:
        product_detail: The full product details, expected to have a
            category_chains list of dicts with {id, is_leaf, ...}.

    Returns:
        The id of the first (and typically only) leaf category.

    Raises:
        ValueError: If no leaf category is found in category_chains.
    """
    category_chains = product_detail.get("category_chains", [])
    for chain in category_chains:
        if chain.get("is_leaf"):
            return chain["id"]
    raise ValueError(
        f"Product {product_detail.get('id', '?')} has no leaf category in "
        f"category_chains. Cannot proceed with edit. Category chains: {category_chains}"
    )


def _build_listing_edit_body(
    params: UpdateProductListingInput, context: ProductToolContext
) -> dict[str, Any]:
    """Build the TikTok product edit body with all required fields per B-4 spec.

    Per the contract (docs/integrations/tiktok_api/contract-collection.md § B-4),
    the edit endpoint requires:
    - title, description (agent-authored)
    - category_id, category_version (derived from product's current values)
    - skus, package_weight (passthrough from product detail)

    The agent only controls title and description; all other fields are derived
    from the product's current state to avoid clobbering seller changes between
    read and write.
    """
    if context.product_detail is None:
        raise UnresolvedAgentRefError(
            "update_product_listing called with no product_detail in run context. "
            "The run must read the product first via get_product_information."
        )

    body: dict[str, Any] = {}

    # Agent-authored fields (only these can change)
    if params.title is not None:
        body["title"] = params.title
    if params.description is not None:
        body["description"] = params.description

    # Required fields derived from product's current values (passthrough).
    # Never hardcode or invent these — they come from the product detail.
    body["category_id"] = _extract_leaf_category_id(context.product_detail)
    body["category_version"] = TIKTOK_PRODUCT_EDIT_CATEGORY_VERSION

    # SKUs and package weight — passthrough from product detail.
    # This ensures we only edit what the agent authored, preserving the
    # product's current configuration for these fields.
    if "skus" in context.product_detail:
        body["skus"] = context.product_detail["skus"]
    if "package_weight" in context.product_detail:
        body["package_weight"] = context.product_detail["package_weight"]

    # Optional: staged image attachment
    if params.attach_staged_image:
        if not context.staged_image_uri:
            raise UnresolvedStagedImageError(
                "update_product_listing called with attach_staged_image=True but no "
                "staged_image_uri in run context"
            )
        body["main_images"] = [{"uri": context.staged_image_uri}]

    return body


def handle_update_product_listing(
    resources: SandboxWriteResources,
    context: ProductToolContext,
    params: UpdateProductListingInput,
) -> UpdateProductListingOutput:
    body = _build_listing_edit_body(params, context)
    resources.products.edit(product_id=context.product_id, body=body)
    return UpdateProductListingOutput(
        title=params.title,
        description=params.description,
        image_attached=params.attach_staged_image,
    )


UPDATE_PRODUCT_LISTING_SPEC = ToolSpec(
    name="update_product_listing",
    description=(
        "Apply agent-authored title/description (and, if attach_staged_image is true, "
        "the run's staged image) to the bound product's listing."
    ),
    input_model=UpdateProductListingInput,
    output_model=UpdateProductListingOutput,
    classification=ToolClassification.WRITE,
    policy=ToolPolicy.CONFIRM,
    timeout_seconds=20,
)


# --- update_product_price -------------------------------------------------------


class ProductSkuPrice(BaseModel):
    # Rationale for sku_ref (an opaque per-run token, not a vendor SKU id):
    # see module docstring, "Context-bound identity AND raw-ID-free schemas".
    """One SKU's proposed new price. Identify the SKU by the sku_ref token
    given earlier in this run (for example "S1"), not by any marketplace
    code."""

    sku_ref: str
    amount: str
    currency: str = "VND"


class UpdateProductPriceInput(BaseModel):
    # Rationale for the field shape: see module docstring, "Context-bound
    # identity AND raw-ID-free schemas". Independently rejectable from
    # update_product_listing — a separate CONFIRM step, not a bundled one
    # (ADR-069 decision 1).
    """New prices to apply to one or more SKUs of the product already
    selected for this run."""

    # `min_length=1`, and required rather than defaulting (issue #1198). An
    # empty list passed local validation, and because this is a CONFIRM-policy
    # step the run then PAUSED FOR SELLER APPROVAL on an empty field diff --
    # approving nothing -- before failing at the vendor with `36009004 Skus is
    # a required field`. A confirmation gate that can pause on an empty
    # mutation trains sellers to approve without reading, which is worse than
    # the wasted round-trip. Rejecting here fails fast at the tool boundary,
    # the same shape `UnresolvedSkuRefError` already gives an unknown sku_ref.
    skus: list[ProductSkuPrice] = Field(min_length=1)


class UpdateProductPriceOutput(BaseModel):
    updated_skus: list[ProductSkuPrice] = Field(default_factory=list)


def handle_update_product_price(
    resources: SandboxWriteResources,
    context: ProductToolContext,
    params: UpdateProductPriceInput,
) -> UpdateProductPriceOutput:
    body_skus: list[dict[str, Any]] = []
    for sku in params.skus:
        try:
            vendor_sku_id = context.sku_refs[sku.sku_ref]
        except KeyError:
            raise UnresolvedSkuRefError(f"Unknown sku_ref: {sku.sku_ref!r}") from None
        body_skus.append(
            {"id": vendor_sku_id, "price": {"currency": sku.currency, "amount": sku.amount}}
        )
    resources.products.update_prices(product_id=context.product_id, body={"skus": body_skus})
    return UpdateProductPriceOutput(updated_skus=list(params.skus))


UPDATE_PRODUCT_PRICE_SPEC = ToolSpec(
    name="update_product_price",
    description=(
        "Apply new SKU prices (by opaque sku_ref) to the bound product. Independently "
        "rejectable from update_product_listing."
    ),
    input_model=UpdateProductPriceInput,
    output_model=UpdateProductPriceOutput,
    classification=ToolClassification.WRITE,
    policy=ToolPolicy.CONFIRM,
    timeout_seconds=20,
)


# --- registration + handler lookup --------------------------------------------

PRODUCT_WRITE_TOOL_HANDLERS: dict[
    str, Callable[[SandboxWriteResources, ProductToolContext, Any], BaseModel]
] = {
    UPLOAD_PRODUCT_IMAGE_SPEC.name: handle_upload_product_image,
    UPDATE_PRODUCT_LISTING_SPEC.name: handle_update_product_listing,
    UPDATE_PRODUCT_PRICE_SPEC.name: handle_update_product_price,
}


def register_product_write_tools(registry: ToolRegistry) -> None:
    """Register the three Optimize Product WRITE capabilities."""
    registry.register(UPLOAD_PRODUCT_IMAGE_SPEC)
    registry.register(UPDATE_PRODUCT_LISTING_SPEC)
    registry.register(UPDATE_PRODUCT_PRICE_SPEC)
