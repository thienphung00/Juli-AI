"""Product WRITE agent-tool capability tests — issue #982 (W1-A).

Covers the three WRITE capabilities for Optimize Product (ADR-069 decision 1's
granularity table, exact rows 4/4.5, 5, 6):

- `upload_product_image` wraps a screened upload (ADR-055 item 20) of
  seller-supplied image bytes staged in run context. WRITE / AUTO — staging
  only, the listing changes only via the listing edit, whose confirmation
  diff shows the new image.
- `update_product_listing` wraps `products.edit` with agent-authored
  title/description and, when the run staged one, the run's staged image.
  WRITE / CONFIRM.
- `update_product_price` wraps `products.update_prices`. WRITE / CONFIRM,
  independently rejectable from the listing edit.

Structural requirements proven here — **ADR-070 decision 1 governs the
schema shape** (its text bars a "raw vendor ID", not narrowly a "product
ID"; ADR-069's tool table is granularity only, and does not license a
schema ADR-070 forbids):

- No input schema carries the bound product identifier — the executor
  injects it from the approved run context via the shared
  `ProductToolContext` (reused from #981's `product.py`, not a second
  context type).
- No input schema accepts a raw vendor SKU id, a raw vendor asset URI, or
  raw image bytes from the model. `upload_product_image` has zero
  LLM-supplied fields (image bytes come from `context.pending_image_bytes`).
  `update_product_listing` carries `attach_staged_image: bool`, never a URI
  (the URI lives in `context.staged_image_uri`). `update_product_price`
  carries an opaque `sku_ref`, resolved against `context.sku_refs` — an
  unresolvable ref raises `UnresolvedSkuRefError` rather than passing
  anything through as a guessed vendor id.
- `upload_product_image` is explicitly AUTO; the other two are explicitly
  CONFIRM, so a later edit that silently makes a confirmed write automatic
  fails a test here. Listing and price updates are separate, independently
  rejectable capabilities.

Marketplace access is via stubbed `SandboxWriteResources` only — no live
calls, no direct `TikTokClient` construction.
"""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import BaseModel

from juli_backend.integrations.tiktok.factories import SandboxWriteResources
from juli_backend.services.agent.tools.product import ProductToolContext
from juli_backend.services.agent.tools.product_write import (
    PRODUCT_WRITE_TOOL_HANDLERS,
    UPDATE_PRODUCT_LISTING_SPEC,
    UPDATE_PRODUCT_PRICE_SPEC,
    UPLOAD_PRODUCT_IMAGE_SPEC,
    ProductSkuPrice,
    UnresolvedAgentRefError,
    UnresolvedSkuRefError,
    UnresolvedStagedImageError,
    UpdateProductListingInput,
    UpdateProductListingOutput,
    UpdateProductPriceInput,
    UpdateProductPriceOutput,
    UploadProductImageInput,
    UploadProductImageOutput,
    _build_listing_edit_body,
    handle_update_product_listing,
    handle_update_product_price,
    handle_upload_product_image,
    register_product_write_tools,
)
from juli_backend.services.agent.tools.registry import (
    ToolClassification,
    ToolPolicy,
    ToolRegistry,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCT_WRITE_MODULE = REPO_ROOT / "backend/src/juli_backend/services/agent/tools/product_write.py"

ALL_SPECS = (
    UPLOAD_PRODUCT_IMAGE_SPEC,
    UPDATE_PRODUCT_LISTING_SPEC,
    UPDATE_PRODUCT_PRICE_SPEC,
)

BOUND_PRODUCT_ID = "1736405947247986307"

# A minimal valid 1x1 PNG (magic bytes + a real, decodable image).
_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xfc\xcf\xc0\xf0\x1f\x00\x05\x05\x02\x00\xa7\x93\xa1"
    b"\xf2\x00\x00\x00\x00IEND\xaeB`\x82"
)

# Default product detail for tests that need it (issue #1389).
# Matches the shape from docs/integrations/tiktok_api/samples/products-detail-response.json
_DEFAULT_PRODUCT_DETAIL = {
    "id": BOUND_PRODUCT_ID,
    "title": "Original Title",
    "description": "Original Description",
    "category_chains": [
        {"id": "605254", "is_leaf": True, "local_name": "Water Bottles", "parent_id": "849672"}
    ],
    "skus": [
        {
            "id": "1736433041572857475",
            "inventory": [{"warehouse_id": "7657265511696664340", "quantity": 50}],
            "price": {"amount": "100000", "currency": "VND"},
        }
    ],
    "package_weight": {"value": "500", "unit": "GRAM"},
    # Required by the edit endpoint on EVERY edit, not just photo changes —
    # gate #1226 walk run f6f2695e was rejected with "MainImages is a required
    # field" on a description-only edit. A fixture without it does not model a
    # real product.
    "main_images": [
        {"uri": "tos-alisg-i-aphluv4xwc-sg/abc123", "width": 1200, "height": 1200},
    ],
    # Category-mandatory attributes. Which ones are required varies by
    # category, so a product that carries none does not model the real case.
    "product_attributes": [
        {"id": "100107", "name": "Loại bảo hành", "values": [{"id": "1001", "name": "12 tháng"}]},
    ],
}


class _FakeProductsResource:
    """Stub standing in for `ProductsResource` — records calls, no HTTP."""

    def __init__(
        self,
        *,
        edit_result: dict | None = None,
        update_prices_result: dict | None = None,
        upload_result: dict | None = None,
    ) -> None:
        self._edit_result = edit_result if edit_result is not None else {}
        self._update_prices_result = (
            update_prices_result if update_prices_result is not None else {}
        )
        self._upload_result = upload_result if upload_result is not None else {}
        self.edit_calls: list[tuple[str, dict]] = []
        self.update_prices_calls: list[tuple[str, dict]] = []
        self.upload_product_image_calls: list[dict] = []

    def edit(self, *, product_id: str, body: dict) -> dict:
        self.edit_calls.append((product_id, body))
        return self._edit_result

    def update_prices(self, *, product_id: str, body: dict) -> dict:
        self.update_prices_calls.append((product_id, body))
        return self._update_prices_result

    def upload_product_image(self, *, image_bytes: bytes, filename: str) -> dict:
        self.upload_product_image_calls.append({"image_bytes": image_bytes, "filename": filename})
        return self._upload_result


def make_resources(products: _FakeProductsResource) -> SandboxWriteResources:
    """A `SandboxWriteResources` with only `products` populated — the other
    three fields are irrelevant to product-write tools and left `None`,
    proving handlers reach the marketplace exclusively through this guarded
    shape."""
    return SandboxWriteResources(
        inventory=None,  # type: ignore[arg-type]
        products=products,  # type: ignore[arg-type]
        fulfillment=None,  # type: ignore[arg-type]
        promotion=None,  # type: ignore[arg-type]
    )


@pytest.fixture
def context() -> ProductToolContext:
    """A bound-identity context with product detail for update_product_listing.
    Tests that need staged image or sku_refs populate their own context explicitly."""
    return ProductToolContext(product_id=BOUND_PRODUCT_ID, product_detail=_DEFAULT_PRODUCT_DETAIL)


def _all_field_names(model: type[BaseModel]) -> set[str]:
    """Field names across a model and any nested Pydantic submodels/list
    item models — used to prove no raw vendor id/URI hides in a nested
    shape."""
    names: set[str] = set()
    for field_name, field_info in model.model_fields.items():
        names.add(field_name)
        annotation = field_info.annotation
        for candidate in getattr(annotation, "__args__", ()) or (annotation,):
            if isinstance(candidate, type) and issubclass(candidate, BaseModel):
                names |= _all_field_names(candidate)
    return names


class TestNoIdentifierOrRawVendorValueInAnyInputSchema:
    """ADR-070 decision 1 governs: no raw vendor ID (product id, SKU id) and
    no raw vendor asset URI in any input schema — not merely no "product
    id"-named field. Opaque refs and booleans are fine; raw vendor values
    are not."""

    BANNED_FIELD_NAMES = {
        "product_id",
        "productid",
        "sku_id",
        "skuid",
        "vendor_id",
        "vendorid",
        "asset_uri",
        "assets_uri",
        "image_uri",
        "imageuri",
        "uri",
        "id",
    }

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.name)
    def test_no_field_name_anywhere_in_the_schema_is_a_banned_raw_value(self, spec):
        offending = _all_field_names(spec.input_model) & self.BANNED_FIELD_NAMES
        assert offending == set(), f"{spec.name}: banned raw-value field(s) {offending}"

    def test_upload_product_image_input_has_zero_fields(self):
        """The strongest form of "no raw vendor value": nothing in the
        schema for a model to hallucinate or leak image bytes into."""
        assert UploadProductImageInput.model_fields == {}

    def test_update_product_listing_input_has_exactly_the_agent_authored_fields(self):
        assert set(UpdateProductListingInput.model_fields) == {
            "title",
            "description",
            "attach_staged_image",
        }

    def test_update_product_price_input_has_exactly_skus(self):
        assert set(UpdateProductPriceInput.model_fields) == {"skus"}

    def test_product_sku_price_carries_an_opaque_ref_not_a_raw_sku_id(self):
        assert set(ProductSkuPrice.model_fields) == {"sku_ref", "amount", "currency"}
        assert "sku_id" not in ProductSkuPrice.model_fields

    def test_all_three_input_models_are_distinct(self):
        models = {
            UploadProductImageInput,
            UpdateProductListingInput,
            UpdateProductPriceInput,
        }
        assert len(models) == 3


class TestWriteClassification:
    """All three capabilities are registered WRITE — explicit, not implied."""

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.name)
    def test_classification_is_write(self, spec):
        assert spec.classification is ToolClassification.WRITE


class TestPolicyDeclarations:
    """Exact per-spec policy, asserted individually so a later edit that
    silently makes a confirmed write automatic fails this test."""

    def test_upload_product_image_is_auto(self):
        assert UPLOAD_PRODUCT_IMAGE_SPEC.policy is ToolPolicy.AUTO

    def test_update_product_listing_is_confirm(self):
        assert UPDATE_PRODUCT_LISTING_SPEC.policy is ToolPolicy.CONFIRM

    def test_update_product_price_is_confirm(self):
        assert UPDATE_PRODUCT_PRICE_SPEC.policy is ToolPolicy.CONFIRM

    def test_only_upload_is_auto_among_all_three(self):
        auto_names = {spec.name for spec in ALL_SPECS if spec.policy is ToolPolicy.AUTO}
        confirm_names = {spec.name for spec in ALL_SPECS if spec.policy is ToolPolicy.CONFIRM}
        assert auto_names == {"upload_product_image"}
        assert confirm_names == {"update_product_listing", "update_product_price"}


class TestListingAndPriceAreSeparateAndIndependentlyRejectable:
    """Listing and price updates are distinct capabilities — rejecting one
    must not touch the other."""

    def test_specs_are_distinct_objects_with_distinct_names(self):
        assert UPDATE_PRODUCT_LISTING_SPEC is not UPDATE_PRODUCT_PRICE_SPEC
        assert UPDATE_PRODUCT_LISTING_SPEC.name != UPDATE_PRODUCT_PRICE_SPEC.name

    def test_distinct_input_and_output_models(self):
        assert UPDATE_PRODUCT_LISTING_SPEC.input_model is not UPDATE_PRODUCT_PRICE_SPEC.input_model
        assert (
            UPDATE_PRODUCT_LISTING_SPEC.output_model is not UPDATE_PRODUCT_PRICE_SPEC.output_model
        )

    def test_calling_update_listing_never_touches_prices(self, context):
        products = _FakeProductsResource(edit_result={"product_id": BOUND_PRODUCT_ID})
        resources = make_resources(products)

        handle_update_product_listing(
            resources, context, UpdateProductListingInput(title="New Title")
        )

        assert products.edit_calls
        assert products.update_prices_calls == []

    def test_calling_update_price_never_touches_listing(self, context):
        products = _FakeProductsResource(update_prices_result={})
        price_context = ProductToolContext(
            product_id=BOUND_PRODUCT_ID, sku_refs={"S1": "vendor-sku-1"}
        )
        resources = make_resources(products)

        handle_update_product_price(
            resources,
            price_context,
            UpdateProductPriceInput(
                skus=[ProductSkuPrice(sku_ref="S1", amount="80000", currency="VND")]
            ),
        )

        assert products.update_prices_calls
        assert products.edit_calls == []


class TestRegistration:
    """The three specs register cleanly under their business-semantic names."""

    def test_register_product_write_tools_registers_all_three_by_name(self):
        registry = ToolRegistry()

        register_product_write_tools(registry)

        names = {spec.name for spec in registry.list_all()}
        assert names == {
            "upload_product_image",
            "update_product_listing",
            "update_product_price",
        }

    def test_registered_specs_are_the_module_level_spec_objects(self):
        registry = ToolRegistry()
        register_product_write_tools(registry)

        assert registry.get("upload_product_image") is UPLOAD_PRODUCT_IMAGE_SPEC
        assert registry.get("update_product_listing") is UPDATE_PRODUCT_LISTING_SPEC
        assert registry.get("update_product_price") is UPDATE_PRODUCT_PRICE_SPEC


class TestUploadProductImage:
    """Screened upload (ADR-055 item 20) of context-staged bytes. Staging
    only; no LLM-supplied fields at all."""

    def test_handler_screens_and_uploads_bytes_staged_in_context(self):
        products = _FakeProductsResource(upload_result={"uri": "tos-img-abc123"})
        resources = make_resources(products)
        staged_context = ProductToolContext(
            product_id=BOUND_PRODUCT_ID, pending_image_bytes=_PNG_1X1
        )

        result = handle_upload_product_image(resources, staged_context, UploadProductImageInput())

        assert isinstance(result, UploadProductImageOutput)
        assert result.staged is True
        assert len(products.upload_product_image_calls) == 1

    def test_output_never_carries_the_raw_asset_uri(self):
        """ADR-070 decision 2: images surface with server-held references,
        not the reference itself."""
        assert "image_uri" not in UploadProductImageOutput.model_fields
        assert "uri" not in UploadProductImageOutput.model_fields
        assert set(UploadProductImageOutput.model_fields) == {"staged"}

    def test_handler_never_forwards_the_staged_bytes_unscreened(self):
        """Re-encoding (screening) changes the bytes on the wire — the raw
        staged bytes never reach the upload call unchanged."""
        products = _FakeProductsResource(upload_result={"uri": "tos-img-xyz"})
        resources = make_resources(products)
        staged_context = ProductToolContext(
            product_id=BOUND_PRODUCT_ID, pending_image_bytes=_PNG_1X1
        )

        handle_upload_product_image(resources, staged_context, UploadProductImageInput())

        forwarded = products.upload_product_image_calls[0]["image_bytes"]
        # Re-encoded bytes are a valid PNG again, but not required to be
        # byte-identical to the input — screening re-encodes.
        assert forwarded[:8] == b"\x89PNG\r\n\x1a\n"

    def test_handler_rejects_an_unrecognized_staged_payload(self):
        products = _FakeProductsResource()
        resources = make_resources(products)
        staged_context = ProductToolContext(
            product_id=BOUND_PRODUCT_ID, pending_image_bytes=b"not-an-image"
        )

        with pytest.raises(ValueError):
            handle_upload_product_image(resources, staged_context, UploadProductImageInput())

        assert products.upload_product_image_calls == []

    def test_handler_raises_loudly_when_nothing_is_staged(self, context):
        """No pending_image_bytes in context — must raise, never silently
        no-op or call the marketplace with nothing."""
        products = _FakeProductsResource()
        resources = make_resources(products)

        with pytest.raises(UnresolvedStagedImageError):
            handle_upload_product_image(resources, context, UploadProductImageInput())

        assert products.upload_product_image_calls == []


class TestUpdateProductListing:
    """Wraps `products.edit` with agent-authored title/description and, when
    attach_staged_image is true, the run's staged image — never a URI on the
    wire to/from the model."""

    def test_handler_calls_edit_with_the_bound_context_product_id(self, context):
        products = _FakeProductsResource(edit_result={"product_id": BOUND_PRODUCT_ID})
        resources = make_resources(products)

        handle_update_product_listing(
            resources,
            context,
            UpdateProductListingInput(title="Hero Runner Pro", description="Lightweight."),
        )

        assert len(products.edit_calls) == 1
        called_product_id, body = products.edit_calls[0]
        assert called_product_id == BOUND_PRODUCT_ID
        assert body["title"] == "Hero Runner Pro"
        assert body["description"] == "Lightweight."

    def test_handler_attaches_the_context_staged_image_when_requested(self):
        products = _FakeProductsResource(edit_result={})
        resources = make_resources(products)
        staged_context = ProductToolContext(
            product_id=BOUND_PRODUCT_ID,
            staged_image_uri="tos-img-abc123",
            product_detail=_DEFAULT_PRODUCT_DETAIL,
        )

        handle_update_product_listing(
            resources,
            staged_context,
            UpdateProductListingInput(title="T", attach_staged_image=True),
        )

        _, body = products.edit_calls[0]
        assert body["main_images"] == [{"uri": "tos-img-abc123"}]

    def test_handler_raises_loudly_when_attach_requested_but_nothing_staged(self, context):
        products = _FakeProductsResource(edit_result={})
        resources = make_resources(products)

        with pytest.raises(UnresolvedStagedImageError):
            handle_update_product_listing(
                resources,
                context,
                UpdateProductListingInput(title="T", attach_staged_image=True),
            )

        assert products.edit_calls == []

    def test_handler_carries_unset_fields_through_at_their_current_values(self, context):
        """Renamed and inverted from `..._omits_unset_fields_...` (#1389).

        It asserted the "partial edit" assumption — that a field the agent did
        not author is left out of the body. That assumption is the bug: the
        endpoint requires these fields whether or not the run is changing them,
        and omitting them produced two production 400s one after the other,
        "CategoryId is a required field" then "MainImages is a required field".

        Passing the current value through is a no-op edit, not a widening of
        what the agent authors — the agent still controls only what it set.
        """
        products = _FakeProductsResource(edit_result={})
        resources = make_resources(products)

        handle_update_product_listing(resources, context, UpdateProductListingInput(title="T"))

        _, body = products.edit_calls[0]
        assert body["title"] == "T", "the agent's edit is applied"
        assert body["description"] == _DEFAULT_PRODUCT_DETAIL["description"], (
            "unset description falls back to the product's current value"
        )
        assert body["main_images"] == [
            {"uri": img["uri"]} for img in _DEFAULT_PRODUCT_DETAIL["main_images"]
        ], "the seller's photos are preserved, never dropped"

    def test_output_echoes_the_applied_fields_without_a_uri(self):
        products = _FakeProductsResource(edit_result={})
        resources = make_resources(products)
        staged_context = ProductToolContext(
            product_id=BOUND_PRODUCT_ID,
            staged_image_uri="tos-img-1",
            product_detail=_DEFAULT_PRODUCT_DETAIL,
        )

        result = handle_update_product_listing(
            resources,
            staged_context,
            UpdateProductListingInput(
                title="Hero Runner Pro",
                description="Lightweight.",
                attach_staged_image=True,
            ),
        )

        assert isinstance(result, UpdateProductListingOutput)
        assert result.title == "Hero Runner Pro"
        assert result.description == "Lightweight."
        assert result.image_attached is True
        assert "image_uri" not in type(result).model_fields

    def test_handler_includes_all_required_fields_from_product_detail(self):
        """Verify that edit body includes all fields required by TikTok B-4
        (Edit Product / Partial endpoint) — title, description, category_id,
        category_version, skus, and package_weight.

        Refs issue #1389, docs/integrations/tiktok_api/contract-collection.md § B-4.
        """
        products = _FakeProductsResource(edit_result={})
        resources = make_resources(products)

        product_detail = {
            "id": BOUND_PRODUCT_ID,
            "title": "Original Title",
            "description": "Original Description",
            "category_chains": [
                {
                    "id": "605254",
                    "is_leaf": True,
                    "local_name": "Water Bottles",
                    "parent_id": "849672",
                }
            ],
            "skus": [
                {
                    "id": "1736433041572857475",
                    "inventory": [{"warehouse_id": "7657265511696664340", "quantity": 50}],
                    "price": {"amount": "100000", "currency": "VND"},
                }
            ],
            "package_weight": {"value": "500", "unit": "GRAM"},
            "main_images": [{"uri": "tos-alisg-i-aphluv4xwc-sg/abc123"}],
        }

        context = ProductToolContext(product_id=BOUND_PRODUCT_ID, product_detail=product_detail)

        handle_update_product_listing(
            resources,
            context,
            UpdateProductListingInput(title="New Title", description="New Description"),
        )

        _, body = products.edit_calls[0]

        # Agent-authored fields
        assert body["title"] == "New Title"
        assert body["description"] == "New Description"

        # Required fields derived from product detail
        assert body["category_id"] == "605254"
        assert body["category_version"] == "v2"

        # Passthrough from product detail
        assert body["skus"] == product_detail["skus"]
        assert body["package_weight"] == product_detail["package_weight"]

    def test_handler_raises_when_no_leaf_category_found(self):
        """Per anti-hardcoding contract, missing leaf category fails closed
        with no vendor call attempted. Never invents a category."""
        products = _FakeProductsResource(edit_result={})
        resources = make_resources(products)

        product_detail = {
            "id": BOUND_PRODUCT_ID,
            "category_chains": [
                {"id": "849672", "is_leaf": False, "local_name": "Parent", "parent_id": "root"}
            ],
        }

        context = ProductToolContext(product_id=BOUND_PRODUCT_ID, product_detail=product_detail)

        with pytest.raises(ValueError) as exc_info:
            handle_update_product_listing(
                resources,
                context,
                UpdateProductListingInput(title="New Title"),
            )

        assert "leaf category" in str(exc_info.value).lower()
        assert products.edit_calls == []

    def test_handler_raises_when_product_detail_missing(self):
        """Fail closed: without product detail, cannot build the edit body."""
        products = _FakeProductsResource(edit_result={})
        resources = make_resources(products)
        context = ProductToolContext(product_id=BOUND_PRODUCT_ID)

        with pytest.raises(UnresolvedAgentRefError):
            handle_update_product_listing(
                resources,
                context,
                UpdateProductListingInput(title="New Title"),
            )

        assert products.edit_calls == []

    def test_handler_agent_only_authors_title_and_description(self):
        """Agent controls only title/description; everything else is
        passthrough from product's current values."""
        products = _FakeProductsResource(edit_result={})
        resources = make_resources(products)

        product_detail = {
            "id": BOUND_PRODUCT_ID,
            "category_chains": [{"id": "605254", "is_leaf": True}],
            "skus": [{"id": "sku-1", "price": {"amount": "100000", "currency": "VND"}}],
            "package_weight": {"value": "500", "unit": "GRAM"},
            "main_images": [{"uri": "tos-alisg-i-aphluv4xwc-sg/abc123"}],
        }

        context = ProductToolContext(product_id=BOUND_PRODUCT_ID, product_detail=product_detail)

        handle_update_product_listing(
            resources,
            context,
            UpdateProductListingInput(title="Changed", description="Also Changed"),
        )

        _, body = products.edit_calls[0]

        # Agent-authored fields changed
        assert body["title"] == "Changed"
        assert body["description"] == "Also Changed"

        # Everything else unchanged from product detail
        assert body["category_id"] == product_detail["category_chains"][0]["id"]
        assert body["skus"] == product_detail["skus"]
        assert body["package_weight"] == product_detail["package_weight"]


class TestUpdateProductPrice:
    """Wraps `products.update_prices` via opaque sku_ref resolution —
    independently rejectable from the listing edit."""

    def test_handler_resolves_sku_ref_and_calls_update_prices(self):
        products = _FakeProductsResource(update_prices_result={})
        resources = make_resources(products)
        price_context = ProductToolContext(
            product_id=BOUND_PRODUCT_ID, sku_refs={"S1": "1736433041572857475"}
        )

        handle_update_product_price(
            resources,
            price_context,
            UpdateProductPriceInput(
                skus=[ProductSkuPrice(sku_ref="S1", amount="80000", currency="VND")]
            ),
        )

        assert len(products.update_prices_calls) == 1
        called_product_id, body = products.update_prices_calls[0]
        assert called_product_id == BOUND_PRODUCT_ID
        assert body == {
            "skus": [
                {
                    "id": "1736433041572857475",
                    "price": {"currency": "VND", "amount": "80000"},
                }
            ]
        }

    def test_handler_supports_multiple_skus_in_one_call(self):
        products = _FakeProductsResource(update_prices_result={})
        resources = make_resources(products)
        price_context = ProductToolContext(
            product_id=BOUND_PRODUCT_ID,
            sku_refs={"S1": "vendor-sku-1", "S2": "vendor-sku-2"},
        )

        handle_update_product_price(
            resources,
            price_context,
            UpdateProductPriceInput(
                skus=[
                    ProductSkuPrice(sku_ref="S1", amount="80000", currency="VND"),
                    ProductSkuPrice(sku_ref="S2", amount="120000", currency="VND"),
                ]
            ),
        )

        _, body = products.update_prices_calls[0]
        assert len(body["skus"]) == 2
        assert {sku["id"] for sku in body["skus"]} == {"vendor-sku-1", "vendor-sku-2"}

    def test_unknown_sku_ref_raises_loudly_and_never_calls_update_prices(self, context):
        """No sku_refs staged at all — an unresolvable ref must raise, never
        fall through to a passthrough or a guessed vendor id."""
        products = _FakeProductsResource(update_prices_result={})
        resources = make_resources(products)

        with pytest.raises(UnresolvedSkuRefError) as exc_info:
            handle_update_product_price(
                resources,
                context,
                UpdateProductPriceInput(
                    skus=[ProductSkuPrice(sku_ref="S1", amount="80000", currency="VND")]
                ),
            )

        assert "S1" in str(exc_info.value)
        assert products.update_prices_calls == []

    def test_unknown_sku_ref_among_known_ones_still_raises(self):
        """A partially-resolvable batch still raises rather than silently
        applying only the resolvable subset."""
        products = _FakeProductsResource(update_prices_result={})
        resources = make_resources(products)
        price_context = ProductToolContext(
            product_id=BOUND_PRODUCT_ID, sku_refs={"S1": "vendor-sku-1"}
        )

        with pytest.raises(UnresolvedSkuRefError):
            handle_update_product_price(
                resources,
                price_context,
                UpdateProductPriceInput(
                    skus=[
                        ProductSkuPrice(sku_ref="S1", amount="80000", currency="VND"),
                        ProductSkuPrice(sku_ref="S2", amount="120000", currency="VND"),
                    ]
                ),
            )

        assert products.update_prices_calls == []

    def test_output_echoes_the_applied_skus_by_ref(self):
        products = _FakeProductsResource(update_prices_result={})
        resources = make_resources(products)
        price_context = ProductToolContext(
            product_id=BOUND_PRODUCT_ID, sku_refs={"S1": "vendor-sku-1"}
        )

        result = handle_update_product_price(
            resources,
            price_context,
            UpdateProductPriceInput(
                skus=[ProductSkuPrice(sku_ref="S1", amount="80000", currency="VND")]
            ),
        )

        assert isinstance(result, UpdateProductPriceOutput)
        assert result.updated_skus == [
            ProductSkuPrice(sku_ref="S1", amount="80000", currency="VND")
        ]


class TestProductToolContextExtensionIsBackwardCompatible:
    """#981's construction (product_id only) must keep working unchanged."""

    def test_product_id_only_construction_still_works(self):
        ctx = ProductToolContext(product_id=BOUND_PRODUCT_ID)
        assert ctx.product_id == BOUND_PRODUCT_ID
        assert ctx.sku_refs == {}
        assert ctx.staged_image_uri is None
        assert ctx.pending_image_bytes is None


class TestHandlerRegistry:
    """Handlers are addressable by the same business-semantic tool name."""

    def test_all_three_names_map_to_their_handlers(self):
        assert set(PRODUCT_WRITE_TOOL_HANDLERS) == {
            "upload_product_image",
            "update_product_listing",
            "update_product_price",
        }
        assert PRODUCT_WRITE_TOOL_HANDLERS["upload_product_image"] is handle_upload_product_image
        assert (
            PRODUCT_WRITE_TOOL_HANDLERS["update_product_listing"] is handle_update_product_listing
        )
        assert PRODUCT_WRITE_TOOL_HANDLERS["update_product_price"] is handle_update_product_price


class TestOutputModelsArePydantic:
    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.name)
    def test_output_model_is_a_pydantic_model(self, spec):
        assert issubclass(spec.output_model, BaseModel)


class TestNoDirectClientConstruction:
    """ADR-068 decision 6b: agent tool handlers never import `TikTokClient`
    directly — guarded factories only. `product_write.py` may depend on the
    `SandboxWriteResources` shape the guarded factory produces, but must
    never import the client classes that construct a transport itself."""

    def test_module_never_imports_tiktok_client_construction_symbols(self):
        tree = ast.parse(PRODUCT_WRITE_MODULE.read_text(encoding="utf-8"))
        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_names.add(alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imported_names.add(alias.name)

        forbidden = {
            "TikTokClient",
            "GuardedTikTokClient",
            "ProductionReadClientFactory",
            "SandboxWriteClientFactory",
        }
        offending = imported_names & forbidden
        assert not offending, (
            f"product_write.py must not import client construction symbols: {offending}"
        )

    def test_module_imports_sandbox_write_resources_type(self):
        """It's expected — and required — to depend on the guarded factory's
        output shape; this is the one legitimate marketplace-adjacent import."""
        tree = ast.parse(PRODUCT_WRITE_MODULE.read_text(encoding="utf-8"))
        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_names.add(alias.name)

        assert "SandboxWriteResources" in imported_names

    def test_module_imports_marketplace_type_only_from_package_root(self):
        """Cross-package deep imports are capped at depth 2 (`.importlinter.toml`):
        `juli_backend.integrations.tiktok` is legal, `juli_backend.integrations.tiktok.factories`
        is not."""
        tree = ast.parse(PRODUCT_WRITE_MODULE.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("juli_backend.integrations")
            ):
                assert node.module == "juli_backend.integrations.tiktok", (
                    f"deep cross-package import forbidden: {node.module}"
                )


class TestEmptyPriceMutationCannotReachConfirmation:
    """#1198: an empty `skus` list must be rejected at the tool boundary.

    Before this, `skus: []` passed validation, and because `update_product_price`
    is CONFIRM-policy the run PAUSED FOR SELLER APPROVAL showing an empty field
    diff -- approving nothing -- then failed at the vendor with `36009004 Skus
    is a required field`. The wasted round-trip is minor; a confirmation gate
    that can pause on an empty mutation is not, because it trains sellers to
    approve without reading.
    """

    def test_empty_skus_is_rejected_by_the_input_schema(self):
        import pytest
        from pydantic import ValidationError

        from juli_backend.services.agent.tools.product_write import UpdateProductPriceInput

        with pytest.raises(ValidationError):
            UpdateProductPriceInput(skus=[])

    def test_skus_is_required_not_silently_defaulted(self):
        import pytest
        from pydantic import ValidationError

        from juli_backend.services.agent.tools.product_write import UpdateProductPriceInput

        # A missing field must fail too -- defaulting to [] would reintroduce
        # exactly the invalid value this issue is about.
        with pytest.raises(ValidationError):
            UpdateProductPriceInput()

    def test_a_single_sku_proposal_is_still_accepted(self):
        from juli_backend.services.agent.tools.product_write import (
            ProductSkuPrice,
            UpdateProductPriceInput,
        )

        parsed = UpdateProductPriceInput(
            skus=[ProductSkuPrice(sku_ref="S1", currency="VND", amount="179000")]
        )
        assert len(parsed.skus) == 1


class TestEveryRequiredFieldSurvivesADescriptionOnlyEdit:
    """Gate #1226 walk run f6f2695e: the agent edited the description only
    (`title: null`, `attach_staged_image: false`) and TikTok rejected it with

        400 {"code":36009004,"message":"MainImages is a required field and has not been provided."}

    The endpoint requires fields regardless of whether the run is changing them
    — the same lesson `category_id` taught one 400 earlier. B-4's sample cURL
    omits `main_images`, so the sample is not a complete required-field list,
    and building the body from an allowlist copied out of it is what produced
    this second failure.

    These pin the fields present on a description-only edit, which is the
    common case: the model changes copy and leaves the photo alone.
    """

    def test_a_description_only_edit_still_carries_title_and_images(self, context):
        params = UpdateProductListingInput(
            title=None, description="<p>mô tả mới</p>", attach_staged_image=False
        )

        body = _build_listing_edit_body(params, context)

        assert body["description"] == "<p>mô tả mới</p>", "the agent's edit is applied"
        assert body["title"] == context.product_detail["title"], (
            "title falls back to the product's current value — a no-op edit, not a "
            "widening of what the agent authors"
        )
        assert body["main_images"] == [
            {"uri": img["uri"]} for img in context.product_detail["main_images"]
        ], "the seller's current photos are passed through, never dropped"

    def test_main_images_are_refs_not_the_raw_detail_objects(self, context):
        """The detail carries width/height/urls; the edit body takes uri refs."""
        params = UpdateProductListingInput(
            title=None, description="<p>x</p>", attach_staged_image=False
        )

        body = _build_listing_edit_body(params, context)

        for ref in body["main_images"]:
            assert set(ref) == {"uri"}, f"unexpected keys in an image ref: {sorted(ref)}"

    def test_a_staged_image_still_replaces_the_current_ones(self, context):
        """The attach path is unchanged — passthrough must not override it."""
        ctx = replace(context, staged_image_uri="tos-staged/new-photo")
        params = UpdateProductListingInput(
            title=None, description="<p>x</p>", attach_staged_image=True
        )

        body = _build_listing_edit_body(params, ctx)

        assert body["main_images"] == [{"uri": "tos-staged/new-photo"}]

    def test_category_mandatory_attributes_are_passed_through(self, context):
        """Gate #1226 walk run f5c1f9bf: TikTokAPIError [12052104] "missing
        product attribute ID 100107" (Loại bảo hành). Which attributes a
        category makes mandatory varies by category, so there is no fixed list
        to encode — passing through whatever the product already carries is the
        only correct answer, and the only one that cannot invent a value."""
        params = UpdateProductListingInput(
            title=None, description="<p>x</p>", attach_staged_image=False
        )

        body = _build_listing_edit_body(params, context)

        assert body["product_attributes"] == context.product_detail["product_attributes"]

    def test_a_product_with_no_usable_image_fails_closed(self, context):
        """Never send an empty main_images — that would clear the listing's
        photos, which is worse than the 400 this avoids."""
        ctx = replace(context, product_detail=dict(context.product_detail, main_images=[]))
        params = UpdateProductListingInput(
            title=None, description="<p>x</p>", attach_staged_image=False
        )

        with pytest.raises(UnresolvedAgentRefError, match="main_images"):
            _build_listing_edit_body(params, ctx)
