"""P100 S2-E: the Ảnh bìa banner rules (``services/shopee_builder/banner.py``).

``tests/fixtures/banner_cases.json`` is shared with the TypeScript editor
(``apps/demo/src/lib/shopee-decisions/__tests__/banner.test.ts``): the same display text, the
same rule checks and the same refused specs on both sides.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from juli_backend.services.shopee_builder import banner as bn

CASES: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "banner_cases.json").read_text("utf-8")
)


@pytest.mark.parametrize("case", CASES["text"], ids=lambda c: f"{c['kind']}:{c['values']}")
def test_the_display_text_comes_from_the_raw_values(case: dict[str, Any]) -> None:
    assert bn.text(case["kind"], case["values"]) == (case["head"], case["sub"])


@pytest.mark.parametrize("case", CASES["checks"], ids=lambda c: c["name"])
def test_the_rule_checks_are_the_designs_step_4(case: dict[str, Any]) -> None:
    spec = bn.BannerSpec.model_validate(case["spec"])
    got = [{"code": c.code, "banner": c.banner, "title": c.title} for c in bn.rule_checks(spec)]
    assert got == case["checks"]


@pytest.mark.parametrize("case", CASES["invalid"], ids=lambda c: c["name"])
def test_a_spec_outside_the_shapes_and_limits_is_refused(case: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        bn.BannerSpec.model_validate(case["spec"])


def test_every_kind_has_a_shape_with_positions_and_bottom_left_is_never_one() -> None:
    assert set(bn.SHAPES) == {"ngang", "goc", "the"}
    assert all("bottom_left" not in p for p in bn.SHAPES.values())
    for kind in bn.KINDS.values():
        assert kind.shape in bn.SHAPES and kind.fields
        assert kind.kind in bn.KIND_TITLE
    assert [k for k, v in bn.KINDS.items() if v.mega_only] == ["mega"]


def test_the_stored_spec_carries_its_checks() -> None:
    overlap = next(c for c in CASES["checks"] if c["name"] == "overlap_with_free_slot")
    spec = bn.with_checks(bn.BannerSpec.model_validate(overlap["spec"]))
    assert [c.code for c in spec.checks] == ["overlap"]
    assert spec.checks[0].fix == "Chuyển Combo sang Dưới phải."


def test_the_colours_come_from_the_style_profile_else_the_default() -> None:
    assert bn.palette_of(None) == bn.DEFAULT_PALETTE
    assert bn.palette_of({"palette": ["#2f6b4f", "#E07A3F", "nope"]}) == ("#2F6B4F", "#E07A3F")
    spec = bn.BannerSpec.model_validate(
        {
            "template": "toi_gian",
            "day_mode": "ngay_thuong",
            "banners": [
                {
                    "shape": "goc",
                    "kind": "pct",
                    "values": {"pct": 10},
                    "position": "top_left",
                    "colour": "#123456",
                },
                {
                    "shape": "the",
                    "kind": "quy_cach",
                    "values": {"text": "500ml"},
                    "position": "bottom_right",
                    "colour": "#2f6b4f",
                },
            ],
        }
    )
    assert bn.off_palette(spec, ("#2F6B4F",)) == [0]
    assert bn.summary(spec) == "−10%; 500ml"


def test_a_cover_change_takes_a_banner_or_an_overlay() -> None:
    from juli_backend.services.shopee_builder.specs import CoverSpec

    clean = next(c for c in CASES["checks"] if c["name"] == "clean")["spec"]
    made = CoverSpec.model_validate({"kind": "cover_image", "item_id": "1001", "banner": clean})
    assert made.banner is not None and made.overlay is None
    with pytest.raises(ValidationError):
        CoverSpec.model_validate({"kind": "cover_image", "item_id": "1001"})
    with pytest.raises(ValidationError):
        CoverSpec.model_validate(
            {"kind": "cover_image", "item_id": "1001", "banner": {**clean, "banners": []}}
        )
    old = CoverSpec.model_validate(
        {"kind": "cover_image", "item_id": "1001", "overlay": {"layout": "corner_tag"}}
    )
    assert old.overlay is not None and old.banner is None
