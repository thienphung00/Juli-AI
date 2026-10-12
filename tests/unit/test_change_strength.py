"""D31.7 change strength: the backend helper on the table the demo app also tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from juli_backend.services import change_strength as cs

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads(
    (ROOT / "apps/demo/src/lib/__tests__/fixtures/change-strength-cases.json").read_text(
        encoding="utf-8"
    )
)["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_shared_table(case):
    assert cs.change_strength(case["change"], case["a"], case["b"]) == case["expected"]


def test_combined_band_is_the_hypotenuse():
    assert cs.combined_band(6, 8) == pytest.approx(10)
    assert cs.combined_band(None, 8) is None
    assert cs.combined_band(6, float("nan")) is None


def test_labels_match_the_demo_copy():
    source = (ROOT / "apps/demo/src/lib/change-strength.ts").read_text(encoding="utf-8")
    for key, label in cs.STRENGTH_LABELS_VI.items():
        assert f'{key}: "{label}"' in source
    assert cs.STRENGTH_LABELS_VI == {
        "clear": "Thay đổi rõ",
        "likely": "Có thể thay đổi",
        "noise": "Trong dao động",
    }
