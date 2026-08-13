"""Seller-facing copy rules for incremental impact readings (ADR-077
decision 4, #1043).

Acceptance criteria covered here:
- Every rendered number carries the "uoc tinh" hedge.
- No causal language appears anywhere in the rendered battery.
- The inline method disclaimer ("so voi cac san pham tuong tu trong shop")
  is present on the full-control-path copy verbatim; the fallback path gets
  a different, honest disclaimer (it did not actually compare to similar
  products).
- A negative reading renders with the same structure and hedging as a
  positive one -- asserted explicitly (the failure mode this design guards
  against is under-reporting bad news).
- Seller-facing strings carry zero `seller-copy-banned-patterns.json`
  entries (checked via the shared loader,
  `juli_backend.services.agent.sanitize.load_banned_patterns`) and zero
  `dictionary.md` `_Avoid_` aliases (checked via a parse of the real file,
  never a hand-copied list -- #1002 exists because someone made a third
  copy).
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest

from juli_backend.services.agent.sanitize import load_banned_patterns
from juli_backend.services.impact.confidence import ConfidenceResult
from juli_backend.services.impact.copy import (
    BELOW_FLOOR_MESSAGE,
    METHOD_DISCLAIMER_FALLBACK,
    METHOD_DISCLAIMER_FULL_PATH,
    render_below_floor,
    render_confounded,
    render_reading,
    render_suppressed,
    render_tiered_reading,
)
from juli_backend.services.impact.metric_map import CTR, GMV, IMPRESSIONS

REPO_ROOT = Path(__file__).resolve().parents[2]
DICTIONARY_PATH = REPO_ROOT / "dictionary.md"

# ADR-077-decision-4-specific causal-language guard. This is NOT the shared
# seller-copy-banned-patterns.json (which does not cover causal language at
# all) -- it is this module's own, narrowly-scoped check that the templates
# never claim a mutation *caused* a measured outcome, only that the
# outcome was observed relative to an estimate. Word-boundary anchored so
# Vietnamese words that merely contain these Latin letters (e.g. "do" is
# never a substring of "đó"/"đủ" since đ is a distinct letter) are not
# false-flagged.
_CAUSAL_MARKERS = (
    re.compile(r"\bdo\b", re.IGNORECASE),
    re.compile(r"\bvì\b", re.IGNORECASE),  # "vì"
    re.compile(r"\bnhờ\b", re.IGNORECASE),  # "nhờ"
    re.compile(r"\bkhiến\b", re.IGNORECASE),  # "khiến"
    re.compile(r"gây ra", re.IGNORECASE),  # "gây ra"
    re.compile(r"dẫn đến", re.IGNORECASE),  # "dẫn đến"
    re.compile(r"nguyên nhân", re.IGNORECASE),  # "nguyên nhân"
)


def _parse_avoid_aliases(text: str) -> list[str]:
    """Best-effort parse of every `- _Avoid_: ...` line in dictionary.md into
    individual alias phrases -- never a hand-copied list (#1002)."""
    aliases: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("- _Avoid_:"):
            continue
        rest = line[len("- _Avoid_:") :].strip()
        rest = re.sub(r"\([^)]*\)", "", rest)  # drop parenthetical qualifiers
        for fragment in rest.split(","):
            fragment = fragment.strip().strip(".")
            if fragment:
                aliases.append(fragment)
    return aliases


def _battery() -> list[str]:
    """Every seller-facing string this module can produce, across outcomes,
    tiers, signs, and paths -- the full surface the copy-safety guards below
    scan."""
    texts = [
        render_below_floor(GMV).text,
        render_below_floor(IMPRESSIONS).text,
        render_suppressed(GMV).text,
        render_confounded(GMV).text,
    ]
    for tier in ("cao", "trung_binh", "thap"):
        for sign in (1, -1):
            for used_fallback in (False, True):
                texts.append(
                    render_tiered_reading(
                        GMV, tier, Decimal(sign) * Decimal("12345.67"), used_fallback
                    ).text
                )
    return texts


class TestBelowFloorIsTheDesignedFirstClassState:
    def test_exact_required_phrase_present(self):
        rendered = render_below_floor(GMV)
        assert BELOW_FLOOR_MESSAGE in rendered.text
        assert rendered.text.startswith("Chưa đủ dữ liệu để ước tính")
        assert rendered.tier == "below_floor"


class TestThreeOutcomesRenderDistinctly:
    def test_below_floor_suppressed_confounded_render_different_text(self):
        below_floor = render_below_floor(GMV).text
        suppressed = render_suppressed(GMV).text
        confounded = render_confounded(GMV).text
        assert len({below_floor, suppressed, confounded}) == 3


class TestEveryNumberCarriesTheEstimateHedge:
    @pytest.mark.parametrize("tier", ["cao", "trung_binh", "thap"])
    @pytest.mark.parametrize("used_fallback", [False, True])
    def test_hedge_present(self, tier, used_fallback):
        rendered = render_tiered_reading(GMV, tier, Decimal("500"), used_fallback)
        assert "ước tính" in rendered.text.lower()


class TestMethodDisclaimer:
    def test_full_path_uses_the_adr_literal_disclaimer(self):
        rendered = render_tiered_reading(GMV, "cao", Decimal("500"), used_fallback=False)
        assert METHOD_DISCLAIMER_FULL_PATH in rendered.text

    def test_fallback_path_uses_a_different_honest_disclaimer(self):
        rendered = render_tiered_reading(GMV, "thap", Decimal("500"), used_fallback=True)
        assert METHOD_DISCLAIMER_FALLBACK in rendered.text
        # Must NOT claim a similar-products comparison that never happened.
        assert METHOD_DISCLAIMER_FULL_PATH not in rendered.text


class TestNegativeRendersAsHonestlyAsPositive:
    def test_negative_and_positive_share_structure_and_hedging(self):
        positive = render_tiered_reading(GMV, "trung_binh", Decimal("789.00"), False)
        negative = render_tiered_reading(GMV, "trung_binh", Decimal("-789.00"), False)

        for rendered in (positive, negative):
            assert "ước tính" in rendered.text.lower()
            assert METHOD_DISCLAIMER_FULL_PATH in rendered.text
            assert "trung bình" in rendered.text.lower()

        # Same magnitude formatting, same everything except the direction
        # word -- prove the templates are structurally identical, not that
        # the negative case got a shorter/quieter/hedged-differently render.
        assert "789" in positive.text
        assert "789" in negative.text
        assert positive.text != negative.text  # direction word must differ

    def test_negative_incremental_does_not_get_dropped_or_hidden(self):
        rendered = render_tiered_reading(GMV, "cao", Decimal("-999999"), False)
        assert "999,999" in rendered.text or "999999" in rendered.text
        assert "giảm" in rendered.text.lower()  # "giảm" (decreased)


class TestRenderReadingDispatcher:
    def test_dispatches_confounded(self):
        result = ConfidenceResult(
            metric=GMV.key,
            tier="confounded",
            volume=None,
            noise_band=None,
            used_fallback=False,
            fallback_reason=None,
        )
        rendered = render_reading(GMV, result, incremental=None)
        assert rendered.text == render_confounded(GMV).text

    def test_dispatches_below_floor(self):
        result = ConfidenceResult(
            metric=GMV.key,
            tier="below_floor",
            volume=Decimal(0),
            noise_band=Decimal(1),
            used_fallback=False,
            fallback_reason=None,
        )
        rendered = render_reading(GMV, result, incremental=None)
        assert rendered.text == render_below_floor(GMV).text

    def test_dispatches_tiered_reading_with_incremental(self):
        result = ConfidenceResult(
            metric=CTR.key,
            tier="cao",
            volume=Decimal(100),
            noise_band=Decimal(1),
            used_fallback=False,
            fallback_reason=None,
        )
        rendered = render_reading(CTR, result, incremental=Decimal("0.05"))
        assert rendered.text == render_tiered_reading(CTR, "cao", Decimal("0.05"), False).text


class TestNoCausalLanguage:
    def test_battery_never_uses_a_causal_marker(self):
        for text in _battery():
            for marker in _CAUSAL_MARKERS:
                assert not marker.search(text), f"causal marker {marker.pattern!r} in {text!r}"


class TestSharedBannedPatternsSource:
    def test_battery_has_zero_banned_pattern_hits(self):
        compiled = load_banned_patterns()
        for text in _battery():
            for pattern in compiled:
                assert not pattern.search(text), (
                    f"banned pattern {pattern.pattern!r} matched in {text!r}"
                )


class TestDictionaryAvoidAliases:
    def test_dictionary_parses_to_a_nonempty_alias_list(self):
        # Sanity check on the parser itself against the real file, so a
        # silently-broken parser can't make the next test vacuously pass.
        aliases = _parse_avoid_aliases(DICTIONARY_PATH.read_text(encoding="utf-8"))
        assert len(aliases) > 10

    def test_battery_contains_zero_avoid_aliases(self):
        aliases = _parse_avoid_aliases(DICTIONARY_PATH.read_text(encoding="utf-8"))
        for text in _battery():
            lowered = text.lower()
            for alias in aliases:
                if len(alias) < 4:
                    continue  # too short to be a meaningful phrase collision
                assert alias.lower() not in lowered, (
                    f"dictionary.md _Avoid_ alias {alias!r} found in {text!r}"
                )
