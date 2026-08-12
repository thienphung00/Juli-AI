"""Golden-file gate: real recorded marketplace response in, agent-safe result out.

Issue #995 (W1-C) — the phase gate for ADR-070. A single deterministic transform
(`sanitize_product_detail_response`, defined in this module — the READ handlers in
`services/agent/tools/product.py` do not yet apply sanitization, per that module's own
"Sanitization is out of scope here" note) runs the sanitize package's building blocks
together against one real marketplace response: provenance envelopes (`VendorText` /
`to_json_safe`), machine values (`Money`, `iso_utc_timestamp`), hard caps with signalled
truncation (`cap_text`, `cap_list`, `sanitize_images`), and the inbound fail-closed
banned-pattern chokepoint (`guard_inbound_tool_result`). This is the artifact later waves
(product write tools, other domains) regress against.

## Provenance of the golden inputs — read before trusting the green check

**Recorded fixture** (`docs/integrations/tiktok_api/samples/products-detail-response.json`,
referenced directly here, not copied): a **genuinely recorded** TikTok Shop Partner API
response — `GET /product/202309/products/{product_id}` against the Fujiwa VN sandbox shop,
captured 2026-07-09 per that file's `_meta` block, redacted per
`docs/integrations/tiktok_api/samples/README.md`'s security section (`shop_cipher_redacted:
true`, no access/refresh tokens, no buyer PII). It is already relied on elsewhere in this
repo (`tests/unit/test_tiktok_api_samples.py`, `tests/integration/tiktok_recorded_replay.py`
loads its sibling `products-search-response.json`) — this test does not invent it.
**One caveat, stated plainly:** the `description` field in that recorded file is itself the
literal placeholder string `"[TRUNCATED — HTML product description]"` — whoever captured
the sample redacted the live HTML body before committing it (not buyer PII, presumably just
noisy markup), so this golden does not exercise `cap_text` truncation on real recorded prose.
Every other field used here (title, status, per-SKU price/inventory, image dimensions,
`update_time`) is the real captured value.

**Synthetic fixture**
(`tests/fixtures/agent_sanitize_golden/synthetic/large_product_detail_raw.json`): **NOT a
recorded response** — say so plainly, because the whole point of a golden-file gate
is that it reflects reality, and silently passing off a hand-authored payload as "recorded"
would defeat that. TikTok Shop's sandbox never returned a payload this large for the
single-SKU, single-image product the recorded fixture captures. Built by
`_build_synthetic_large_raw_input` below by scaling the recorded fixture's real field
*shapes* (25 SKUs, 24 main images, a description well over `FREE_TEXT_CHAR_CAP`) so this
gate actually exercises `cap_list`/`sanitize_images`/`cap_text` truncation — the small
recorded response is too small to ever trigger a cap. Every value in it is synthesized;
`_meta.provenance` inside the fixture file itself says so too.

## Regenerating the golden fixtures

Golden fixtures are committed, not computed at test time — the byte-for-byte comparison
tests are the whole point. To regenerate all four files this module owns (the synthetic raw
input plus both golden expectation files) after a deliberate change to
`sanitize_product_detail_response` or `_build_synthetic_large_raw_input`, run from the repo
root:

    PYTHONPATH=$PWD/backend/src python3 tests/unit/test_agent_sanitize_golden.py

This calls `_regenerate_golden_fixtures()` (guarded behind `if __name__ == "__main__"`, never
run by pytest). It is deterministic and idempotent: with no source change, running it again
produces byte-identical files — `git status --porcelain` is empty afterward. No step depends
on wall-clock time (`update_time` comes only from the fixture's own recorded/synthetic epoch
value), randomness, or the iteration order of a `set` or `dict` built without an explicit,
fixed key order — `test_recorded_transform_is_deterministic_across_runs` and
`test_synthetic_transform_is_deterministic_across_runs` check this in-process, without
touching the filesystem, on every test run (not just at regeneration time).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from juli_backend.services.agent.sanitize import (
    Money,
    VendorText,
    cap_list,
    cap_text,
    find_banned_pattern_hits,
    guard_inbound_tool_result,
    iso_utc_timestamp,
    sanitize_images,
    to_json_safe,
)
from juli_backend.services.agent.sanitize.caps import FREE_TEXT_CHAR_CAP, LIST_ITEM_CAP

REPO_ROOT = Path(__file__).resolve().parents[2]
RECORDED_INPUT_PATH = (
    REPO_ROOT / "docs/integrations/tiktok_api/samples/products-detail-response.json"
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "agent_sanitize_golden"
RECORDED_GOLDEN_OUTPUT_PATH = FIXTURES_DIR / "recorded" / "product_detail_sanitized.golden.json"
SYNTHETIC_INPUT_PATH = FIXTURES_DIR / "synthetic" / "large_product_detail_raw.json"
SYNTHETIC_GOLDEN_OUTPUT_PATH = (
    FIXTURES_DIR / "synthetic" / "large_product_detail_sanitized.golden.json"
)

#: The tool name this fixture stands in for — `get_product_information` (product.py)
#: is the READ capability that calls `products.get_details`, the exact endpoint this
#: recorded fixture captured.
TOOL_NAME = "get_product_information"


# ---------------------------------------------------------------------------
# The transform under test — composes the sanitize package's building blocks.
# ---------------------------------------------------------------------------


def _money_amount(raw: str) -> int | float:
    """Vendor prices arrive as decimal strings (`"72000"`); `Money.amount` must be a
    bare number (ADR-070 decision 4). VND has no minor subunit, so a whole-VND price
    is emitted as `int`; anything with a fractional remainder as `float`.
    """
    value = float(raw)
    as_int = int(value)
    return as_int if as_int == value else value


def _vendor_text_payload(capped_text: Any) -> dict[str, Any]:
    """Combine provenance (`VendorText`/`to_json_safe`) with a `cap_text` result.

    `cap_text` never re-tags provenance and `VendorText` never caps — this is the
    seam that puts the two ADR-070 decisions (2 and 3) together for one free-text
    field, exactly as a real product-tool handler would.
    """
    envelope = VendorText(text=capped_text.text)
    payload = to_json_safe(envelope)
    if capped_text.truncated:
        payload["truncated"] = True
        payload["omitted_count"] = capped_text.omitted_count
    return payload


def sanitize_product_detail_response(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Raw `GET /product/202309/products/{product_id}` envelope -> agent-safe result.

    Reads only the fields a `get_product_information`-shaped tool result needs and
    that ADR-070 permits surfacing: title/description (provenance + cap_text), status
    (a plain status string, not an identifier), `update_time` (machine ISO-8601 UTC),
    per-SKU price (`Money`, capped via `cap_list`) and inventory quantity (a bare
    `int` total), and image dimensions (`sanitize_images`). Every vendor identifier on
    the raw envelope — product id, SKU id, warehouse id, brand id, category id,
    request id, image URI, the endpoint path itself — is read by nothing here, so none
    of it can reach the returned mapping. `sku_count` and `total_inventory_quantity`
    are computed from the *full* SKU list before capping (the same "count is always
    the true total" convention `sanitize_images`/`CappedImages` already uses), not
    from whatever survives the cap.

    The result is run through `guard_inbound_tool_result` before it is returned —
    the same fail-closed chokepoint a real tool executor would apply before this
    content ever reaches the conversation (ADR-070 decision 6(a)). A clean result
    passes through unchanged; this function does not special-case that, so a
    regression that reintroduces a banned identifier would silently reroute the
    golden output to the guard's error envelope, and the byte-for-byte comparison
    against the committed golden file would fail loudly.
    """
    data = envelope["response"]["data"]

    title_payload = _vendor_text_payload(cap_text(data["title"]))
    description_payload = _vendor_text_payload(cap_text(data["description"]))

    skus = data.get("skus") or []
    sku_price_payloads: list[dict[str, Any]] = []
    total_inventory_quantity = 0
    for sku in skus:
        price = sku.get("price") or {}
        amount = _money_amount(price["tax_exclusive_price"])
        sku_price_payloads.append(Money(amount=amount, currency=price["currency"]).to_dict())
        for inventory_entry in sku.get("inventory") or []:
            total_inventory_quantity += int(inventory_entry.get("quantity") or 0)
    capped_sku_prices = cap_list(sku_price_payloads)

    capped_images = sanitize_images(data.get("main_images") or [])

    update_time_raw = data.get("update_time")
    update_time_iso = (
        iso_utc_timestamp(datetime.fromtimestamp(update_time_raw, tz=UTC))
        if update_time_raw is not None
        else None
    )

    result: dict[str, Any] = {
        "title": title_payload,
        "status": data.get("status"),
        "update_time": update_time_iso,
        "description": description_payload,
        "sku_count": len(skus),
        "total_inventory_quantity": total_inventory_quantity,
        "sku_prices": capped_sku_prices.to_dict(),
        "images": capped_images.to_dict(),
    }
    return dict(guard_inbound_tool_result(result, tool_name=TOOL_NAME))


# ---------------------------------------------------------------------------
# Synthetic large fixture — NOT a recorded response, see module docstring.
# ---------------------------------------------------------------------------


def _build_synthetic_large_raw_input() -> dict[str, Any]:
    """Deterministically build a large, synthetic product-detail-shaped raw response.

    Not recorded — see the module docstring's "Provenance of the golden inputs"
    section. Scales the recorded fixture's real field shapes past every cap this
    module exercises: 25 SKUs (`LIST_ITEM_CAP` is 20), 24 main images (same cap,
    via `sanitize_images`), and a description built from a fixed, repeated
    Vietnamese sentence — containing none of the banned patterns in
    `packages/contracts/seller-copy-banned-patterns.json` — comfortably past
    `FREE_TEXT_CHAR_CAP` (1500 characters). Pure fixed-size loops, no randomness,
    no wall-clock read: calling this function twice returns equal dicts.
    """
    base_sentence = (
        "Sản phẩm chính hãng, đóng gói cẩn thận, được kiểm định kỹ lưỡng "
        "trước khi giao đến khách hàng. "
    )
    description = (base_sentence * 25).strip()
    assert len(description) > FREE_TEXT_CHAR_CAP, "synthetic description must exceed the cap"

    sku_count = LIST_ITEM_CAP + 5
    skus = [
        {
            "id": f"synthetic-sku-{index:03d}",
            "inventory": [
                {
                    "quantity": 40 + index,
                    "warehouse_id": f"synthetic-warehouse-{index:03d}",
                }
            ],
            "price": {
                "currency": "VND",
                "sale_price": str(70_000 + index * 500),
                "tax_exclusive_price": str(70_000 + index * 500),
            },
            "seller_sku": f"XTM-SYN-{index:03d}",
            "status_info": {"status": "NORMAL"},
        }
        for index in range(sku_count)
    ]
    assert len(skus) > LIST_ITEM_CAP, "synthetic sku list must exceed the cap"

    image_count = LIST_ITEM_CAP + 4
    main_images = [
        {
            "height": 1200,
            "uri": f"synthetic-tos/{index:03d}/{{image_uri}}",
            "urls": ["{signed_image_url}"],
            "width": 1200 if index % 2 == 0 else 800,
        }
        for index in range(image_count)
    ]
    assert len(main_images) > LIST_ITEM_CAP, "synthetic image list must exceed the cap"

    return {
        "_meta": {
            "captured_at": None,
            "region": "VN",
            "merchant": "synthetic",
            "endpoint": "GET /product/202309/products/{product_id}",
            "api_version": "202309",
            "contract_section": "synthetic-large-#995",
            "contract_collection": "docs/integrations/tiktok_api/contract-collection.md",
            "shop_cipher_redacted": True,
            "provenance": (
                "SYNTHETIC — NOT a recorded marketplace response. Built by "
                "tests/unit/test_agent_sanitize_golden.py::_build_synthetic_large_raw_input "
                "to exercise cap_list/sanitize_images/cap_text truncation at a scale the real "
                "recorded fixture (single SKU, single image) never reaches. See issue #995."
            ),
        },
        "response": {
            "code": 0,
            "data": {
                "audit": {"status": "APPROVED"},
                "description": description,
                "id": "0000000000000000000",
                "main_images": main_images,
                "skus": skus,
                "status": "ACTIVATE",
                "title": "[Synthetic] Large Product Fixture For Golden-File Cap Truncation (#995)",
                "update_time": 1782892330,
            },
            "message": "Success",
            "request_id": "{synthetic_request_id}",
        },
    }


# ---------------------------------------------------------------------------
# Fixture I/O helpers (shared by tests and the regeneration entrypoint).
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump_json_bytes(value: Any) -> bytes:
    """Deterministic serialization: fixed indent, no ASCII-escaping, insertion
    key order preserved (never sorted — sorting would not change any value here,
    but this stays consistent with `estimate_result_tokens`'s documented choice
    not to sort, and gives every golden file's diff a stable, readable shape).
    """
    return (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=False) + "\n").encode("utf-8")


def _load_recorded_raw_input() -> dict[str, Any]:
    return _load_json(RECORDED_INPUT_PATH)


def _walk_strings(value: object) -> list[str]:
    """Recurse an arbitrarily nested structure and collect every string found
    (dict keys and values, list/tuple elements) — the adversarial no-leak
    assertions below need a whole-structure walk, not a top-level-keys check,
    since a leaked identifier could hide nested arbitrarily deep.
    """
    found: list[str] = []
    if isinstance(value, str):
        found.append(value)
    elif isinstance(value, dict):
        for key, val in value.items():
            found.append(str(key))
            found.extend(_walk_strings(val))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.extend(_walk_strings(item))
    return found


def _regenerate_golden_fixtures() -> None:
    """Regenerate every golden fixture this module owns. See the module
    docstring's "Regenerating the golden fixtures" section — run directly,
    never imported/called by pytest.
    """
    RECORDED_GOLDEN_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SYNTHETIC_INPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    recorded_output = sanitize_product_detail_response(_load_recorded_raw_input())
    RECORDED_GOLDEN_OUTPUT_PATH.write_bytes(_dump_json_bytes(recorded_output))

    synthetic_raw = _build_synthetic_large_raw_input()
    SYNTHETIC_INPUT_PATH.write_bytes(_dump_json_bytes(synthetic_raw))
    synthetic_output = sanitize_product_detail_response(synthetic_raw)
    SYNTHETIC_GOLDEN_OUTPUT_PATH.write_bytes(_dump_json_bytes(synthetic_output))


# ---------------------------------------------------------------------------
# Recorded fixture: real marketplace response in, agent-safe result out.
# ---------------------------------------------------------------------------


def test_recorded_input_is_the_real_committed_recorded_sample():
    """Sanity check that this test reads the same fixture other tests already
    trust as recorded (`test_tiktok_api_samples.py`), not a private copy that
    could silently drift from it.
    """
    assert RECORDED_INPUT_PATH.exists(), f"missing recorded fixture: {RECORDED_INPUT_PATH}"
    envelope = _load_recorded_raw_input()
    meta = envelope["_meta"]
    assert meta["captured_at"] == "2026-07-09"
    assert meta["merchant"] == "Fujiwa"
    assert meta["endpoint"] == "GET /product/202309/products/{product_id}"
    assert meta["shop_cipher_redacted"] is True
    assert envelope["response"]["code"] == 0


def test_recorded_transform_matches_golden_output_byte_for_byte():
    raw = _load_recorded_raw_input()
    result = sanitize_product_detail_response(raw)
    expected = RECORDED_GOLDEN_OUTPUT_PATH.read_bytes()
    assert _dump_json_bytes(result) == expected


def test_recorded_transform_is_deterministic_across_runs():
    raw = _load_recorded_raw_input()
    first = _dump_json_bytes(sanitize_product_detail_response(raw))
    second = _dump_json_bytes(sanitize_product_detail_response(raw))
    third = _dump_json_bytes(sanitize_product_detail_response(_load_recorded_raw_input()))
    assert first == second == third


def test_recorded_golden_output_has_no_truncation_markers():
    """The recorded product is genuinely small (one SKU, one image, a short
    placeholder description) — nothing here should ever get cut. Truncation is
    exercised by the synthetic large fixture below, on purpose.
    """
    output = json.loads(RECORDED_GOLDEN_OUTPUT_PATH.read_text(encoding="utf-8"))
    assert "truncated" not in output["title"]
    assert "truncated" not in output["description"]
    assert "truncated" not in output["sku_prices"]
    assert "truncated" not in output["images"]


def test_recorded_golden_output_contains_zero_banned_identifiers():
    """Checked via the shared pattern source itself (#990's loader), not a
    hand-copied list — this must stay true even if the JSON source changes.
    """
    output = json.loads(RECORDED_GOLDEN_OUTPUT_PATH.read_text(encoding="utf-8"))
    hits = find_banned_pattern_hits(output)
    assert hits == ()


def test_recorded_golden_output_leaks_no_vendor_identifier_or_endpoint_or_payload():
    raw = _load_recorded_raw_input()
    raw_data = raw["response"]["data"]
    distinctive_values = [
        raw_data["id"],
        raw_data["skus"][0]["id"],
        raw_data["skus"][0]["inventory"][0]["warehouse_id"],
        raw_data["skus"][0]["seller_sku"],
        raw_data["brand"]["id"],
        raw_data["brand"]["name"],
        raw_data["category_chains"][0]["id"],
        raw_data["category_chains"][0]["local_name"],
        raw_data["main_images"][0]["uri"],
        raw["_meta"]["endpoint"],
        raw["response"]["request_id"],
        "/product/202309/products",  # the endpoint path fragment on its own
    ]

    output = json.loads(RECORDED_GOLDEN_OUTPUT_PATH.read_text(encoding="utf-8"))
    haystack = _walk_strings(output)
    serialized = "\n".join(haystack)
    for value in distinctive_values:
        assert value not in serialized, (
            f"leaked recorded vendor value into golden output: {value!r}"
        )


# ---------------------------------------------------------------------------
# Synthetic large fixture: caps and truncation markers, on purpose.
# ---------------------------------------------------------------------------


def test_synthetic_large_input_genuinely_exceeds_every_cap():
    """Prove the fixture actually earns the word "large" before trusting that
    the golden output's truncation markers mean anything.
    """
    raw = _load_json(SYNTHETIC_INPUT_PATH)
    data = raw["response"]["data"]
    assert len(data["skus"]) > LIST_ITEM_CAP
    assert len(data["main_images"]) > LIST_ITEM_CAP
    assert len(data["description"]) > FREE_TEXT_CHAR_CAP
    assert raw["_meta"]["merchant"] == "synthetic"
    assert "SYNTHETIC" in raw["_meta"]["provenance"]


def test_synthetic_input_fixture_matches_the_deterministic_builder_byte_for_byte():
    """The committed synthetic input file is not hand-edited — it is exactly
    what `_build_synthetic_large_raw_input` produces, checked the same way the
    sanitized golden outputs are checked below.
    """
    assert _dump_json_bytes(_build_synthetic_large_raw_input()) == SYNTHETIC_INPUT_PATH.read_bytes()


def test_synthetic_transform_matches_golden_output_byte_for_byte():
    raw = _load_json(SYNTHETIC_INPUT_PATH)
    result = sanitize_product_detail_response(raw)
    expected = SYNTHETIC_GOLDEN_OUTPUT_PATH.read_bytes()
    assert _dump_json_bytes(result) == expected


def test_synthetic_transform_is_deterministic_across_runs():
    raw = _load_json(SYNTHETIC_INPUT_PATH)
    first = _dump_json_bytes(sanitize_product_detail_response(raw))
    second = _dump_json_bytes(sanitize_product_detail_response(raw))
    third = _dump_json_bytes(sanitize_product_detail_response(_build_synthetic_large_raw_input()))
    assert first == second == third


def test_synthetic_golden_output_demonstrates_cap_list_truncation_on_sku_prices():
    output = json.loads(SYNTHETIC_GOLDEN_OUTPUT_PATH.read_text(encoding="utf-8"))
    sku_prices = output["sku_prices"]
    assert sku_prices["truncated"] is True
    assert len(sku_prices["items"]) == LIST_ITEM_CAP
    assert sku_prices["omitted_count"] == 5
    # sku_count is the true total, computed before capping — not the capped count.
    assert output["sku_count"] == LIST_ITEM_CAP + 5


def test_synthetic_golden_output_demonstrates_sanitize_images_truncation():
    output = json.loads(SYNTHETIC_GOLDEN_OUTPUT_PATH.read_text(encoding="utf-8"))
    images = output["images"]
    assert images["truncated"] is True
    assert images["omitted_count"] == 4
    assert len(images["dimensions"]) == LIST_ITEM_CAP
    # count is the true total, even though dimensions itself was truncated.
    assert images["count"] == LIST_ITEM_CAP + 4


def test_synthetic_golden_output_demonstrates_cap_text_truncation_on_description():
    output = json.loads(SYNTHETIC_GOLDEN_OUTPUT_PATH.read_text(encoding="utf-8"))
    description = output["description"]
    assert description["truncated"] is True
    assert description["omitted_count"] > 0
    assert len(description["text"]) == FREE_TEXT_CHAR_CAP
    assert description["source"] == "vendor"


def test_synthetic_golden_output_contains_zero_banned_identifiers():
    output = json.loads(SYNTHETIC_GOLDEN_OUTPUT_PATH.read_text(encoding="utf-8"))
    hits = find_banned_pattern_hits(output)
    assert hits == ()


def test_synthetic_golden_output_leaks_no_vendor_identifier_or_endpoint_or_payload():
    raw = _load_json(SYNTHETIC_INPUT_PATH)
    raw_data = raw["response"]["data"]
    distinctive_values = [
        raw_data["id"],
        raw_data["skus"][0]["id"],
        raw_data["skus"][-1]["id"],
        raw_data["skus"][0]["inventory"][0]["warehouse_id"],
        raw_data["skus"][0]["seller_sku"],
        raw_data["main_images"][0]["uri"],
        raw["_meta"]["endpoint"],
        raw["response"]["request_id"],
        "/product/202309/products",
    ]

    output = json.loads(SYNTHETIC_GOLDEN_OUTPUT_PATH.read_text(encoding="utf-8"))
    haystack = _walk_strings(output)
    serialized = "\n".join(haystack)
    for value in distinctive_values:
        assert value not in serialized, (
            f"leaked synthetic vendor value into golden output: {value!r}"
        )


if __name__ == "__main__":
    _regenerate_golden_fixtures()
