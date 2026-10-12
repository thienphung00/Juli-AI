"""Change strength (D31.7): how sure a change between two windows is not noise. Pure.

A change between two window means is compared with the COMBINED band of both
windows, ``√(a² + b²)``, where ``a`` and ``b`` are each window's window-mean band
(D28.1: ``1.2816 × stdev(daily) / √n / mean``, in ± % of the mean). Daily values
are not independent (weekday effect, runs), so that band is optimistic; one
shared rule grades every comparison:

- ``|change| ≥ 2 × combined`` → ``clear`` ("Thay đổi rõ");
- ``|change| ≥ 1 × combined`` → ``likely`` ("Có thể thay đổi");
- otherwise (and always for a zero change) → ``noise`` ("Trong dao động");
- a missing change or band → ``None`` (nothing is shown).

"Not random" is not "caused by Juli": a day-14 result still needs no overlapping
external change and holding guard metrics (D29/D30). The demo app mirrors this
in ``apps/demo/src/lib/change-strength.ts``; both are tested on the same table
(``apps/demo/src/lib/__tests__/fixtures/change-strength-cases.json``).
"""

from __future__ import annotations

import math
from collections.abc import Mapping

STRENGTH_CLEAR = "clear"
STRENGTH_LIKELY = "likely"
STRENGTH_NOISE = "noise"

STRENGTH_LABELS_VI: Mapping[str, str] = {
    STRENGTH_CLEAR: "Thay đổi rõ",
    STRENGTH_LIKELY: "Có thể thay đổi",
    STRENGTH_NOISE: "Trong dao động",
}

#: ``|change| ≥ CLEAR_MULT × combined`` is "clear"; ``≥ LIKELY_MULT ×`` is "likely".
CLEAR_MULT = 2.0
LIKELY_MULT = 1.0


def _finite(value: float | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def combined_band(band_a_pct: float | None, band_b_pct: float | None) -> float | None:
    """``√(a² + b²)`` of two windows' bands (± % of the mean); None if either is missing."""
    a, b = _finite(band_a_pct), _finite(band_b_pct)
    if a is None or b is None:
        return None
    return math.hypot(a, b)


def change_strength(
    change_pct: float | None, band_a_pct: float | None, band_b_pct: float | None
) -> str | None:
    """``clear`` / ``likely`` / ``noise`` for ``change_pct`` against both windows' bands."""
    change = _finite(change_pct)
    combined = combined_band(band_a_pct, band_b_pct)
    if change is None or combined is None:
        return None
    size = abs(change)
    if size == 0:
        # No change is never "clear", even against a flat (zero-band) series.
        return STRENGTH_NOISE
    if size >= CLEAR_MULT * combined:
        return STRENGTH_CLEAR
    if size >= LIKELY_MULT * combined:
        return STRENGTH_LIKELY
    return STRENGTH_NOISE


__all__ = [
    "CLEAR_MULT",
    "LIKELY_MULT",
    "STRENGTH_CLEAR",
    "STRENGTH_LABELS_VI",
    "STRENGTH_LIKELY",
    "STRENGTH_NOISE",
    "change_strength",
    "combined_band",
]
