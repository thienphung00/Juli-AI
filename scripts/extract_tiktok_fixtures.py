#!/usr/bin/env python3
"""Extract sanitized JSON fixtures from contract-collection.md for issue #294."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "docs/integrations/tiktok_api/contract-collection.md"
SAMPLES_DIR = REPO_ROOT / "docs/integrations/tiktok_api/samples"

# Layer 1 minimum set — contract-collection §N → fixture
FIXTURE_MAP: dict[str, dict[str, str]] = {
    "3. Get Authorized Shops": {
        "file": "authorized-shops-response.json",
        "endpoint": "GET /authorization/202309/shops",
        "api_version": "202309",
        "contract_section": "§3",
    },
    "4. Search Products": {
        "file": "products-search-response.json",
        "endpoint": "POST /product/202309/products/search",
        "api_version": "202309",
        "contract_section": "§4",
    },
    "5. Get Product": {
        "file": "products-detail-response.json",
        "endpoint": "GET /product/202309/products/{product_id}",
        "api_version": "202309",
        "contract_section": "§5",
    },
    "6. Get Order List": {
        "file": "orders-search-response.json",
        "endpoint": "POST /order/202309/orders/search",
        "api_version": "202309",
        "contract_section": "§6",
    },
    "7. Get Order Detail": {
        "file": "orders-detail-response.json",
        "endpoint": "GET /order/202507/orders",
        "api_version": "202507",
        "contract_section": "§7",
    },
    "8. Search Returns": {
        "file": "returns-search-response.json",
        "endpoint": "POST /return_refund/202602/returns/search",
        "api_version": "202602",
        "contract_section": "§8",
    },
    "9. Search Cancellations": {
        "file": "cancellations-search-response.json",
        "endpoint": "POST /return_refund/202602/cancellations/search",
        "api_version": "202602",
        "contract_section": "§9",
    },
    "10. Inventory Search": {
        "file": "inventory-search-response.json",
        "endpoint": "POST /product/202309/inventory/search",
        "api_version": "202309",
        "contract_section": "§10",
    },
}

PII_STRING_KEYS = {
    "buyer_email",
    "phone_number",
    "full_address",
    "name",
    "first_name",
    "last_name",
    "address_detail",
    "address_line1",
    "address_line2",
    "address_line3",
    "address_line4",
    "postal_code",
}
TOKEN_PLACEHOLDER_KEYS = {"request_id", "next_page_token"}
ARRAY_TRUNCATE_KEYS = {
    "shops",
    "products",
    "orders",
    "return_orders",
    "cancellations",
    "inventory",
    "line_items",
    "cancel_line_items",
    "return_line_items",
    "skus",
    "packages",
}


def _extract_layer1_sections(text: str) -> dict[str, str]:
    layer1_start = text.find("## Layer 1 — Production read validation")
    layer2_start = text.find("## Layer 2 — Sandbox write validation")
    if layer1_start == -1 or layer2_start == -1:
        raise ValueError("Could not locate Layer 1 section boundaries")
    layer1 = text[layer1_start:layer2_start]
    sections: dict[str, str] = {}
    for match in re.finditer(r"^### (\d+\. [^\n]+)$", layer1, re.MULTILINE):
        title = match.group(1)
        start = match.end()
        next_match = re.search(r"^### \d+\.", layer1[start:], re.MULTILINE)
        end = start + next_match.start() if next_match else len(layer1)
        sections[title] = layer1[start:end]
    return sections


def _extract_response_json(section_body: str) -> dict[str, Any]:
    # Prefer filled sanitized block when present
    sanitized_marker = "**Sanitized response"
    if sanitized_marker in section_body:
        after = section_body.split(sanitized_marker, 1)[1]
        json_start = after.find("```json")
        if json_start != -1:
            json_start += len("```json")
            json_end = after.find("```", json_start)
            candidate = after[json_start:json_end].strip()
            if candidate:
                return json.loads(candidate)

    response_marker = "**Response**"
    if response_marker not in section_body:
        raise ValueError("Missing **Response** block")
    after = section_body.split(response_marker, 1)[1]
    for line in after.splitlines():
        stripped = line.strip()
        if stripped.startswith('{"code":'):
            return json.loads(stripped)
    raise ValueError("No response JSON line found after **Response**")


def _redact_string(key: str, value: str) -> str:
    if key in PII_STRING_KEYS or key == "user_id":
        return "[REDACTED]"
    if key == "cipher" or value.startswith("ROW_"):
        return "{shop_cipher}"
    if key in TOKEN_PLACEHOLDER_KEYS:
        return "{page_token}" if key == "next_page_token" else "{request_id}"
    if key == "description" and len(value) > 120:
        return "[TRUNCATED — HTML product description]"
    if key == "url" and "tiktok" in value:
        return "{signed_image_url}"
    if key == "doc_url":
        return "{signed_document_url}"
    return value


def _sanitize_node(node: Any, key: str | None = None) -> Any:
    if isinstance(node, dict):
        sanitized: dict[str, Any] = {}
        for k, v in node.items():
            if k == "recipient_address" and isinstance(v, dict):
                sanitized[k] = "[REDACTED]"
                continue
            if k == "return_warehouse_address" and isinstance(v, dict):
                sanitized[k] = {"full_address": "[REDACTED]"}
                continue
            sanitized[k] = _sanitize_node(v, k)
        return sanitized
    if isinstance(node, list):
        items = [_sanitize_node(item, key) for item in node]
        if key in ARRAY_TRUNCATE_KEYS and items:
            return items[:1]
        return items
    if isinstance(node, str) and key is not None:
        return _redact_string(key, node)
    return node


def sanitize_response(response: dict[str, Any]) -> dict[str, Any]:
    cleaned = _sanitize_node(deepcopy(response))
    if isinstance(cleaned.get("request_id"), str):
        cleaned["request_id"] = "{request_id}"
    data = cleaned.get("data")
    if isinstance(data, dict):
        if isinstance(data.get("next_page_token"), str):
            data["next_page_token"] = "{page_token}"
        # Get Product returns single object — wrap consistency not needed
        if "orders" in data and isinstance(data["orders"], list) and data["orders"]:
            order = data["orders"][0]
            if isinstance(order.get("line_items"), list) and order["line_items"]:
                order["line_items"] = order["line_items"][:1]
    return cleaned


def build_fixture(meta: dict[str, str], response: dict[str, Any]) -> dict[str, Any]:
    return {
        "_meta": {
            "captured_at": "2026-07-09",
            "region": "VN",
            "merchant": "Fujiwa",
            "endpoint": meta["endpoint"],
            "api_version": meta["api_version"],
            "contract_section": meta["contract_section"],
            "contract_collection": "docs/integrations/tiktok_api/contract-collection.md",
            "shop_cipher_redacted": True,
        },
        "response": response,
    }


def main() -> int:
    text = CONTRACT_PATH.read_text(encoding="utf-8")
    sections = _extract_layer1_sections(text)
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    for title, meta in FIXTURE_MAP.items():
        section_key = next((k for k in sections if k.startswith(title)), None)
        if section_key is None:
            raise ValueError(f"Layer 1 section not found: {title}")
        raw = _extract_response_json(sections[section_key])
        fixture = build_fixture(meta, sanitize_response(raw))
        out_path = SAMPLES_DIR / meta["file"]
        out_path.write_text(
            json.dumps(fixture, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        written.append(meta["file"])

    print(f"Wrote {len(written)} fixtures to {SAMPLES_DIR}:")
    for name in written:
        print(f"  - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
