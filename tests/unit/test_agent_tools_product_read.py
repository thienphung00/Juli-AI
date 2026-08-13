"""Product READ agent-tool capability tests — issue #981 (W1-A).

Covers the three READ capabilities for Optimize Product (ADR-069 decision 1's
granularity table, exact — no collapsing, no splitting):

- `get_product_information` wraps `products.get_details`.
- `get_seo_keywords` bundles `get_seo_words` + `get_suggestions` — the only
  permitted bundle, since there is no decision point between the two calls.
- `check_product_status` wraps `products.get_details`'s status field as an
  in-run snapshot.

Structural requirements proven here (ADR-070 decision 1, ADR-068 decision 4):
no input schema carries a product identifier — the executor injects the
bound product identity from the approved run context; handlers read it from
a context parameter, never from the model-facing input. All three are
READ / AUTO. Marketplace access is via stubbed `ProductionReadResources`
only — no live calls, no direct `TikTokClient` construction.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from juli_backend.integrations.tiktok.factories import ProductionReadResources
from juli_backend.services.agent.tools.product import (
    CHECK_PRODUCT_STATUS_SPEC,
    GET_PRODUCT_INFORMATION_SPEC,
    GET_SEO_KEYWORDS_SPEC,
    PRODUCT_READ_TOOL_HANDLERS,
    CheckProductStatusInput,
    CheckProductStatusOutput,
    GetProductInformationInput,
    GetProductInformationOutput,
    GetSeoKeywordsInput,
    GetSeoKeywordsOutput,
    ProductToolContext,
    handle_check_product_status,
    handle_get_product_information,
    handle_get_seo_keywords,
    register_product_read_tools,
)
from juli_backend.services.agent.tools.registry import (
    ToolClassification,
    ToolPolicy,
    ToolRegistry,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCT_MODULE = REPO_ROOT / "backend/src/juli_backend/services/agent/tools/product.py"

ALL_SPECS = (
    GET_PRODUCT_INFORMATION_SPEC,
    GET_SEO_KEYWORDS_SPEC,
    CHECK_PRODUCT_STATUS_SPEC,
)


class _FakeProductsResource:
    """Stub standing in for `ProductsResource` — records calls, no HTTP."""

    def __init__(self, *, details: dict, seo_words: dict, suggestions: dict) -> None:
        self._details = details
        self._seo_words = seo_words
        self._suggestions = suggestions
        self.get_details_calls: list[str] = []
        self.get_seo_words_calls: list[list[str]] = []
        self.get_suggestions_calls: list[list[str]] = []

    def get_details(self, product_id: str) -> dict:
        self.get_details_calls.append(product_id)
        return self._details

    def get_seo_words(self, *, product_ids: list[str]) -> dict:
        self.get_seo_words_calls.append(product_ids)
        return self._seo_words

    def get_suggestions(self, *, product_ids: list[str]) -> dict:
        self.get_suggestions_calls.append(product_ids)
        return self._suggestions


def make_resources(products: _FakeProductsResource) -> ProductionReadResources:
    """A `ProductionReadResources` with only `products` populated — the other
    six fields are irrelevant to product-read tools and left `None`, proving
    handlers reach the marketplace exclusively through this guarded shape."""
    return ProductionReadResources(
        authorization=None,  # type: ignore[arg-type]
        orders=None,  # type: ignore[arg-type]
        products=products,  # type: ignore[arg-type]
        returns=None,  # type: ignore[arg-type]
        inventory=None,  # type: ignore[arg-type]
        analytics=None,  # type: ignore[arg-type]
        promotion=None,  # type: ignore[arg-type]
    )


BOUND_PRODUCT_ID = "1736405947247986307"


@pytest.fixture
def context() -> ProductToolContext:
    return ProductToolContext(product_id=BOUND_PRODUCT_ID)


class TestNoIdentifierInAnyInputSchema:
    """No input shape declares an identifier parameter — asserted across all three."""

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.name)
    def test_input_model_declares_no_fields_at_all(self, spec):
        """Zero fields is the strongest form of "no identifier parameter":
        there is nothing in the schema for a model to hallucinate an ID into."""
        assert spec.input_model.model_fields == {}

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.name)
    def test_rendered_schema_has_no_identifier_like_property(self, spec):
        schema = spec.render_input_schema()
        properties = schema.get("properties", {})
        identifier_like = {
            name for name in properties if "id" in name.lower() or "product" in name.lower()
        }
        assert identifier_like == set()

    def test_all_three_input_models_are_distinct_empty_models(self):
        """Distinct classes (not one shared empty model reused unlabeled) so
        each tool's schema documents its own capability under its own name."""
        models = {
            GetProductInformationInput,
            GetSeoKeywordsInput,
            CheckProductStatusInput,
        }
        assert len(models) == 3


class TestReadAutoClassification:
    """All three capabilities are registered READ / AUTO — explicit, not implied."""

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.name)
    def test_classification_is_read(self, spec):
        assert spec.classification is ToolClassification.READ

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.name)
    def test_policy_is_auto(self, spec):
        assert spec.policy is ToolPolicy.AUTO


class TestRegistration:
    """The three specs register cleanly under their business-semantic names."""

    def test_register_product_read_tools_registers_all_three_by_name(self):
        registry = ToolRegistry()

        register_product_read_tools(registry)

        names = {spec.name for spec in registry.list_all()}
        assert names == {
            "get_product_information",
            "get_seo_keywords",
            "check_product_status",
        }

    def test_registered_specs_are_the_module_level_spec_objects(self):
        registry = ToolRegistry()
        register_product_read_tools(registry)

        assert registry.get("get_product_information") is GET_PRODUCT_INFORMATION_SPEC
        assert registry.get("get_seo_keywords") is GET_SEO_KEYWORDS_SPEC
        assert registry.get("check_product_status") is CHECK_PRODUCT_STATUS_SPEC


class TestGetProductInformation:
    """Wraps `products.get_details`, taking the bound identity from context."""

    def test_handler_calls_get_details_with_the_bound_context_product_id(self, context):
        products = _FakeProductsResource(
            details={
                "id": BOUND_PRODUCT_ID,
                "title": "Hero Running Shoe",
                "status": "ACTIVATE",
                "audit": {"status": "APPROVED"},
                "create_time": 1_700_000_000,
                "update_time": 1_700_100_000,
            },
            seo_words={},
            suggestions={},
        )
        resources = make_resources(products)

        result = handle_get_product_information(resources, context, GetProductInformationInput())

        assert products.get_details_calls == [BOUND_PRODUCT_ID]
        assert isinstance(result, GetProductInformationOutput)
        # ADR-070 decision 3: vendor free text is a provenance envelope, not a
        # bare string.
        assert result.title == {"source": "vendor", "text": "Hero Running Shoe"}
        assert result.status == "ACTIVATE"
        # ADR-070 decision 4: absolute ISO-8601 UTC, never a raw epoch int.
        assert result.create_time == "2023-11-14T22:13:20+00:00"
        assert result.update_time == "2023-11-16T02:00:00+00:00"

    def test_handler_uses_context_id_not_any_id_embedded_in_details_payload(self, context):
        """Even if the raw vendor payload disagrees, the call is keyed off the
        bound context id — proving there is no path for a model-controlled id."""
        products = _FakeProductsResource(
            details={"id": "some-other-id", "title": "T", "status": "ACTIVATE"},
            seo_words={},
            suggestions={},
        )
        resources = make_resources(products)

        handle_get_product_information(resources, context, GetProductInformationInput())

        assert products.get_details_calls == [BOUND_PRODUCT_ID]

    def test_output_model_never_carries_the_raw_vendor_id(self, context):
        products = _FakeProductsResource(
            details={
                "id": BOUND_PRODUCT_ID,
                "title": "T",
                "status": "ACTIVATE",
                "skus": [
                    {
                        "id": "sku-should-never-leak",
                        "inventory": [
                            {"quantity": 5, "warehouse_id": "warehouse-should-never-leak"}
                        ],
                        "price": {"currency": "VND", "tax_exclusive_price": "1000"},
                    }
                ],
                "main_images": [{"width": 10, "height": 10, "uri": "uri-should-never-leak"}],
            },
            seo_words={},
            suggestions={},
        )
        resources = make_resources(products)

        result = handle_get_product_information(resources, context, GetProductInformationInput())

        assert "id" not in type(result).model_fields
        assert "product_id" not in type(result).model_fields
        # Stronger than the field-name check above (kept, not weakened): walk
        # the fully serialized output and prove no raw vendor identifier —
        # product id, SKU id, warehouse id, or image URI — is present in any
        # nested value either.
        serialized = json.dumps(result.model_dump(mode="json"))
        assert BOUND_PRODUCT_ID not in serialized
        assert "some-other-id" not in serialized
        assert "sku-should-never-leak" not in serialized
        assert "warehouse-should-never-leak" not in serialized
        assert "uri-should-never-leak" not in serialized

    def test_output_free_text_fields_are_provenance_envelopes(self, context):
        products = _FakeProductsResource(
            details={"id": BOUND_PRODUCT_ID, "title": "Hero Shoe", "description": "Great shoe."},
            seo_words={},
            suggestions={},
        )
        resources = make_resources(products)

        result = handle_get_product_information(resources, context, GetProductInformationInput())

        assert result.title == {"source": "vendor", "text": "Hero Shoe"}
        assert result.description == {"source": "vendor", "text": "Great shoe."}

    def test_output_sku_prices_are_money_shaped_not_formatted_strings(self, context):
        products = _FakeProductsResource(
            details={
                "id": BOUND_PRODUCT_ID,
                "skus": [
                    {
                        "id": "sku-1",
                        "inventory": [{"quantity": 3, "warehouse_id": "w-1"}],
                        "price": {"currency": "VND", "tax_exclusive_price": "72000"},
                    }
                ],
            },
            seo_words={},
            suggestions={},
        )
        resources = make_resources(products)

        result = handle_get_product_information(resources, context, GetProductInformationInput())

        assert result.sku_count == 1
        assert result.total_inventory_quantity == 3
        assert result.sku_prices == {"items": [{"amount": 72000, "currency": "VND"}]}

    def test_output_images_collapse_to_count_and_dimensions_only(self, context):
        products = _FakeProductsResource(
            details={
                "id": BOUND_PRODUCT_ID,
                "main_images": [{"width": 800, "height": 600, "uri": "tos/some-vendor-uri"}],
            },
            seo_words={},
            suggestions={},
        )
        resources = make_resources(products)

        result = handle_get_product_information(resources, context, GetProductInformationInput())

        assert result.images == {"count": 1, "dimensions": [{"width": 800, "height": 600}]}

    def test_output_list_fields_are_capped_with_signalled_truncation(self, context):
        skus = [
            {
                "id": f"sku-{i}",
                "inventory": [{"quantity": 1, "warehouse_id": f"w-{i}"}],
                "price": {"currency": "VND", "tax_exclusive_price": "1000"},
            }
            for i in range(25)
        ]
        products = _FakeProductsResource(
            details={"id": BOUND_PRODUCT_ID, "skus": skus},
            seo_words={},
            suggestions={},
        )
        resources = make_resources(products)

        result = handle_get_product_information(resources, context, GetProductInformationInput())

        assert result.sku_count == 25
        assert result.sku_prices["truncated"] is True
        assert result.sku_prices["omitted_count"] == 5
        assert len(result.sku_prices["items"]) == 20


class TestGetSeoKeywords:
    """The only permitted bundle — issues both underlying calls, one combined result."""

    def test_handler_issues_both_underlying_calls_for_the_bound_product(self, context):
        products = _FakeProductsResource(
            details={},
            seo_words={
                "products": [
                    {
                        "id": BOUND_PRODUCT_ID,
                        "seo_words": ["running shoe", "trainer", "sport"],
                    }
                ]
            },
            suggestions={
                "products": [
                    {
                        "id": BOUND_PRODUCT_ID,
                        "suggestions": [
                            {"field": "TITLE", "items": [{"text": "Hero Runner Pro"}]},
                            {
                                "field": "DESCRIPTION",
                                "items": [{"text": "Lightweight everyday trainer."}],
                            },
                        ],
                    }
                ]
            },
        )
        resources = make_resources(products)

        handle_get_seo_keywords(resources, context, GetSeoKeywordsInput())

        assert products.get_seo_words_calls == [[BOUND_PRODUCT_ID]]
        assert products.get_suggestions_calls == [[BOUND_PRODUCT_ID]]

    def test_handler_returns_one_combined_result(self, context):
        products = _FakeProductsResource(
            details={},
            seo_words={
                "products": [{"id": BOUND_PRODUCT_ID, "seo_words": ["running shoe", "trainer"]}]
            },
            suggestions={
                "products": [
                    {
                        "id": BOUND_PRODUCT_ID,
                        "suggestions": [
                            {"field": "TITLE", "items": [{"text": "Hero Runner Pro"}]},
                            {
                                "field": "DESCRIPTION",
                                "items": [{"text": "Lightweight everyday trainer."}],
                            },
                        ],
                    }
                ]
            },
        )
        resources = make_resources(products)

        result = handle_get_seo_keywords(resources, context, GetSeoKeywordsInput())

        assert isinstance(result, GetSeoKeywordsOutput)
        # ADR-070 decision 3: each vendor-sourced suggestion string is its own
        # provenance envelope; decision 2: the list itself is a capped envelope.
        assert result.seo_words == {
            "items": [
                {"source": "vendor", "text": "running shoe"},
                {"source": "vendor", "text": "trainer"},
            ]
        }
        assert result.suggested_titles == {
            "items": [{"source": "vendor", "text": "Hero Runner Pro"}]
        }
        assert result.suggested_descriptions == {
            "items": [{"source": "vendor", "text": "Lightweight everyday trainer."}]
        }

    def test_handler_tolerates_empty_upstream_payloads(self, context):
        products = _FakeProductsResource(details={}, seo_words={}, suggestions={})
        resources = make_resources(products)

        result = handle_get_seo_keywords(resources, context, GetSeoKeywordsInput())

        assert result == GetSeoKeywordsOutput(
            seo_words={"items": []},
            suggested_titles={"items": []},
            suggested_descriptions={"items": []},
        )

    def test_output_list_fields_are_capped_with_signalled_truncation(self, context):
        words = [f"keyword-{i}" for i in range(25)]
        products = _FakeProductsResource(
            details={},
            seo_words={"products": [{"id": BOUND_PRODUCT_ID, "seo_words": words}]},
            suggestions={},
        )
        resources = make_resources(products)

        result = handle_get_seo_keywords(resources, context, GetSeoKeywordsInput())

        assert result.seo_words["truncated"] is True
        assert result.seo_words["omitted_count"] == 5
        assert len(result.seo_words["items"]) == 20


class TestCheckProductStatus:
    """Wraps `products.get_details`'s status field as an in-run snapshot."""

    def test_handler_calls_get_details_with_the_bound_context_product_id(self, context):
        products = _FakeProductsResource(
            details={"id": BOUND_PRODUCT_ID, "title": "T", "status": "FREEZE"},
            seo_words={},
            suggestions={},
        )
        resources = make_resources(products)

        result = handle_check_product_status(resources, context, CheckProductStatusInput())

        assert products.get_details_calls == [BOUND_PRODUCT_ID]
        assert isinstance(result, CheckProductStatusOutput)
        assert result.status == "FREEZE"

    def test_output_carries_only_the_status_snapshot_no_identifier(self, context):
        assert set(CheckProductStatusOutput.model_fields) == {"status"}


class TestHandlerRegistry:
    """Handlers are addressable by the same business-semantic tool name."""

    def test_all_three_names_map_to_their_handlers(self):
        assert set(PRODUCT_READ_TOOL_HANDLERS) == {
            "get_product_information",
            "get_seo_keywords",
            "check_product_status",
        }
        assert (
            PRODUCT_READ_TOOL_HANDLERS["get_product_information"] is handle_get_product_information
        )
        assert PRODUCT_READ_TOOL_HANDLERS["get_seo_keywords"] is handle_get_seo_keywords
        assert PRODUCT_READ_TOOL_HANDLERS["check_product_status"] is handle_check_product_status


class TestOutputModelsArePydantic:
    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.name)
    def test_output_model_is_a_pydantic_model(self, spec):
        assert issubclass(spec.output_model, BaseModel)


class TestNoDirectClientConstruction:
    """ADR-068 decision 6b: agent tool handlers never import `TikTokClient`
    directly — guarded factories only. `product.py` may depend on the
    `ProductionReadResources` shape the guarded factory produces, but must
    never import the client classes that construct a transport itself."""

    def test_product_module_never_imports_tiktok_client_construction_symbols(self):
        tree = ast.parse(PRODUCT_MODULE.read_text(encoding="utf-8"))
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
        assert not offending, f"product.py must not import client construction symbols: {offending}"

    def test_product_module_imports_production_read_resources_type(self):
        """It's expected — and required — to depend on the guarded factory's
        output shape; this is the one legitimate marketplace-adjacent import."""
        tree = ast.parse(PRODUCT_MODULE.read_text(encoding="utf-8"))
        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_names.add(alias.name)

        assert "ProductionReadResources" in imported_names
