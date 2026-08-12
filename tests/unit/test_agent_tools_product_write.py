"""Product WRITE agent-tool capability tests — issue #982 (W1-A).

Covers the three WRITE capabilities for Optimize Product (ADR-069 decision 1's
granularity table, exact rows 4/4.5, 5, 6):

- `upload_product_image` wraps a screened upload (ADR-055 item 20) into an
  asset URI. WRITE / AUTO — staging only, the listing changes only via the
  listing edit, whose confirmation diff shows the new image.
- `update_product_listing` wraps `products.edit` with agent-authored
  title/description (and, when supplied, the staged image URI). WRITE /
  CONFIRM.
- `update_product_price` wraps `products.update_prices`. WRITE / CONFIRM,
  independently rejectable from the listing edit.

Structural requirements proven here (ADR-070 decision 1, ADR-068 decision 4):
no input schema carries the bound product identifier — the executor injects
it from the approved run context via the shared `ProductToolContext` (reused
from #981's `product.py`, not a second context type). `upload_product_image`
is explicitly AUTO; the other two are explicitly CONFIRM, so a later edit
that silently makes a confirmed write automatic fails a test here. Listing
and price updates are separate, independently rejectable capabilities.
Marketplace access is via stubbed `SandboxWriteResources` only — no live
calls, no direct `TikTokClient` construction.
"""

from __future__ import annotations

import ast
import base64
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
    UpdateProductListingInput,
    UpdateProductListingOutput,
    UpdateProductPriceInput,
    UpdateProductPriceOutput,
    UploadProductImageInput,
    UploadProductImageOutput,
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
_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


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
    return ProductToolContext(product_id=BOUND_PRODUCT_ID)


class TestNoIdentifierInAnyInputSchema:
    """No input shape declares the bound product identifier."""

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.name)
    def test_input_model_declares_no_product_id_field(self, spec):
        assert "product_id" not in spec.input_model.model_fields

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.name)
    def test_rendered_schema_has_no_product_identifier_property(self, spec):
        schema = spec.render_input_schema()
        properties = schema.get("properties", {})
        banned = {"product_id", "productid", "product id", "id"}
        offending = {name for name in properties if name.lower().replace("_", " ") in banned}
        assert offending == set()

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
        resources = make_resources(products)

        handle_update_product_price(
            resources,
            context,
            UpdateProductPriceInput(
                skus=[ProductSkuPrice(sku_id="sku-1", amount="80000", currency="VND")]
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
    """Screened upload (ADR-055 item 20) -> asset URI. Staging only."""

    def test_handler_screens_and_uploads_then_returns_asset_uri(self, context):
        products = _FakeProductsResource(upload_result={"uri": "tos-img-abc123"})
        resources = make_resources(products)
        params = UploadProductImageInput(
            image_content_base64=base64.b64encode(_PNG_1X1).decode("ascii")
        )

        result = handle_upload_product_image(resources, context, params)

        assert isinstance(result, UploadProductImageOutput)
        assert result.image_uri == "tos-img-abc123"
        assert len(products.upload_product_image_calls) == 1

    def test_handler_never_forwards_the_caller_supplied_bytes_unscreened(self, context):
        """Re-encoding (screening) changes the bytes on the wire — the raw
        base64 payload never reaches the upload call unchanged."""
        products = _FakeProductsResource(upload_result={"uri": "tos-img-xyz"})
        resources = make_resources(products)
        params = UploadProductImageInput(
            image_content_base64=base64.b64encode(_PNG_1X1).decode("ascii")
        )

        handle_upload_product_image(resources, context, params)

        forwarded = products.upload_product_image_calls[0]["image_bytes"]
        # Re-encoded bytes are a valid PNG again, but not required to be
        # byte-identical to the input — screening re-encodes.
        assert forwarded[:8] == b"\x89PNG\r\n\x1a\n"

    def test_handler_rejects_an_unrecognized_payload(self, context):
        products = _FakeProductsResource()
        resources = make_resources(products)
        params = UploadProductImageInput(
            image_content_base64=base64.b64encode(b"not-an-image").decode("ascii")
        )

        with pytest.raises(ValueError):
            handle_upload_product_image(resources, context, params)

        assert products.upload_product_image_calls == []

    def test_output_model_never_carries_a_product_id(self):
        assert "product_id" not in UploadProductImageOutput.model_fields


class TestUpdateProductListing:
    """Wraps `products.edit` with agent-authored title/description and, when
    supplied, the staged image URI — the diff that surfaces at CONFIRM."""

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

    def test_handler_includes_staged_image_uri_in_the_edit_body_when_supplied(self, context):
        products = _FakeProductsResource(edit_result={})
        resources = make_resources(products)

        handle_update_product_listing(
            resources,
            context,
            UpdateProductListingInput(title="T", image_uri="tos-img-abc123"),
        )

        _, body = products.edit_calls[0]
        assert body["main_images"] == [{"uri": "tos-img-abc123"}]

    def test_handler_omits_unset_fields_from_the_edit_body(self, context):
        products = _FakeProductsResource(edit_result={})
        resources = make_resources(products)

        handle_update_product_listing(resources, context, UpdateProductListingInput(title="T"))

        _, body = products.edit_calls[0]
        assert "description" not in body
        assert "main_images" not in body

    def test_output_echoes_the_applied_fields(self, context):
        products = _FakeProductsResource(edit_result={})
        resources = make_resources(products)

        result = handle_update_product_listing(
            resources,
            context,
            UpdateProductListingInput(
                title="Hero Runner Pro",
                description="Lightweight.",
                image_uri="tos-img-1",
            ),
        )

        assert isinstance(result, UpdateProductListingOutput)
        assert result.title == "Hero Runner Pro"
        assert result.description == "Lightweight."
        assert result.image_uri == "tos-img-1"

    def test_input_model_has_no_product_identifier_field(self):
        assert set(UpdateProductListingInput.model_fields) == {
            "title",
            "description",
            "image_uri",
        }


class TestUpdateProductPrice:
    """Wraps `products.update_prices` — independently rejectable from the
    listing edit."""

    def test_handler_calls_update_prices_with_the_bound_context_product_id(self, context):
        products = _FakeProductsResource(update_prices_result={})
        resources = make_resources(products)

        handle_update_product_price(
            resources,
            context,
            UpdateProductPriceInput(
                skus=[ProductSkuPrice(sku_id="sku-1", amount="80000", currency="VND")]
            ),
        )

        assert len(products.update_prices_calls) == 1
        called_product_id, body = products.update_prices_calls[0]
        assert called_product_id == BOUND_PRODUCT_ID
        assert body == {"skus": [{"id": "sku-1", "price": {"currency": "VND", "amount": "80000"}}]}

    def test_handler_supports_multiple_skus_in_one_call(self, context):
        products = _FakeProductsResource(update_prices_result={})
        resources = make_resources(products)

        handle_update_product_price(
            resources,
            context,
            UpdateProductPriceInput(
                skus=[
                    ProductSkuPrice(sku_id="sku-1", amount="80000", currency="VND"),
                    ProductSkuPrice(sku_id="sku-2", amount="120000", currency="VND"),
                ]
            ),
        )

        _, body = products.update_prices_calls[0]
        assert len(body["skus"]) == 2

    def test_output_echoes_the_applied_skus(self, context):
        products = _FakeProductsResource(update_prices_result={})
        resources = make_resources(products)

        result = handle_update_product_price(
            resources,
            context,
            UpdateProductPriceInput(
                skus=[ProductSkuPrice(sku_id="sku-1", amount="80000", currency="VND")]
            ),
        )

        assert isinstance(result, UpdateProductPriceOutput)
        assert result.updated_skus == [
            ProductSkuPrice(sku_id="sku-1", amount="80000", currency="VND")
        ]

    def test_input_model_has_no_product_identifier_field(self):
        assert set(UpdateProductPriceInput.model_fields) == {"skus"}
        assert set(ProductSkuPrice.model_fields) == {"sku_id", "amount", "currency"}


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
