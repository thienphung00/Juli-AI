"""Product-diagnosis read support: allowlist entries and resource request shapes."""

from __future__ import annotations

from typing import Any, cast

import pytest

from juli_backend.integrations.tiktok.capabilities import (
    is_production_read_allowed,
    is_sandbox_write_allowed,
    path_contains_write_marker,
)
from juli_backend.integrations.tiktok.client import TikTokClient
from juli_backend.integrations.tiktok.constants import (
    PRODUCT_DIAGNOSE_OPTIMIZE_PATH,
    PRODUCT_DIAGNOSES_PATH,
)
from juli_backend.integrations.tiktok.resources.products import ProductsResource


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def get(self, path: str, params: dict[str, str] | None = None, **_: Any) -> dict[str, Any]:
        self.calls.append(("GET", path, {"params": params}))
        return {"products": []}

    def post(
        self,
        path: str,
        body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        self.calls.append(("POST", path, {"body": body, "params": params}))
        return {"diagnoses": []}


def _resource() -> tuple[ProductsResource, _FakeClient]:
    client = _FakeClient()
    return ProductsResource(cast(TikTokClient, client)), client


def test_production_read_accepts_diagnoses_get_and_diagnose_optimize_post():
    assert is_production_read_allowed("GET", PRODUCT_DIAGNOSES_PATH)
    assert is_production_read_allowed("POST", PRODUCT_DIAGNOSE_OPTIMIZE_PATH)
    assert not path_contains_write_marker(PRODUCT_DIAGNOSES_PATH)
    assert not path_contains_write_marker(PRODUCT_DIAGNOSE_OPTIMIZE_PATH)


def test_sandbox_accepts_both_diagnosis_paths():
    assert is_sandbox_write_allowed("GET", PRODUCT_DIAGNOSES_PATH)
    assert is_sandbox_write_allowed("POST", PRODUCT_DIAGNOSE_OPTIMIZE_PATH)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/product/202411/products/123/partial_edit"),
        ("PUT", "/product/202405/products/diagnoses"),
        ("POST", "/product/202405/products/diagnoses"),
        ("GET", PRODUCT_DIAGNOSE_OPTIMIZE_PATH),
        ("POST", "/product/202405/products/diagnose_optimize"),
    ],
)
def test_production_read_rejects_neighbouring_paths(method: str, path: str):
    assert not is_production_read_allowed(method, path)


def test_get_diagnoses_builds_path_and_params():
    resource, client = _resource()
    resource.get_diagnoses(["1", "2", "3"])
    assert client.calls == [
        (
            "GET",
            "/product/202405/products/diagnoses",
            {"params": {"version": "202405", "product_ids": "1,2,3"}},
        )
    ]


@pytest.mark.parametrize("count", [0, 201])
def test_get_diagnoses_rejects_bad_id_counts(count: int):
    resource, client = _resource()
    with pytest.raises(ValueError):
        resource.get_diagnoses([str(i) for i in range(count)])
    assert client.calls == []


def test_get_diagnoses_accepts_200_ids():
    resource, client = _resource()
    resource.get_diagnoses([str(i) for i in range(200)])
    assert len(client.calls) == 1


def test_diagnose_optimize_strips_none_fields():
    resource, client = _resource()
    resource.diagnose_optimize(
        product_id="p1", category_id="c1", optimization_fields=["TITLE"], title="New title"
    )
    assert client.calls == [
        (
            "POST",
            "/product/202411/products/diagnose_optimize",
            {
                "body": {
                    "product_id": "p1",
                    "category_id": "c1",
                    "optimization_fields": ["TITLE"],
                    "title": "New title",
                },
                "params": {"version": "202411"},
            },
        )
    ]
