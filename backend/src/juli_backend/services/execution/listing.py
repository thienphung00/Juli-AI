"""Create Hero Product / Optimize Product API chains for P2-B6 (#379).

Workflow parameters are resolved from catalog endpoint responses and earlier steps
in the same chain — callers only need to supply inputs that cannot be derived
(for example raw image bytes or seller overrides).
"""

from __future__ import annotations

import base64
from typing import Any

from juli_backend.integrations.tiktok.factories import SandboxWriteResources


def _decode_optional_base64(value: str | None) -> bytes | None:
    if not value:
        return None
    return base64.b64decode(value)


def _attribute_required(attr: dict[str, Any]) -> bool:
    return bool(attr.get("is_requried") or attr.get("is_required"))


def _category_requires_brand(attributes: dict[str, Any]) -> bool:
    for attr in attributes.get("attributes") or []:
        name = str(attr.get("name", "")).lower()
        if name == "brand" and _attribute_required(attr):
            return True
    return False


def _required_product_attributes(attributes: dict[str, Any]) -> list[dict[str, Any]]:
    """Build product_attributes[] from Get Attributes required fields."""
    result: list[dict[str, Any]] = []
    for attr in attributes.get("attributes") or []:
        if not _attribute_required(attr):
            continue
        values = attr.get("values") or []
        if values:
            result.append({"id": attr["id"], "values": [{"id": values[0]["id"]}]})
        else:
            result.append(
                {
                    "id": attr["id"],
                    "values": [{"name": str(attr.get("name") or "Required")}],
                }
            )
    return result


def _resolve_brand_id(
    payload: dict[str, Any],
    *,
    attributes: dict[str, Any],
    brands: dict[str, Any] | None,
) -> str | None:
    if payload.get("brand_id"):
        return str(payload["brand_id"])
    if brands is None or not _category_requires_brand(attributes):
        return None
    brand_rows = brands.get("brands") or []
    authorized = [
        row for row in brand_rows if row.get("authorized_status") == "AUTHORIZED"
    ]
    chosen = authorized[0] if authorized else (brand_rows[0] if brand_rows else None)
    if chosen is None:
        return None
    return str(chosen.get("id") or "")


def _first_suggestion_text(
    suggestions: dict[str, Any] | None,
    *,
    product_id: str,
    field: str,
) -> str | None:
    if not suggestions:
        return None
    for product in suggestions.get("products") or []:
        if str(product.get("id")) != product_id:
            continue
        for suggestion in product.get("suggestions") or []:
            if suggestion.get("field") != field:
                continue
            items = suggestion.get("items") or []
            if not items:
                continue
            first = items[0]
            if isinstance(first, dict):
                return str(
                    first.get("text")
                    or first.get("value")
                    or first.get("name")
                    or ""
                ) or None
            return str(first)
    return None


def _resolve_image_uri(payload: dict[str, Any], products) -> str | None:
    if payload.get("image_uri"):
        return str(payload["image_uri"])
    image_bytes = _decode_optional_base64(payload.get("image_content_base64"))
    if image_bytes is None:
        return None
    upload = products.upload_product_image(image_bytes=image_bytes)
    return str(upload.get("uri") or "")


def _resolve_file_uri(payload: dict[str, Any], products) -> str | None:
    if payload.get("file_uri"):
        return str(payload["file_uri"])
    file_bytes = _decode_optional_base64(payload.get("file_content_base64"))
    filename = str(payload.get("file_name") or "supporting-document.pdf")
    if file_bytes is None:
        return None
    upload = products.upload_product_file(file_bytes=file_bytes, filename=filename)
    return str(upload.get("uri") or "")


def _build_create_body(
    payload: dict[str, Any],
    *,
    image_uri: str | None,
    attributes: dict[str, Any],
    brand_id: str | None,
) -> dict[str, Any]:
    if payload.get("create_body"):
        body = dict(payload["create_body"])
        if image_uri and not body.get("main_images"):
            body["main_images"] = [{"uri": image_uri}]
        return body

    if image_uri is None:
        raise ValueError("create_hero_product requires image_uri or image_content_base64")

    product_attributes = payload.get("product_attributes")
    if not product_attributes:
        product_attributes = _required_product_attributes(attributes)

    body: dict[str, Any] = {
        "category_id": payload["category_id"],
        "title": payload["title"],
        "description": payload["description"],
        "main_images": [{"uri": image_uri}],
        "skus": [
            {
                "seller_sku": payload["seller_sku"],
                "inventory": [
                    {
                        "warehouse_id": payload["warehouse_id"],
                        "quantity": payload.get("quantity", 100),
                    }
                ],
                "price": payload["price"],
            }
        ],
    }
    if product_attributes:
        body["product_attributes"] = product_attributes
    if payload.get("category_version"):
        body["category_version"] = payload["category_version"]
    if brand_id:
        body["brand_id"] = brand_id
    if payload.get("package_weight"):
        body["package_weight"] = payload["package_weight"]
    file_uri = payload.get("file_uri")
    if file_uri:
        body.setdefault("certifications", []).append({"uri": file_uri})
    return body


def _build_edit_body_from_chain(
    payload: dict[str, Any],
    *,
    product_id: str,
    current: dict[str, Any],
    suggestions: dict[str, Any],
    image_uri: str | None,
) -> dict[str, Any]:
    """Merge caller overrides with Get Product + suggestions catalog outputs."""
    edit_body = dict(payload.get("edit_body") or {})

    if "title" not in edit_body:
        suggested_title = _first_suggestion_text(
            suggestions, product_id=product_id, field="TITLE"
        )
        if suggested_title:
            edit_body["title"] = suggested_title
        elif current.get("title"):
            edit_body["title"] = current["title"]

    if "description" not in edit_body:
        suggested_description = _first_suggestion_text(
            suggestions, product_id=product_id, field="DESCRIPTION"
        )
        if suggested_description:
            edit_body["description"] = suggested_description
        elif current.get("description"):
            edit_body["description"] = current["description"]

    if "category_id" not in edit_body and current.get("category_id"):
        edit_body["category_id"] = current["category_id"]

    if image_uri:
        edit_body.setdefault("main_images", [{"uri": image_uri}])

    return edit_body


def run_create_hero_product_chain(
    resources: SandboxWriteResources,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Execute Create Hero Product workflow steps via sandbox write resources."""
    products = resources.products
    category_id = str(payload["category_id"])

    prerequisites = products.check_listing_prerequisites(category_id=category_id)
    attributes = products.get_category_attributes(category_id=category_id)

    brands = None
    brand_id = payload.get("brand_id")
    if not brand_id and (
        payload.get("resolve_brand") or _category_requires_brand(attributes)
    ):
        brands = products.get_brands(category_id=category_id)
        brand_id = _resolve_brand_id(
            payload, attributes=attributes, brands=brands
        )

    image_uri = _resolve_image_uri(payload, products)
    file_uri = _resolve_file_uri(payload, products)
    if file_uri and not payload.get("file_uri"):
        payload = {**payload, "file_uri": file_uri}

    seo_words = None
    suggestions = None
    product_ids = payload.get("product_ids") or []
    if product_ids:
        seo_words = products.get_seo_words(product_ids=[str(pid) for pid in product_ids])
        suggestions = products.get_suggestions(product_ids=[str(pid) for pid in product_ids])

    create_body = _build_create_body(
        payload,
        image_uri=image_uri,
        attributes=attributes,
        brand_id=str(brand_id) if brand_id else None,
    )
    created = products.create(body=create_body)
    product_id = str(created.get("product_id") or "")
    search_result = products.search(status=None)

    return {
        "tool_name": "listing.create_hero_product",
        "product_id": product_id,
        "skus": created.get("skus", []),
        "prerequisites": prerequisites,
        "attributes": attributes,
        "brands": brands,
        "brand_id": brand_id,
        "seo_words": seo_words,
        "suggestions": suggestions,
        "search": search_result,
    }


def run_optimize_product_chain(
    resources: SandboxWriteResources,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Execute Optimize Product workflow steps via sandbox write resources."""
    products = resources.products
    product_id = str(payload["product_id"])

    current = products.get_details(product_id)
    seo_words = products.get_seo_words(product_ids=[product_id])
    suggestions = products.get_suggestions(product_ids=[product_id])

    image_uri = _resolve_image_uri(payload, products)
    edit_body = _build_edit_body_from_chain(
        payload,
        product_id=product_id,
        current=current,
        suggestions=suggestions,
        image_uri=image_uri,
    )

    edit_result = None
    if edit_body:
        edit_result = products.edit(product_id=product_id, body=edit_body)

    price_result = None
    if payload.get("price_update"):
        price_result = products.update_prices(
            product_id=product_id,
            body=payload["price_update"],
        )

    return {
        "tool_name": "listing.optimize_product",
        "product_id": product_id,
        "current_product": current,
        "seo_words": seo_words,
        "suggestions": suggestions,
        "edit": edit_result,
        "price_update": price_result,
    }
