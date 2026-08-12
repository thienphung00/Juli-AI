"""Product WRITE agent-tool capabilities — issue #982 (W1-A, ADR-069 decision 1).

The sibling handler module to `product.py` (#981's READ capabilities, left
untouched). Registers the three WRITE capabilities for Optimize Product
against a `ToolRegistry` (from `registry.py`, #980 — untouched here) and
implements their handlers:

- `upload_product_image` wraps a screened upload (ADR-055 item 20,
  `services/execution/file_screening.py` — reused, not reimplemented) into an
  asset URI. WRITE / **AUTO**: staging only. The upload itself is not yet
  attached to any listing — the listing changes only via
  `update_product_listing`, whose confirmation diff is what actually shows
  the new image to the seller (ADR-069 decision 1, playbook steps 4/4.5).
- `update_product_listing` wraps `products.edit` with agent-authored
  title/description and, when the run staged one, the image URI from
  `upload_product_image`. WRITE / **CONFIRM** (playbook step 5).
- `update_product_price` wraps `products.update_prices`. WRITE / **CONFIRM**,
  independently rejectable from the listing edit — a separate capability, not
  a bundled step, because a seller confirming new copy has not thereby
  confirmed a price change (playbook step 6).

**Context-bound identity (ADR-070 decision 1).** None of the three input
models declares an identifier field — the LLM never sees nor supplies the
bound vendor product id. Handlers take the same `ProductToolContext` #981
defined in `product.py`; this module does not invent a second context type.
`update_product_listing` and `update_product_price` do carry agent-authored,
non-identifying fields (title/description/image URI; SKU id + price) — those
are content the LLM composes or targets *within* the bound product, not a
lookup key for *which* product, so they do not violate the no-identifier
rule.

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
its handler.

**Sanitization is out of scope here (ADR-070, phase P5 / #990-995).** Output
models declare business-semantic shapes only; no caps, truncation,
source-role tagging, or banned-pattern guard is implemented in this slice.
"""

from __future__ import annotations

import base64
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

# --- upload_product_image -----------------------------------------------------


class UploadProductImageInput(BaseModel):
    """Base64-encoded raw image bytes to screen and stage. No identifier
    field: this capability does not target any product yet — the resulting
    asset URI is attached to the bound product only by a later
    `update_product_listing` call."""

    image_content_base64: str


class UploadProductImageOutput(BaseModel):
    image_uri: str


def handle_upload_product_image(
    resources: SandboxWriteResources,
    context: ProductToolContext,
    params: UploadProductImageInput,
) -> UploadProductImageOutput:
    del context  # Staging-only upload; not yet associated with any product.
    decoded = base64.b64decode(params.image_content_base64)
    screened_bytes, safe_filename = screen_and_reencode_image(decoded)
    raw = resources.products.upload_product_image(
        image_bytes=screened_bytes, filename=safe_filename
    )
    return UploadProductImageOutput(image_uri=str(raw.get("uri") or ""))


UPLOAD_PRODUCT_IMAGE_SPEC = ToolSpec(
    name="upload_product_image",
    description=(
        "Screen and upload a candidate listing image, returning a staged asset "
        "URI. The image is not applied to the listing until update_product_listing "
        "is called with the returned URI."
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
    field — the bound product identity comes from `ProductToolContext`
    (ADR-070 decision 1)."""

    title: str | None = None
    description: str | None = None
    image_uri: str | None = None


class UpdateProductListingOutput(BaseModel):
    title: str | None = None
    description: str | None = None
    image_uri: str | None = None


def _build_listing_edit_body(params: UpdateProductListingInput) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if params.title is not None:
        body["title"] = params.title
    if params.description is not None:
        body["description"] = params.description
    if params.image_uri:
        body["main_images"] = [{"uri": params.image_uri}]
    return body


def handle_update_product_listing(
    resources: SandboxWriteResources,
    context: ProductToolContext,
    params: UpdateProductListingInput,
) -> UpdateProductListingOutput:
    body = _build_listing_edit_body(params)
    resources.products.edit(product_id=context.product_id, body=body)
    return UpdateProductListingOutput(
        title=params.title,
        description=params.description,
        image_uri=params.image_uri,
    )


UPDATE_PRODUCT_LISTING_SPEC = ToolSpec(
    name="update_product_listing",
    description=(
        "Apply agent-authored title/description (and, if staged, a new image) "
        "to the bound product's listing."
    ),
    input_model=UpdateProductListingInput,
    output_model=UpdateProductListingOutput,
    classification=ToolClassification.WRITE,
    policy=ToolPolicy.CONFIRM,
    timeout_seconds=20,
)


# --- update_product_price -------------------------------------------------------


class ProductSkuPrice(BaseModel):
    """A single SKU's proposed price. `sku_id` targets a variant *within* the
    already-bound product — not a second product identifier."""

    sku_id: str
    amount: str
    currency: str = "VND"


class UpdateProductPriceInput(BaseModel):
    """No product identifier field — the bound product identity comes from
    `ProductToolContext` (ADR-070 decision 1). Independently rejectable from
    `update_product_listing` — a separate CONFIRM capability, not a bundled
    step."""

    skus: list[ProductSkuPrice] = Field(default_factory=list)


class UpdateProductPriceOutput(BaseModel):
    updated_skus: list[ProductSkuPrice] = Field(default_factory=list)


def handle_update_product_price(
    resources: SandboxWriteResources,
    context: ProductToolContext,
    params: UpdateProductPriceInput,
) -> UpdateProductPriceOutput:
    body = {
        "skus": [
            {"id": sku.sku_id, "price": {"currency": sku.currency, "amount": sku.amount}}
            for sku in params.skus
        ]
    }
    resources.products.update_prices(product_id=context.product_id, body=body)
    return UpdateProductPriceOutput(updated_skus=list(params.skus))


UPDATE_PRODUCT_PRICE_SPEC = ToolSpec(
    name="update_product_price",
    description=(
        "Apply new SKU prices to the bound product. Independently rejectable "
        "from update_product_listing."
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
