"""Lean sanity coverage for `workers.impact_reader.classify` (#1044).

This module's *exhaustive* classification matrix (every field combination,
edge cases, malformed payloads) is #1068's dedicated slice — deliberately
out of scope here per the #1044 issue body. What belongs here is proof that
classification is driven by realistic `ToolExecution.payload_json` shapes
(the actual request `listing.optimize_product` dispatch persists — see
`services/execution/listing.py`'s `run_optimize_product_chain` /
`_build_edit_body_from_chain`), not hand-constructed `MutationKind` enum
values — because a classifier tested only against values it already knows
how to produce cannot catch a real payload-shape mismatch.
"""

from __future__ import annotations

from juli_backend.services.impact import MutationKind
from juli_backend.workers.impact_reader.classify import (
    classify_mutation_kinds,
    rollup_metric_for,
)

# A realistic `listing.optimize_product` request payload, as dispatched by
# services/execution/listing.py — not a synthetic dict invented for this test.
_REALISTIC_PRICE_ONLY_PAYLOAD = {
    "product_id": "tt-product-001",
    "price_update": {"price": "199000", "currency": "VND"},
}

_REALISTIC_MULTI_MUTATION_PAYLOAD = {
    "product_id": "tt-product-002",
    "price_update": {"price": "149000", "currency": "VND"},
    "image_uri": "https://cdn.example/tt-product-002/hero.jpg",
    "edit_body": {
        "title": "Áo thun cotton cao cấp - Bán chạy nhất",
        "description": "Chất liệu cotton 100%, thoáng mát, form chuẩn.",
    },
}

_REALISTIC_DESCRIPTION_ONLY_PAYLOAD = {
    "product_id": "tt-product-003",
    "edit_body": {"description": "Mô tả sản phẩm mới, chi tiết hơn."},
}

_UNCLASSIFIABLE_PAYLOAD = {
    "product_id": "tt-product-004",
    "edit_body": {"category_id": "600001"},
}


def test_price_update_classifies_as_price():
    kinds = classify_mutation_kinds(_REALISTIC_PRICE_ONLY_PAYLOAD)
    assert kinds == [MutationKind.PRICE]


def test_multi_field_payload_classifies_every_touched_mutation():
    kinds = classify_mutation_kinds(_REALISTIC_MULTI_MUTATION_PAYLOAD)
    assert set(kinds) == {
        MutationKind.PRICE,
        MutationKind.IMAGE,
        MutationKind.SEO_KEYWORDS_TITLE,
        MutationKind.DESCRIPTION,
    }


def test_description_only_edit_body_classifies_as_description():
    kinds = classify_mutation_kinds(_REALISTIC_DESCRIPTION_ONLY_PAYLOAD)
    assert kinds == [MutationKind.DESCRIPTION]


def test_payload_with_no_recognized_fields_classifies_as_empty():
    """The caller must skip an unclassifiable execution, never guess."""
    assert classify_mutation_kinds(_UNCLASSIFIABLE_PAYLOAD) == []


def test_rollup_metric_for_uses_first_classified_kinds_primary():
    """Documented, deliberate simplification (issue #1044 body): the
    run-level rollup approximates the ActionCard's `expected_impact.metric`
    as the primary metric of the first classified mutation kind, rather than
    joining `ToolExecution.approval_id` back to an `ActionCard` row."""
    kinds = classify_mutation_kinds(_REALISTIC_MULTI_MUTATION_PAYLOAD)
    rollup = rollup_metric_for(kinds)
    assert rollup.key == "gmv"  # METRIC_MAP[MutationKind.PRICE].primary
    assert kinds[0] == MutationKind.PRICE
