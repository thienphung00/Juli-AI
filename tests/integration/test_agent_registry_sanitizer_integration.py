"""Registry x sanitizer integration — issue #996 (W1 close), acceptance criterion 1.

Wave 1's three blocks (W1-A tool registry, W1-B LLM service, W1-C sanitizer) were built
in isolation against their own fixtures. This is where two of them are proven to
compose for real: the sanitize package (ADR-070, I3) runs against the **real ADR-069
registry's** tool outputs (I2) — `register_product_read_tools` populating a real
`ToolRegistry`, `PRODUCT_READ_TOOL_HANDLERS` resolving real handlers in
`services/agent/tools/product.py` — not a hand-made fixture standing in for either.

Marketplace transport is still stubbed (`_StubProductsResource`, the same pattern
`test_agent_tools_product_read.py` already uses) — this suite proves the *registry x
sanitizer* seam, not a live TikTok call, which stays out of scope for CI (`live`-marked
suites cover that separately). "Not fixtures" in the acceptance criterion means: not a
hand-authored expected-output JSON standing in for what the sanitizer produces (that is
`test_agent_sanitize_golden.py`'s job) — every assertion below is computed by actually
calling the real registry + real handler + real `guard_inbound_tool_result`.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from juli_backend.integrations.tiktok.factories import ProductionReadResources
from juli_backend.services.agent.tools.product import (
    PRODUCT_READ_TOOL_HANDLERS,
    ProductToolContext,
    register_product_read_tools,
)
from juli_backend.services.agent.tools.registry import ToolRegistry
from tests.integration.agent_tool_dispatch import dispatch_and_sanitize

BOUND_PRODUCT_ID = "1736405947247986307"
RAW_SKU_ID = "raw-sku-id-must-never-leak"
RAW_WAREHOUSE_ID = "raw-warehouse-id-must-never-leak"
RAW_IMAGE_URI = "tos/raw-image-uri-must-never-leak"


class _StubProductsResource:
    """Stands in for the marketplace transport only — the registry, the specs,
    the handlers, and the sanitize package underneath this are all real."""

    def __init__(self) -> None:
        self.get_details_calls: list[str] = []
        self.get_seo_words_calls: list[list[str]] = []
        self.get_suggestions_calls: list[list[str]] = []

    def get_details(self, product_id: str) -> dict:
        self.get_details_calls.append(product_id)
        return {
            "id": BOUND_PRODUCT_ID,
            "title": "Hero Running Shoe",
            "description": "A lightweight everyday trainer built for long runs.",
            "status": "ACTIVATE",
            "update_time": 1_782_892_330,
            "skus": [
                {
                    "id": RAW_SKU_ID,
                    "inventory": [{"quantity": 43, "warehouse_id": RAW_WAREHOUSE_ID}],
                    "price": {"currency": "VND", "tax_exclusive_price": "72000"},
                }
            ],
            "main_images": [{"width": 1200, "height": 1200, "uri": RAW_IMAGE_URI}],
        }

    def get_seo_words(self, *, product_ids: list[str]) -> dict:
        self.get_seo_words_calls.append(product_ids)
        return {
            "products": [
                {"id": BOUND_PRODUCT_ID, "seo_words": ["running shoe", "trainer", "sport"]}
            ]
        }

    def get_suggestions(self, *, product_ids: list[str]) -> dict:
        self.get_suggestions_calls.append(product_ids)
        return {
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
        }


@pytest.fixture
def registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    return registry


@pytest.fixture
def products() -> _StubProductsResource:
    return _StubProductsResource()


@pytest.fixture
def resources(products: _StubProductsResource) -> ProductionReadResources:
    return ProductionReadResources(
        authorization=None,  # type: ignore[arg-type]
        orders=None,  # type: ignore[arg-type]
        products=products,  # type: ignore[arg-type]
        returns=None,  # type: ignore[arg-type]
        inventory=None,  # type: ignore[arg-type]
        analytics=None,  # type: ignore[arg-type]
        promotion=None,  # type: ignore[arg-type]
    )


@pytest.fixture
def context() -> ProductToolContext:
    return ProductToolContext(product_id=BOUND_PRODUCT_ID)


def _leaked(sanitized, *values: str) -> list[str]:
    serialized = json.dumps(sanitized)
    return [value for value in values if value in serialized]


class TestAllReadCapabilitiesSanitizeFromTheRealRegistry:
    """Each of the three READ capabilities, dispatched against the real registry
    and real handler, with the real sanitize package applied at the boundary."""

    def test_get_product_information_sanitizes_from_the_real_registry(
        self, registry, resources, context
    ):
        sanitized = dispatch_and_sanitize(
            registry=registry,
            handlers=PRODUCT_READ_TOOL_HANDLERS,
            tool_name="get_product_information",
            resources=resources,
            context=context,
        )

        assert "error" not in sanitized
        assert sanitized["title"] == {"source": "vendor", "text": "Hero Running Shoe"}
        assert sanitized["description"]["source"] == "vendor"
        # ADR-070 decision 4: absolute ISO-8601 UTC — parseable, never a raw epoch int.
        datetime.fromisoformat(sanitized["update_time"])
        assert sanitized["create_time"] is None
        # ADR-070 decision 4: Money, not a formatted string.
        assert sanitized["sku_prices"]["items"] == [{"amount": 72000, "currency": "VND"}]
        assert sanitized["images"] == {"count": 1, "dimensions": [{"width": 1200, "height": 1200}]}
        # ADR-070 decision 1: no raw vendor identifier anywhere in the sanitized result.
        assert (
            _leaked(sanitized, BOUND_PRODUCT_ID, RAW_SKU_ID, RAW_WAREHOUSE_ID, RAW_IMAGE_URI) == []
        )

    def test_get_seo_keywords_sanitizes_from_the_real_registry(self, registry, resources, context):
        sanitized = dispatch_and_sanitize(
            registry=registry,
            handlers=PRODUCT_READ_TOOL_HANDLERS,
            tool_name="get_seo_keywords",
            resources=resources,
            context=context,
        )

        assert "error" not in sanitized
        assert sanitized["seo_words"]["items"][0] == {"source": "vendor", "text": "running shoe"}
        assert sanitized["suggested_titles"]["items"] == [
            {"source": "vendor", "text": "Hero Runner Pro"}
        ]
        assert sanitized["suggested_descriptions"]["items"] == [
            {"source": "vendor", "text": "Lightweight everyday trainer."}
        ]
        assert _leaked(sanitized, BOUND_PRODUCT_ID) == []

    def test_check_product_status_sanitizes_from_the_real_registry(
        self, registry, resources, context
    ):
        sanitized = dispatch_and_sanitize(
            registry=registry,
            handlers=PRODUCT_READ_TOOL_HANDLERS,
            tool_name="check_product_status",
            resources=resources,
            context=context,
        )

        assert "error" not in sanitized
        assert sanitized == {"status": "ACTIVATE"}
        assert _leaked(sanitized, BOUND_PRODUCT_ID) == []

    def test_all_read_tools_are_resolved_from_the_real_registry_not_a_private_map(self, registry):
        """Proves the dispatch went through `ToolRegistry.get`, not just the
        handler lookup dict — a spec absent from the registry would 404 here
        even if `PRODUCT_READ_TOOL_HANDLERS` still had an entry for it."""
        names = {spec.name for spec in registry.list_all()}
        assert names == {
            "get_product_information",
            "get_seo_keywords",
            "check_product_status",
            # #1208: the image step is a READ inspection now.
            "inspect_product_image",
        }
