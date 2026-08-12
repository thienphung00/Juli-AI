"""Tests for hard size caps with always-signalled truncation (ADR-070 decision 2).

Issue #992 — three cuts, one convention each: lists cut to their top 20
entries in the caller's own order, free text cut at ~1,500 characters
verbatim below the cap, and images reduced to a bare ``{count, dimensions}``
shape with no raw nested vendor payload. Every cut that actually happens
emits ``{"truncated": true, "omitted_count": n}``; a result that needed no
cut emits no marker at all. Compaction is deterministic server code — the
determinism tests are load-bearing for the golden-file gate (#995).
"""

from __future__ import annotations

import inspect
import json

import pytest

from juli_backend.services.agent.sanitize import caps
from juli_backend.services.agent.sanitize.caps import (
    FREE_TEXT_CHAR_CAP,
    LIST_ITEM_CAP,
    PER_RESULT_TOKEN_CEILING,
    PER_RESULT_TOKEN_TARGET,
    CappedImages,
    CappedList,
    CappedText,
    cap_list,
    cap_text,
    estimate_result_tokens,
    estimate_tokens,
    sanitize_images,
)

# ---------------------------------------------------------------------------
# Constants match the issue's spec
# ---------------------------------------------------------------------------


def test_cap_constants_match_adr_070_decision_2():
    assert LIST_ITEM_CAP == 20
    assert FREE_TEXT_CHAR_CAP == 1500
    assert PER_RESULT_TOKEN_CEILING == 2000
    assert PER_RESULT_TOKEN_TARGET == 800
    assert PER_RESULT_TOKEN_TARGET < PER_RESULT_TOKEN_CEILING


# ---------------------------------------------------------------------------
# Lists: over the cap → top 20 in vendor order + marker + accurate count
# ---------------------------------------------------------------------------


def test_list_over_cap_is_cut_to_top_20_with_marker_and_accurate_omitted_count():
    items = [f"keyword-{i:02d}" for i in range(25)]
    result = cap_list(items)

    assert isinstance(result, CappedList)
    assert result.items == tuple(items[:20])
    assert result.truncated is True
    assert result.omitted_count == 5
    assert result.to_dict() == {
        "items": items[:20],
        "truncated": True,
        "omitted_count": 5,
    }


def test_list_over_cap_preserves_vendor_order_without_re_sorting():
    """Vendor relevance order is descending here — a re-sort would flip it.
    Cutting must keep exactly the first 20 elements in input order.
    """
    items = list(range(30, 0, -1))  # already vendor-ranked: most relevant first
    result = cap_list(items)
    assert result.items == tuple(range(30, 10, -1))  # first 20, order intact


@pytest.mark.parametrize(
    ("size", "expected_omitted"),
    [(21, 1), (40, 20), (100, 80)],
)
def test_list_omitted_count_is_accurate_across_sizes(size, expected_omitted):
    result = cap_list(list(range(size)))
    assert result.truncated is True
    assert result.omitted_count == expected_omitted
    assert len(result.items) == 20


def test_list_arbitrary_objects_not_just_strings():
    items = [{"keyword": f"k{i}", "volume": i} for i in range(22)]
    result = cap_list(items)
    assert result.items == tuple(items[:20])
    assert result.omitted_count == 2


# ---------------------------------------------------------------------------
# Lists: at or under the cap → no marker at all
# ---------------------------------------------------------------------------


def test_list_at_cap_emits_no_truncation_marker():
    items = [f"keyword-{i:02d}" for i in range(20)]
    result = cap_list(items)

    assert result.truncated is False
    assert result.omitted_count == 0
    payload = result.to_dict()
    assert payload == {"items": items}
    assert "truncated" not in payload
    assert "omitted_count" not in payload


def test_list_under_cap_emits_no_truncation_marker():
    items = ["only", "a", "few"]
    result = cap_list(items)
    payload = result.to_dict()
    assert payload == {"items": items}
    assert "truncated" not in payload
    assert "omitted_count" not in payload


def test_list_empty_emits_no_truncation_marker():
    result = cap_list([])
    assert result.to_dict() == {"items": []}


def test_list_custom_cap_is_honored():
    result = cap_list(list(range(10)), cap=5)
    assert result.items == (0, 1, 2, 3, 4)
    assert result.truncated is True
    assert result.omitted_count == 5


# ---------------------------------------------------------------------------
# Free text: over the char cap → cut + marker + accurate count
# ---------------------------------------------------------------------------


def test_text_over_cap_is_cut_with_marker_and_accurate_omitted_count():
    text = "a" * 2000
    result = cap_text(text)

    assert isinstance(result, CappedText)
    assert result.text == "a" * 1500
    assert len(result.text) == FREE_TEXT_CHAR_CAP
    assert result.truncated is True
    assert result.omitted_count == 500
    assert result.to_dict() == {
        "text": "a" * 1500,
        "truncated": True,
        "omitted_count": 500,
    }


def test_text_over_cap_cut_text_is_a_verbatim_prefix_of_the_original():
    text = "Ưu điểm sản phẩm: " + ("chất lượng cao, " * 200)
    result = cap_text(text)
    assert result.truncated is True
    assert text.startswith(result.text)
    assert len(result.text) == FREE_TEXT_CHAR_CAP


# ---------------------------------------------------------------------------
# Free text: under the cap → passed through verbatim, byte-for-byte
# ---------------------------------------------------------------------------


def test_text_under_cap_passes_through_verbatim_byte_for_byte():
    raw = "  Raw vendor\tdescription with   odd   spacing\nand a newline. Áo thun 100%  "
    result = cap_text(raw)

    assert result.text == raw
    assert result.text.encode("utf-8") == raw.encode("utf-8")
    assert result.truncated is False
    assert result.omitted_count == 0
    payload = result.to_dict()
    assert payload == {"text": raw}
    assert "truncated" not in payload
    assert "omitted_count" not in payload


def test_text_at_cap_exactly_emits_no_marker():
    text = "x" * FREE_TEXT_CHAR_CAP
    result = cap_text(text)
    assert result.truncated is False
    assert result.text == text
    assert "truncated" not in result.to_dict()


def test_text_empty_passes_through_with_no_marker():
    result = cap_text("")
    assert result.to_dict() == {"text": ""}


def test_text_custom_cap_is_honored():
    result = cap_text("abcdefghij", cap=4)
    assert result.text == "abcd"
    assert result.omitted_count == 6


# ---------------------------------------------------------------------------
# Images: {count, dimensions}, no raw nested vendor payload survives
# ---------------------------------------------------------------------------

_RAW_VENDOR_IMAGES = [
    {
        "url": "https://cdn.tiktok-shop.example/img/abc123.jpg",
        "id": "img_abc123",
        "width": 800,
        "height": 600,
        "vendor_meta": {"cdn_region": "sg", "checksum": "deadbeef"},
        "alt_text": "Áo thun nam cotton",
    },
    {
        "url": "https://cdn.tiktok-shop.example/img/def456.jpg",
        "id": "img_def456",
        "width": 1024,
        "height": 768,
        "vendor_meta": {"cdn_region": "sg", "checksum": "cafef00d"},
        "alt_text": "Áo thun nam cotton - back view",
    },
]


def test_images_reduced_to_count_and_dimensions_only():
    result = sanitize_images(_RAW_VENDOR_IMAGES)

    assert isinstance(result, CappedImages)
    assert result.count == 2
    assert result.dimensions == (
        caps.ImageDimensions(width=800, height=600),
        caps.ImageDimensions(width=1024, height=768),
    )
    assert result.to_dict() == {
        "count": 2,
        "dimensions": [
            {"width": 800, "height": 600},
            {"width": 1024, "height": 768},
        ],
    }


def test_images_no_raw_vendor_payload_survives_in_serialized_output():
    result = sanitize_images(_RAW_VENDOR_IMAGES)
    dumped = json.dumps(result.to_dict(), ensure_ascii=False)

    for leaked_field in (
        "url",
        "cdn.tiktok-shop",
        "img_abc123",
        "img_def456",
        "vendor_meta",
        "cdn_region",
        "checksum",
        "deadbeef",
        "alt_text",
        "cotton",
    ):
        assert leaked_field not in dumped


def test_images_over_cap_dimensions_truncated_but_count_is_true_total():
    raw_images = [{"width": 100 + i, "height": 100 + i} for i in range(25)]
    result = sanitize_images(raw_images)

    assert result.count == 25  # true total, not capped
    assert len(result.dimensions) == 20
    assert result.truncated is True
    assert result.omitted_count == 5
    payload = result.to_dict()
    assert payload["count"] == 25
    assert len(payload["dimensions"]) == 20
    assert payload["truncated"] is True
    assert payload["omitted_count"] == 5


def test_images_at_or_under_cap_emits_no_truncation_marker():
    raw_images = [{"width": 800, "height": 600}]
    result = sanitize_images(raw_images)
    payload = result.to_dict()
    assert payload == {"count": 1, "dimensions": [{"width": 800, "height": 600}]}
    assert "truncated" not in payload


def test_images_empty_list_emits_no_marker():
    result = sanitize_images([])
    assert result.to_dict() == {"count": 0, "dimensions": []}


def test_images_missing_dimension_field_raises_loudly():
    with pytest.raises(KeyError):
        sanitize_images([{"url": "https://example.com/x.jpg"}])


# ---------------------------------------------------------------------------
# Truncation-marker invariant is structural, not just convention
# ---------------------------------------------------------------------------


def test_capped_list_rejects_truncated_true_with_zero_omitted_count():
    with pytest.raises(ValueError, match="omitted_count"):
        CappedList(items=(1, 2), truncated=True, omitted_count=0)


def test_capped_list_rejects_truncated_false_with_nonzero_omitted_count():
    with pytest.raises(ValueError, match="omitted_count"):
        CappedList(items=(1, 2), truncated=False, omitted_count=3)


def test_capped_text_rejects_inconsistent_marker():
    with pytest.raises(ValueError, match="omitted_count"):
        CappedText(text="hi", truncated=True, omitted_count=0)


def test_capped_images_rejects_inconsistent_marker():
    with pytest.raises(ValueError, match="omitted_count"):
        CappedImages(count=1, dimensions=(), truncated=False, omitted_count=1)


# ---------------------------------------------------------------------------
# Token ceiling: a realistic large fixture stays within the per-result ceiling
# ---------------------------------------------------------------------------


def _realistic_large_tool_result() -> dict:
    """A representative Optimize Product tool result at worst-realistic
    size: an over-cap SEO keyword list, an over-cap free-text description,
    and an over-cap product image gallery — every field actually cut.
    """
    keywords = [f"seo-keyword-phrase-{i:03d}" for i in range(50)]
    description = "Áo thun nam cotton cao cấp, form rộng thoải mái, thấm hút mồ hôi tốt. " * 40
    images = [{"width": 1080, "height": 1080} for _ in range(30)]

    return {
        "keywords": cap_list(keywords).to_dict(),
        "description": cap_text(description).to_dict(),
        "images": sanitize_images(images).to_dict(),
    }


def test_realistic_large_fixture_stays_within_per_result_token_ceiling():
    result = _realistic_large_tool_result()
    tokens = estimate_result_tokens(result)
    assert tokens <= PER_RESULT_TOKEN_CEILING, (
        f"sanitized result estimated at {tokens} tokens, over the "
        f"{PER_RESULT_TOKEN_CEILING}-token ceiling"
    )


def test_realistic_large_fixture_every_field_actually_got_cut():
    """Sanity check on the fixture itself: proves the token-ceiling
    assertion above is meaningful (every field was actually truncated, not
    coincidentally already small).
    """
    result = _realistic_large_tool_result()
    assert result["keywords"]["truncated"] is True
    assert result["description"]["truncated"] is True
    assert result["images"]["truncated"] is True


# ---------------------------------------------------------------------------
# Determinism: same input → byte-identical result across repeated runs
# ---------------------------------------------------------------------------


def test_cap_list_is_byte_identical_across_repeated_runs():
    items = [f"kw-{i}" for i in range(37)]
    dumped_runs = {json.dumps(cap_list(items).to_dict(), sort_keys=True) for _ in range(5)}
    assert len(dumped_runs) == 1


def test_cap_text_is_byte_identical_across_repeated_runs():
    text = "lorem ipsum dolor sit amet " * 100
    dumped_runs = {json.dumps(cap_text(text).to_dict(), sort_keys=True) for _ in range(5)}
    assert len(dumped_runs) == 1


def test_sanitize_images_is_byte_identical_across_repeated_runs():
    images = [{"width": 800, "height": 600, "url": "x"} for _ in range(23)]
    dumped_runs = {json.dumps(sanitize_images(images).to_dict(), sort_keys=True) for _ in range(5)}
    assert len(dumped_runs) == 1


def test_full_realistic_fixture_is_byte_identical_across_repeated_runs():
    serialized_runs = {
        json.dumps(_realistic_large_tool_result(), sort_keys=True, ensure_ascii=False)
        for _ in range(5)
    }
    assert len(serialized_runs) == 1


def test_estimate_tokens_is_deterministic_and_stdlib_only():
    text = "a repeatable sentence for token estimation " * 10
    assert estimate_tokens(text) == estimate_tokens(text)
    # ceil(len/4), never under-counts
    assert estimate_tokens("abcde") == 2  # 5 chars -> ceil(5/4) == 2
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1


# ---------------------------------------------------------------------------
# No model call anywhere in this path
# ---------------------------------------------------------------------------


def test_caps_module_makes_no_model_or_network_call():
    """Static proof this module cannot reach an LLM or the network: the
    entire compaction path is pure stdlib slicing/serialization, so none of
    these tokens should appear in the module's source at all.
    """
    source = inspect.getsource(caps)
    forbidden_substrings = (
        "openai",
        "anthropic",
        "requests.",
        "httpx.",
        "urllib",
        "socket",
        "aiohttp",
        ".chat.completions",
        "generate(",
    )
    lowered = source.lower()
    for substring in forbidden_substrings:
        assert substring.lower() not in lowered, f"unexpected {substring!r} in caps.py"


def test_caps_module_third_party_imports_are_stdlib_only():
    """Every import in caps.py resolves to a module in the Python standard
    library — no third-party dependency was introduced for token counting
    or anything else in this file.
    """
    import ast
    import sys

    tree = ast.parse(inspect.getsource(caps))
    stdlib_module_names = sys.stdlib_module_names
    imported_top_levels = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_top_levels.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_top_levels.add(node.module.split(".")[0])

    non_stdlib = {name for name in imported_top_levels if name not in stdlib_module_names}
    assert non_stdlib == set(), f"non-stdlib imports found in caps.py: {non_stdlib}"
