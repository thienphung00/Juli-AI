"""Lean sanity coverage for `workers.impact_reader.classify` (#1044), extended
to the exhaustive classification matrix (#1068).

#1044 established the lean baseline: proof that classification is driven by
realistic `ToolExecution.payload_json` shapes (the actual request
`listing.optimize_product` dispatch persists — see
`services/execution/listing.py`'s `run_optimize_product_chain` /
`_build_edit_body_from_chain`), not hand-constructed `MutationKind` enum
values. It deliberately left the exhaustive matrix — every field
combination, every `MutationKind` branch, malformed/falsy payloads, and
composition with the real downstream pipeline — to this file.

**Why the exhaustive matrix matters (issue #1068 body).** Before this file,
`tests/` contained zero references to `classify_mutation_kinds`, and the
`MutationKind.IMAGE` / `MutationKind.SEO_KEYWORDS_TITLE` branches were never
exercised by any test in the repo — precisely the two branches feeding the
`impressions_ctr` metric family (also zero gate coverage, see #1045).
`classify_mutation_kinds` decides which metric a run is measured against; if
it is wrong, the reading is computed correctly against the wrong metric,
with the wrong volume floor and the wrong control calibration, and it looks
entirely plausible — nothing downstream checks it.

**Realistic caller shape, one honest exception.** `services/execution/
listing.py`'s `_build_edit_body_from_chain` always nests `title`/
`description` overrides under `payload["edit_body"]` — the real caller never
sends them at the payload's top level. `classify_mutation_kinds` itself
still has an `edit_body.get(...) or payload.get(...)` branch for both
fields, per its own contract (not scoped to only `listing.py`'s current
caller). The dedicated top-level-field tests below are labeled honestly as
exercising that branch, not as claiming today's real caller produces that
shape.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from juli_backend.services.impact import (
    METRIC_MAP,
    ControlCandidate,
    MutationKind,
    RawDailyRecord,
    compute_confidence,
    compute_metric_reading,
    resolve_metric,
    select_control_pool,
    volume_floor_for,
    volume_indicator_for,
)
from juli_backend.workers.impact_reader.classify import (
    classify_mutation_kinds,
    rollup_metric_for,
)

# ---------------------------------------------------------------------------
# Realistic `listing.optimize_product` request payloads (#1044's style) —
# not synthetic dicts invented for this test.
# ---------------------------------------------------------------------------

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

_REALISTIC_TITLE_ONLY_PAYLOAD = {
    "product_id": "tt-product-005",
    "edit_body": {"title": "Từ khóa SEO mới - Áo thun nam"},
}

_REALISTIC_IMAGE_URI_ONLY_PAYLOAD = {
    "product_id": "tt-product-006",
    "image_uri": "https://cdn.example/tt-product-006/hero.jpg",
}

_REALISTIC_IMAGE_BASE64_ONLY_PAYLOAD = {
    "product_id": "tt-product-007",
    # A real `_resolve_image_uri` fallback path (services/execution/listing.py)
    # — the caller supplied raw image bytes instead of a hosted URI.
    "image_content_base64": "aGVsbG8gd29ybGQ=",
}

# `classify_mutation_kinds`'s own `edit_body.get(...) or payload.get(...)`
# branch — not a shape today's real caller produces (see module docstring).
_TOP_LEVEL_TITLE_ONLY_PAYLOAD = {
    "product_id": "tt-product-008",
    "title": "Từ khóa SEO trực tiếp, không qua edit_body",
}
_TOP_LEVEL_DESCRIPTION_ONLY_PAYLOAD = {
    "product_id": "tt-product-009",
    "description": "Mô tả trực tiếp, không qua edit_body",
}

_IMAGE_AND_TITLE_NO_PRICE_PAYLOAD = {
    "product_id": "tt-product-010",
    "image_uri": "https://cdn.example/tt-product-010/hero.jpg",
    "edit_body": {"title": "Tiêu đề mới, không đổi giá"},
}

_TITLE_AND_DESCRIPTION_NO_PRICE_NO_IMAGE_PAYLOAD = {
    "product_id": "tt-product-011",
    "edit_body": {
        "title": "Tiêu đề mới",
        "description": "Mô tả mới",
    },
}


# ===========================================================================
# Every MutationKind branch, exercised from a realistic payload (acceptance
# criterion 1).
# ===========================================================================


class TestEveryBranchFromARealisticPayload:
    def test_price_update_classifies_as_price(self):
        kinds = classify_mutation_kinds(_REALISTIC_PRICE_ONLY_PAYLOAD)
        assert kinds == [MutationKind.PRICE]

    def test_image_uri_classifies_as_image(self):
        kinds = classify_mutation_kinds(_REALISTIC_IMAGE_URI_ONLY_PAYLOAD)
        assert kinds == [MutationKind.IMAGE]

    def test_image_content_base64_classifies_as_image(self):
        """`image_content_base64` is a distinct payload key from `image_uri`
        (`_resolve_image_uri`'s raw-bytes fallback path) — never exercised
        by any test in the repo before this file (issue #1068 body)."""
        kinds = classify_mutation_kinds(_REALISTIC_IMAGE_BASE64_ONLY_PAYLOAD)
        assert kinds == [MutationKind.IMAGE]

    def test_edit_body_title_classifies_as_seo_keywords_title(self):
        """The realistic shape: `_build_edit_body_from_chain` always nests
        `title` under `edit_body` — never exercised by any test in the repo
        before this file (issue #1068 body)."""
        kinds = classify_mutation_kinds(_REALISTIC_TITLE_ONLY_PAYLOAD)
        assert kinds == [MutationKind.SEO_KEYWORDS_TITLE]

    def test_top_level_title_also_classifies_as_seo_keywords_title(self):
        """`classify_mutation_kinds`'s own OR-branch (`payload.get("title")`),
        not a shape today's real caller sends — see module docstring."""
        kinds = classify_mutation_kinds(_TOP_LEVEL_TITLE_ONLY_PAYLOAD)
        assert kinds == [MutationKind.SEO_KEYWORDS_TITLE]

    def test_edit_body_description_classifies_as_description(self):
        kinds = classify_mutation_kinds(_REALISTIC_DESCRIPTION_ONLY_PAYLOAD)
        assert kinds == [MutationKind.DESCRIPTION]

    def test_top_level_description_also_classifies_as_description(self):
        """`classify_mutation_kinds`'s own OR-branch (`payload.get("description")`),
        not a shape today's real caller sends — see module docstring."""
        kinds = classify_mutation_kinds(_TOP_LEVEL_DESCRIPTION_ONLY_PAYLOAD)
        assert kinds == [MutationKind.DESCRIPTION]


# ===========================================================================
# A payload carrying several mutated fields yields all applicable kinds, in
# a deterministic order (acceptance criterion 2).
# ===========================================================================


class TestMultiFieldPayloadDeterministicOrder:
    def test_multi_field_payload_classifies_every_touched_mutation(self):
        kinds = classify_mutation_kinds(_REALISTIC_MULTI_MUTATION_PAYLOAD)
        assert set(kinds) == {
            MutationKind.PRICE,
            MutationKind.IMAGE,
            MutationKind.SEO_KEYWORDS_TITLE,
            MutationKind.DESCRIPTION,
        }

    def test_all_four_kinds_come_back_in_the_fixed_price_image_seo_description_order(self):
        """`classify_mutation_kinds`'s documented deterministic order:
        price, image, SEO/title, description — pinned exactly, not just as a
        set (the weaker assertion above only proves membership)."""
        kinds = classify_mutation_kinds(_REALISTIC_MULTI_MUTATION_PAYLOAD)
        assert kinds == [
            MutationKind.PRICE,
            MutationKind.IMAGE,
            MutationKind.SEO_KEYWORDS_TITLE,
            MutationKind.DESCRIPTION,
        ]

    def test_output_order_is_independent_of_the_payload_dict_key_insertion_order(self):
        """The fixed append order comes from the function's own branching,
        not from dict iteration order — two payloads with the same fields
        inserted in different orders must classify identically."""
        payload_a = {
            "product_id": "tt-product-012",
            "price_update": {"price": "1"},
            "image_uri": "https://cdn.example/a/hero.jpg",
            "edit_body": {"title": "t", "description": "d"},
        }
        payload_b = {
            "edit_body": {"description": "d", "title": "t"},
            "image_uri": "https://cdn.example/a/hero.jpg",
            "product_id": "tt-product-012",
            "price_update": {"price": "1"},
        }
        assert classify_mutation_kinds(payload_a) == classify_mutation_kinds(payload_b)

    def test_image_before_seo_before_description_when_price_is_absent(self):
        """Without a price mutation, the remaining fixed order (image, SEO,
        description) is still observable — proves the order is a total
        fixed order, not merely "price always comes first"."""
        kinds = classify_mutation_kinds(_IMAGE_AND_TITLE_NO_PRICE_PAYLOAD)
        assert kinds == [MutationKind.IMAGE, MutationKind.SEO_KEYWORDS_TITLE]

    def test_seo_before_description_when_price_and_image_are_absent(self):
        kinds = classify_mutation_kinds(_TITLE_AND_DESCRIPTION_NO_PRICE_NO_IMAGE_PAYLOAD)
        assert kinds == [MutationKind.SEO_KEYWORDS_TITLE, MutationKind.DESCRIPTION]


# ===========================================================================
# A payload with no recognised field is handled explicitly — never an
# unhandled KeyError, and never a silent default to the price family
# (acceptance criterion 3). This is the single most important guard in this
# file: a silent default to PRICE would hide behind GMV, the one family that
# was always well covered, and the misclassification would never surface.
# ===========================================================================


class TestNoRecognizedFieldIsHandledExplicitlyNeverDefaultsToPrice:
    def test_payload_with_only_an_unrecognized_field_classifies_as_empty(self):
        """The caller (`workers/impact_reader/pipeline.py`'s `run_daily_
        impact_reader`) checks `if not mutations: skip` and counts it as
        `executions_skipped_unclassified` — `[]` is the designed state that
        drives that skip, not an incidental empty result."""
        kinds = classify_mutation_kinds(_UNCLASSIFIABLE_PAYLOAD)
        assert kinds == []
        assert kinds != [MutationKind.PRICE]

    def test_completely_empty_payload_classifies_as_empty_not_a_keyerror(self):
        kinds = classify_mutation_kinds({"product_id": "tt-product-013"})
        assert kinds == []

    def test_payload_missing_product_id_entirely_does_not_raise(self):
        assert classify_mutation_kinds({}) == []

    def test_falsy_recognized_field_values_never_classify_never_default_to_price(self):
        """Every recognized key is present but falsy (`None`, empty string,
        empty dict) — `classify_mutation_kinds` uses truthy checks
        (`payload.get("price_update")`, not `"price_update" in payload`), so
        none of these should classify. Above all, none should silently fall
        through to `[MutationKind.PRICE]` — the worst possible outcome,
        since PRICE maps to GMV, the metric family everything else has
        always been tested against, so the misclassification would hide."""
        payload = {
            "product_id": "tt-product-014",
            "price_update": None,
            "image_uri": "",
            "image_content_base64": "",
            "edit_body": {},
            "title": "",
            "description": "",
        }
        kinds = classify_mutation_kinds(payload)
        assert kinds == []
        assert kinds != [MutationKind.PRICE]

    def test_empty_price_update_dict_is_falsy_and_does_not_classify_as_price(self):
        """`price_update: {}` is a recognized key with a falsy value — an
        empty-dict "update" is a no-op, not a real price mutation."""
        kinds = classify_mutation_kinds({"product_id": "tt-product-015", "price_update": {}})
        assert kinds == []

    def test_non_dict_edit_body_is_tolerated_not_a_keyerror(self):
        """`edit_body` malformed as a non-dict (e.g. `None`, or the wrong
        type from a caller bug) is coerced to `{}` rather than raising."""
        kinds = classify_mutation_kinds({"product_id": "tt-product-016", "edit_body": None})
        assert kinds == []

    def test_category_id_only_edit_body_is_the_documented_no_op_example(self):
        """`classify_mutation_kinds`'s own docstring names this exact case
        ("a run that only touched `category_id`") as unclassifiable."""
        kinds = classify_mutation_kinds(
            {"product_id": "tt-product-017", "edit_body": {"category_id": "600002"}}
        )
        assert kinds == []


# ===========================================================================
# `rollup_metric_for`'s documented, deliberate simplification is pinned by a
# test that states the approximation (acceptance criterion 5).
# ===========================================================================


class TestRollupMetricForPinsTheDocumentedApproximation:
    def test_rollup_metric_for_uses_first_classified_kinds_primary(self):
        """Documented, deliberate simplification (issue #1044 body, restated
        in `rollup_metric_for`'s own docstring): the run-level rollup
        approximates the ActionCard's `expected_impact.metric` as the
        primary metric of the *first classified* mutation kind — price,
        appended first in `classify_mutation_kinds`'s fixed order — rather
        than joining `ToolExecution.approval_id` back to a real
        `ActionCard` row. This is a stated approximation, not a bug: a
        future ActionCard join would replace this function's body without
        changing its signature (see the docstring)."""
        kinds = classify_mutation_kinds(_REALISTIC_MULTI_MUTATION_PAYLOAD)
        rollup = rollup_metric_for(kinds)
        assert rollup.key == "gmv"  # METRIC_MAP[MutationKind.PRICE].primary
        assert kinds[0] == MutationKind.PRICE

    def test_single_mutation_rollup_matches_that_mutations_own_primary(self):
        """The common case `reading.py`'s own docstring names: "a
        single-mutation run's rollup is typically the same metric as that
        mutation's primary." (`reading.compute_run_readings`'s docstring)"""
        image_kinds = classify_mutation_kinds(_REALISTIC_IMAGE_URI_ONLY_PAYLOAD)
        assert rollup_metric_for(image_kinds).key == "ctr"

        seo_kinds = classify_mutation_kinds(_REALISTIC_TITLE_ONLY_PAYLOAD)
        assert rollup_metric_for(seo_kinds).key == "impressions"

    def test_rollup_picks_image_over_seo_by_append_order_not_by_any_ranking(self):
        """The approximation's sharpest edge: a run that touches BOTH image
        and title (no price) has no principled way, from this function
        alone, to prefer one metric over the other — it picks whichever
        kind `classify_mutation_kinds` appended first (image before SEO in
        the fixed order), which is an artifact of iteration order, not a
        judgment that image's `ctr` is more "primary" than SEO's
        `impressions` for this run. Pinned here so a future reader who
        changes the append order in `classify.py` sees this test explain
        what the old rollup choice was and why it was never meant to be
        load-bearing."""
        kinds = classify_mutation_kinds(_IMAGE_AND_TITLE_NO_PRICE_PAYLOAD)
        assert kinds == [MutationKind.IMAGE, MutationKind.SEO_KEYWORDS_TITLE]
        rollup = rollup_metric_for(kinds)
        assert rollup.key == "ctr"  # METRIC_MAP[MutationKind.IMAGE].primary
        assert rollup.key != "impressions"  # SEO's primary lost only to order

    def test_rollup_metric_for_requires_at_least_one_kind(self):
        """`rollup_metric_for` indexes `kinds[0]` with no guard of its own —
        by contract, the caller (`pipeline.py`) never calls it with an empty
        list (`if not mutations: skip` runs first). Pinned here so that
        contract stays visible at the unit level, not only in the caller."""
        with pytest.raises(IndexError):
            rollup_metric_for([])


# ===========================================================================
# Full classify -> pipeline -> control_pool -> confidence composition, for
# an IMAGE mutation and a SEO_KEYWORDS_TITLE mutation (acceptance criterion
# 4) — the two branches that had zero coverage anywhere before this file.
#
# Single reference point (architect lock): every date below derives from
# `REFERENCE_T` via `timedelta` — never `datetime.now()`.
# ===========================================================================

REFERENCE_T = date(2026, 3, 2)
_PRE_START = REFERENCE_T - timedelta(days=14)
_PRE_END = REFERENCE_T - timedelta(days=1)
_POST_START_FINAL = REFERENCE_T + timedelta(days=1)
_POST_END_FINAL = REFERENCE_T + timedelta(days=14)
_LONG_ACTIVE = REFERENCE_T - timedelta(days=60)  # comfortably >= 14 days active


def _split_series(
    field: str, start: date, end: date, first_half: Decimal, second_half: Decimal, **constant
) -> dict[date, RawDailyRecord]:
    """A daily series over `[start, end]` with real day-to-day variance (the
    first half of the range at one value, the second half at another) so
    Pearson correlation against it is non-degenerate — a flat/constant
    series would score every candidate's correlation at exactly 0.0 (see
    `control_pool.py`'s own degenerate-input handling) and force fallback,
    which would prove nothing about the full control-pool path."""
    days = (end - start).days + 1
    half = days // 2
    out: dict[date, RawDailyRecord] = {}
    for i in range(days):
        value = first_half if i < half else second_half
        kwargs = dict(constant)
        kwargs[field] = value
        out[start + timedelta(days=i)] = RawDailyRecord(**kwargs)
    return out


def _flat_series(
    field: str, start: date, end: date, value: Decimal, **constant
) -> dict[date, RawDailyRecord]:
    kwargs = dict(constant)
    kwargs[field] = value
    days = (end - start).days + 1
    return {start + timedelta(days=i): RawDailyRecord(**kwargs) for i in range(days)}


def _candidates(daily: dict[date, RawDailyRecord], count: int) -> list[ControlCandidate]:
    return [
        ControlCandidate(
            product_id=f"tt-sibling-{i}",
            daily=dict(daily),
            touched=False,
            first_active_date=_LONG_ACTIVE,
        )
        for i in range(count)
    ]


class TestClassifyComposesWithTheRealPipelineForImage:
    """`classify_mutation_kinds` -> `select_control_pool` ->
    `compute_metric_reading` -> `compute_confidence`, driven from a
    realistic `image_uri` payload — the `IMAGE` branch had zero coverage of
    any kind before this file (issue #1068 body)."""

    def test_image_mutation_end_to_end_reaches_cao_confidence(self):
        payload = {
            "product_id": "tt-product-201",
            "image_uri": "https://cdn.example/tt-product-201/hero.jpg",
        }
        kinds = classify_mutation_kinds(payload)
        assert kinds == [MutationKind.IMAGE]

        rollup_spec = rollup_metric_for(kinds)
        assert rollup_spec is METRIC_MAP[MutationKind.IMAGE].primary
        assert rollup_spec.key == "ctr"

        # Target: CTR rises from a pre-period mean of 0.05 to a post-period
        # 0.075, with comfortable pre-period impressions volume (900/day,
        # far above the impressions_ctr family's 50/day floor).
        target_daily = {
            **_split_series(
                "ctr",
                _PRE_START,
                _PRE_END,
                Decimal("0.045"),
                Decimal("0.055"),
                impressions=Decimal(900),
            ),
            **_flat_series(
                "ctr",
                _POST_START_FINAL,
                _POST_END_FINAL,
                Decimal("0.075"),
                impressions=Decimal(900),
            ),
        }
        # Three correlated siblings (their pre-period series is exactly half
        # the target's -- a positive affine transform, so Pearson
        # correlation is exactly 1.0), clearing the top-K=5/min-3 bar with
        # no fallback.
        sibling_daily = {
            **_split_series(
                "ctr",
                _PRE_START,
                _PRE_END,
                Decimal("0.0225"),
                Decimal("0.0275"),
                impressions=Decimal(900),
            ),
            **_flat_series(
                "ctr", _POST_START_FINAL, _POST_END_FINAL, Decimal("0.03"), impressions=Decimal(900)
            ),
        }
        candidates = _candidates(sibling_daily, count=3)

        control_result = select_control_pool(
            rollup_spec,
            target_daily,
            candidates,
            REFERENCE_T,
            "final",
            volume_floor_for(rollup_spec),
            volume_of=volume_indicator_for(rollup_spec),
        )
        assert control_result.used_fallback is False
        assert len(control_result.selected) == 3

        reading = compute_metric_reading(
            rollup_spec, target_daily, control_result.control_daily, REFERENCE_T, "final"
        )
        assert reading.status == "ok"
        assert reading.pre == Decimal("0.05")
        assert reading.post == Decimal("0.075")
        assert reading.growth == Decimal("1.2")
        assert reading.expected == Decimal("0.06")
        assert reading.incremental == Decimal("0.015")
        assert reading.impact_pct == Decimal("0.25")

        confidence = compute_confidence(rollup_spec, target_daily, control_result, reading)
        assert confidence.tier == "cao"
        assert confidence.used_fallback is False


class TestClassifyComposesWithTheRealPipelineForSeoKeywordsTitle:
    """Same composition, driven from a realistic `edit_body.title` payload —
    the `SEO_KEYWORDS_TITLE` branch had zero coverage of any kind before
    this file (issue #1068 body)."""

    def test_seo_keywords_title_mutation_end_to_end_reaches_cao_confidence(self):
        payload = {
            "product_id": "tt-product-202",
            "edit_body": {"title": "Áo thun cotton - Từ khóa SEO mới"},
        }
        kinds = classify_mutation_kinds(payload)
        assert kinds == [MutationKind.SEO_KEYWORDS_TITLE]

        rollup_spec = rollup_metric_for(kinds)
        assert rollup_spec is METRIC_MAP[MutationKind.SEO_KEYWORDS_TITLE].primary
        assert rollup_spec.key == "impressions"

        # Target: impressions rise from a pre-period mean of 1000/day to a
        # post-period 1500/day.
        target_daily = {
            **_split_series("impressions", _PRE_START, _PRE_END, Decimal(900), Decimal(1100)),
            **_flat_series("impressions", _POST_START_FINAL, _POST_END_FINAL, Decimal(1500)),
        }
        sibling_daily = {
            **_split_series("impressions", _PRE_START, _PRE_END, Decimal(450), Decimal(550)),
            **_flat_series("impressions", _POST_START_FINAL, _POST_END_FINAL, Decimal(600)),
        }
        candidates = _candidates(sibling_daily, count=3)

        control_result = select_control_pool(
            rollup_spec,
            target_daily,
            candidates,
            REFERENCE_T,
            "final",
            volume_floor_for(rollup_spec),
            volume_of=volume_indicator_for(rollup_spec),
        )
        assert control_result.used_fallback is False
        assert len(control_result.selected) == 3

        reading = compute_metric_reading(
            rollup_spec, target_daily, control_result.control_daily, REFERENCE_T, "final"
        )
        assert reading.status == "ok"
        assert reading.pre == Decimal(1000)
        assert reading.post == Decimal(1500)
        assert reading.growth == Decimal("1.2")
        assert reading.expected == Decimal(1200)
        assert reading.incremental == Decimal(300)
        assert reading.impact_pct == Decimal("0.25")

        confidence = compute_confidence(rollup_spec, target_daily, control_result, reading)
        assert confidence.tier == "cao"
        assert confidence.used_fallback is False

        # `resolve_metric` round-trips the same spec `rollup_metric_for`
        # picked -- proving the classify -> metric_map seam is consistent,
        # not merely two independent lookups that happen to agree here.
        assert resolve_metric("impressions") is rollup_spec
