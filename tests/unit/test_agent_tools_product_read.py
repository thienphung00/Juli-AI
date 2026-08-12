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
        assert result.title == "Hero Running Shoe"
        assert result.status == "ACTIVATE"
        assert result.create_time == 1_700_000_000
        assert result.update_time == 1_700_100_000

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
            details={"id": BOUND_PRODUCT_ID, "title": "T", "status": "ACTIVATE"},
            seo_words={},
            suggestions={},
        )
        resources = make_resources(products)

        result = handle_get_product_information(resources, context, GetProductInformationInput())

        assert "id" not in type(result).model_fields
        assert "product_id" not in type(result).model_fields


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
        assert result.seo_words == ["running shoe", "trainer"]
        assert result.suggested_titles == ["Hero Runner Pro"]
        assert result.suggested_descriptions == ["Lightweight everyday trainer."]

    def test_handler_tolerates_empty_upstream_payloads(self, context):
        products = _FakeProductsResource(details={}, seo_words={}, suggestions={})
        resources = make_resources(products)

        result = handle_get_seo_keywords(resources, context, GetSeoKeywordsInput())

        assert result == GetSeoKeywordsOutput(
            seo_words=[], suggested_titles=[], suggested_descriptions=[]
        )


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
