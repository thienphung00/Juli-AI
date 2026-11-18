"""F1.5 (batch-1118f): the kinds the UI treats as fillable (``FILLABLE_CHANGE_KINDS`` in the demo's
model.ts) are exactly the kinds the fill queue can queue (``fill_queue._KIND_OF``)."""

from __future__ import annotations

import re
from pathlib import Path

from juli_backend.services.shopee_recommendations import fill_queue

MODEL_TS = Path(__file__).resolve().parents[2] / "apps/demo/src/lib/shopee-decisions/model.ts"


def test_fillable_change_kinds_equal_the_fill_queue_kinds():
    text = MODEL_TS.read_text(encoding="utf-8")
    assert "FILLABLE_CHANGE_KINDS" in text, "FILLABLE_CHANGE_KINDS not found in model.ts"
    # the array literal after "=" (the type annotation `readonly string[]` has brackets too)
    match = re.search(r"FILLABLE_CHANGE_KINDS[^=]*=\s*\[(.*?)\]", text, re.S)
    assert match, "FILLABLE_CHANGE_KINDS has no array literal"
    parsed = set(re.findall(r'"([a-z_]+)"', match.group(1)))
    assert parsed, "FILLABLE_CHANGE_KINDS has no kinds"
    assert parsed == set(fill_queue._KIND_OF.keys())
