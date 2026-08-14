"""`ToolExecutor` protocol and `ProductToolExecutor` — issue #1119 / AGT-W3A.

Covers the seam `WorkflowRunner` (`core.py`, this same slice) calls after it
has already validated a `ToolCallBlock`'s params against the target
`ToolSpec.input_model`: `ProductToolExecutor` resolves the handler + its
marketplace resources, builds `ProductToolContext` from server-held identity
bound at construction time, calls the real W1-A handler, and returns a plain
JSON-safe mapping. Marketplace access is via stubbed `ProductionReadResources`/
`SandboxWriteResources` only — no live calls, mirroring
`test_agent_tools_product_read.py`'s fake-resource pattern.
"""

from __future__ import annotations

from typing import Any

import pytest

from juli_backend.integrations.tiktok.factories import (
    ProductionReadResources,
    SandboxWriteResources,
)
from juli_backend.services.agent.runner.tool_executor import (
    ProductToolExecutor,
    ToolExecutionError,
    ToolExecutor,
)
from juli_backend.services.agent.tools import ToolRegistry
from juli_backend.services.agent.tools.product import (
    GetProductInformationInput,
    register_product_read_tools,
)
from juli_backend.services.agent.tools.product_write import (
    UpdateProductPriceInput,
    UploadProductImageInput,
    register_product_write_tools,
)


class _FakeProductsResource:
    """Stub standing in for `ProductsResource` — records calls, no HTTP."""

    def __init__(self, *, details: dict | None = None) -> None:
        self._details = details or {"title": "A widget", "status": "LIVE"}
        self.get_details_calls: list[str] = []
        self.get_seo_words_calls: list[list[str]] = []
        self.get_suggestions_calls: list[list[str]] = []
        self.update_prices_calls: list[tuple[str, dict]] = []

    def get_details(self, product_id: str) -> dict:
        self.get_details_calls.append(product_id)
        return self._details

    def get_seo_words(self, *, product_ids: list[str]) -> dict:
        self.get_seo_words_calls.append(product_ids)
        return {"products": []}

    def get_suggestions(self, *, product_ids: list[str]) -> dict:
        self.get_suggestions_calls.append(product_ids)
        return {"products": []}

    def update_prices(self, *, product_id: str, body: dict) -> dict:
        self.update_prices_calls.append((product_id, body))
        return {}


def _read_resources(products: _FakeProductsResource) -> ProductionReadResources:
    return ProductionReadResources(
        authorization=None,  # type: ignore[arg-type]
        orders=None,  # type: ignore[arg-type]
        products=products,  # type: ignore[arg-type]
        returns=None,  # type: ignore[arg-type]
        inventory=None,  # type: ignore[arg-type]
        analytics=None,  # type: ignore[arg-type]
        promotion=None,  # type: ignore[arg-type]
    )


def _write_resources(products: _FakeProductsResource) -> SandboxWriteResources:
    return SandboxWriteResources(
        inventory=None,  # type: ignore[arg-type]
        products=products,  # type: ignore[arg-type]
        fulfillment=None,  # type: ignore[arg-type]
        promotion=None,  # type: ignore[arg-type]
    )


def _full_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    return registry


class TestToolExecutorIsAStructuralProtocol:
    def test_product_tool_executor_satisfies_isinstance_check(self):
        executor = ProductToolExecutor(registry=_full_registry(), product_id="p1")
        assert isinstance(executor, ToolExecutor)

    def test_minimal_spy_satisfies_isinstance_check(self):
        class Spy:
            def execute(self, *, tool_name: str, params: Any) -> dict:
                return {}

        assert isinstance(Spy(), ToolExecutor)

    def test_object_missing_execute_does_not_satisfy_the_protocol(self):
        class NotAnExecutor:
            pass

        assert not isinstance(NotAnExecutor(), ToolExecutor)


class TestBuildsProductToolContextFromBoundIdentityOnly:
    """`ProductToolExecutor` is constructed with the run's bound product
    identity; nothing about the constructed `ProductToolContext` ever comes
    from `params` (which, for the six real Optimize Product tools, cannot
    carry an identifier at all — none of their input_models declare one)."""

    def test_read_handler_receives_the_bound_product_id(self):
        products = _FakeProductsResource()
        executor = ProductToolExecutor(
            registry=_full_registry(),
            read_resources=_read_resources(products),
            product_id="bound-product-id",
        )

        result = executor.execute(
            tool_name="get_product_information", params=GetProductInformationInput()
        )

        assert products.get_details_calls == ["bound-product-id"]
        assert isinstance(result, dict)
        assert result["status"] == "LIVE"

    def test_spoofed_identifier_in_arguments_cannot_reach_the_context(self):
        """A `ToolCallBlock.arguments` dict smuggling an extra `product_id`
        key is exactly what `GetProductInformationInput.model_validate`
        silently drops (the model declares no such field) — proving the
        constructed context still reflects only the bound identity."""
        products = _FakeProductsResource()
        executor = ProductToolExecutor(
            registry=_full_registry(),
            read_resources=_read_resources(products),
            product_id="bound-product-id",
        )
        spoofed_params = GetProductInformationInput.model_validate(
            {"product_id": "attacker-supplied-id"}
        )

        executor.execute(tool_name="get_product_information", params=spoofed_params)

        assert products.get_details_calls == ["bound-product-id"]

    def test_sku_refs_are_resolved_from_bound_context_not_arguments(self):
        products = _FakeProductsResource()
        executor = ProductToolExecutor(
            registry=_full_registry(),
            write_resources=_write_resources(products),
            product_id="bound-product-id",
            sku_refs={"S1": "vendor-sku-1"},
        )
        params = UpdateProductPriceInput.model_validate(
            {"skus": [{"sku_ref": "S1", "amount": "10000", "currency": "VND"}]}
        )

        executor.execute(tool_name="update_product_price", params=params)

        assert products.update_prices_calls == [
            (
                "bound-product-id",
                {"skus": [{"id": "vendor-sku-1", "price": {"currency": "VND", "amount": "10000"}}]},
            )
        ]


class TestMissingResourcesFailPlainly:
    def test_read_tool_without_read_resources_raises(self):
        executor = ProductToolExecutor(registry=_full_registry(), product_id="p1")

        with pytest.raises(ToolExecutionError):
            executor.execute(
                tool_name="get_product_information", params=GetProductInformationInput()
            )

    def test_write_tool_without_write_resources_raises(self):
        executor = ProductToolExecutor(
            registry=_full_registry(), product_id="p1", pending_image_bytes=b"jpeg-bytes"
        )

        with pytest.raises(ToolExecutionError):
            executor.execute(tool_name="upload_product_image", params=UploadProductImageInput())
