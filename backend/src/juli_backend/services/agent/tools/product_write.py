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

from collections.abc import Callable
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
    """No fields. The seller-supplied image bytes come from
    `context.pending_image_bytes`, never from model output (ADR-070 decision
    1) — a model cannot be asked to emit raw image bytes as output tokens."""


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
    """Agent-authored listing content for the bound product. No identifier
    field, and no raw asset URI — the bound product identity comes from
    `ProductToolContext.product_id`, and a staged image is referenced only by
    the boolean `attach_staged_image` (ADR-070 decisions 1 and 2)."""

    title: str | None = None
    description: str | None = None
    attach_staged_image: bool = False


class UpdateProductListingOutput(BaseModel):
    title: str | None = None
    description: str | None = None
    image_attached: bool = False


def _build_listing_edit_body(
    params: UpdateProductListingInput, context: ProductToolContext
) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if params.title is not None:
        body["title"] = params.title
    if params.description is not None:
        body["description"] = params.description
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
    """A single SKU's proposed price. `sku_ref` is a server-minted opaque
    token (ADR-070 decision 1's reserved extension, e.g. `"S1"`) resolved
    against `context.sku_refs` — never the raw vendor SKU id, and not a
    second product identifier either way."""

    sku_ref: str
    amount: str
    currency: str = "VND"


class UpdateProductPriceInput(BaseModel):
    """No product identifier field, and no raw vendor SKU id — the bound
    product identity comes from `ProductToolContext.product_id`, and each
    SKU is targeted by opaque `sku_ref` only (ADR-070 decision 1).
    Independently rejectable from `update_product_listing` — a separate
    CONFIRM capability, not a bundled step."""

    skus: list[ProductSkuPrice] = Field(default_factory=list)


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
