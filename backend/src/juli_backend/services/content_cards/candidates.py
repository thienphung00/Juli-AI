"""Content card candidates from the stored metric rankings — rules only, no model (D24.1).

Input: the ADR-109 d.5 tables the daily diagnosis job stores
(``shop_metric_rankings``), one per stream × metric. A content row (a video, a
LIVE session) is measured against the stream's prior-window rate
(``stream_prior``), so a row below it is a row whose CTR / CTOR fell:

- **Video** (``seller_video`` × ``ctr``): a product whose videos' CTR is below
  the stream's prior CTR, with at least :data:`MIN_VIDEO_IMPRESSIONS` product
  impressions on those videos in the last 30 days → card "Kịch bản video mới".
- **LIVE** (``seller_live`` × ``ctor``): a product sold in LIVE sessions whose
  CTOR is below the LIVE stream's prior CTOR, with at least
  :data:`MIN_LIVE_CLICKS` product clicks → card "Kịch bản host + thứ tự giỏ".

Only rows the ranking *listed* are used (``down`` / ``up``): they passed the
ranking's own confidence floor on the metric's quantity (clicks for CTR, SKU
orders for CTOR). A row's window totals are recovered from its rate and its
quantity: impressions = clicks ÷ CTR, clicks = orders ÷ CTOR.

**Expected GMV** is D22's recoverable GMV in the ranking's own terms: a row's
``gmv_per_day`` is already impressions/day × (row CTR − prior CTR) × prior CTOR ×
prior AOV (video) or clicks/day × (row CTOR − prior CTOR) × prior AOV (LIVE), so
the loss is ``−gmv_per_day``. A row featuring several products shares its loss
equally among them (the ranking has no per-product split). Pure: the emitter
reads the rows and the catalogue and writes the cards.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from juli_backend.services.content_cards.constants import (
    LIVE,
    LIVE_SPEC,
    VIDEO,
    VIDEO_SPEC,
    ContentKind,
    KindSpec,
)

#: "Enough impressions" for a video CTR card: the product's falling videos
#: together, last 30 days (the ranking's own impressions floor per window).
MIN_VIDEO_IMPRESSIONS = 1_000
#: "Enough clicks" for a LIVE CTOR card: the product's falling sessions together.
MIN_LIVE_CLICKS = 100
#: Rows quoted in the card's evidence.
MAX_EVIDENCE_ROWS = 3


@dataclass(frozen=True)
class EvidenceRow:
    """One video / LIVE session behind a candidate."""

    row_id: str
    name: str
    day: str | None
    rate: float
    volume: float  # impressions (video) or clicks (LIVE), window total
    loss_per_day: float  # this product's share, VND/day, ≥ 0

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.row_id,
            "name": self.name,
            "date": self.day,
            "rate": self.rate,
            "volume": self.volume,
            "loss_per_day": round(self.loss_per_day, 2),
        }


@dataclass(frozen=True)
class ContentCandidate:
    """One proposed content card (before cooldown / catalogue / weekly checks)."""

    kind: ContentKind
    tiktok_product_id: str
    current: float
    target: float
    recoverable_gmv_per_day: float
    volume: float  # Σ impressions (video) / Σ clicks (LIVE)
    rows: tuple[EvidenceRow, ...] = field(default_factory=tuple)
    as_of: str | None = None

    @property
    def spec(self) -> KindSpec:
        return VIDEO_SPEC if self.kind == VIDEO else LIVE_SPEC


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _rows(payload: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    for side in ("down", "up"):
        rows = payload.get(side)
        if isinstance(rows, list):
            yield from (r for r in rows if isinstance(r, Mapping))


def _volume(rate: float, quantity: float | None) -> float | None:
    """impressions = clicks ÷ CTR (video); clicks = orders ÷ CTOR (LIVE)."""
    if quantity is None or rate <= 0:
        return None
    return quantity / rate


def _as_of(payload: Mapping[str, Any]) -> str | None:
    windows = payload.get("windows")
    last = windows.get("last") if isinstance(windows, Mapping) else None
    return str(last[1]) if isinstance(last, list) and len(last) == 2 else None


def candidates_from_ranking(
    payload: Mapping[str, Any] | None,
    kind: ContentKind,
    *,
    min_volume: float | None = None,
) -> list[ContentCandidate]:
    """Content candidates of one kind from one stored ranking table, best first.

    ``payload`` is the ``shop_metric_rankings.ranking`` JSON of
    ``seller_video × ctr`` (video) or ``seller_live × ctor`` (LIVE). A missing
    or malformed table yields nothing — never a guessed card.
    """
    if not isinstance(payload, Mapping):
        return []
    spec = VIDEO_SPEC if kind == VIDEO else LIVE_SPEC
    if payload.get("stream") not in (None, spec.stream) or payload.get("metric") not in (
        None,
        spec.metric,
    ):
        return []
    reference = _num(payload.get("stream_prior"))
    if reference is None or reference <= 0:
        return []
    floor = (
        min_volume
        if min_volume is not None
        else MIN_VIDEO_IMPRESSIONS
        if kind == VIDEO
        else MIN_LIVE_CLICKS
    )
    per_product: dict[str, list[EvidenceRow]] = defaultdict(list)
    for row in _rows(payload):
        rate = _num(row.get("last"))
        gmv = _num(row.get("gmv_per_day"))
        products = [str(p) for p in row.get("product_ids") or [] if p]
        if rate is None or gmv is None or not products or rate >= reference or gmv >= 0:
            continue
        volume = _volume(rate, _num(row.get("quantity_last")))
        if volume is None:
            continue
        share = -gmv / len(products)
        for product_id in dict.fromkeys(products):
            per_product[product_id].append(
                EvidenceRow(
                    row_id=str(row.get("id") or ""),
                    name=str(row.get("name") or ""),
                    day=str(row["date"]) if row.get("date") else None,
                    rate=rate,
                    volume=volume,
                    loss_per_day=share,
                )
            )
    as_of = _as_of(payload)
    out: list[ContentCandidate] = []
    for product_id, rows in per_product.items():
        volume = sum(r.volume for r in rows)
        if volume < floor:
            continue
        hits = sum(r.rate * r.volume for r in rows)  # clicks (video) / orders (LIVE)
        current = hits / volume
        if current >= reference:
            continue
        rows_sorted = sorted(rows, key=lambda r: (-r.volume, r.row_id))
        out.append(
            ContentCandidate(
                kind=kind,
                tiktok_product_id=product_id,
                current=current,
                target=reference,
                recoverable_gmv_per_day=sum(r.loss_per_day for r in rows),
                volume=volume,
                rows=tuple(rows_sorted[:MAX_EVIDENCE_ROWS]),
                as_of=as_of,
            )
        )
    out.sort(key=lambda c: (-c.recoverable_gmv_per_day, c.tiktok_product_id))
    return out


def product_rate(payload: Mapping[str, Any] | None, tiktok_product_id: str) -> float | None:
    """The product's current rate in a ranking table (all its listed rows), or ``None``.

    Used to withdraw an open card whose metric is already at target.
    """
    if not isinstance(payload, Mapping):
        return None
    volume = hits = 0.0
    for row in _rows(payload):
        if tiktok_product_id not in {str(p) for p in row.get("product_ids") or []}:
            continue
        rate = _num(row.get("last"))
        if rate is None:
            continue
        v = _volume(rate, _num(row.get("quantity_last")))
        if v is None:
            continue
        volume += v
        hits += rate * v
    return hits / volume if volume > 0 else None


def merge_ranked(
    video: Sequence[ContentCandidate],
    live: Sequence[ContentCandidate],
    *,
    weights: Mapping[str, float] | None = None,
) -> list[ContentCandidate]:
    """Both kinds in one list, best priority first (stable on product id).

    Priority = expected GMV × the lever's history weight (calibration factor ×
    seller-reason penalty, D24.6), the content cards' own ranking for their
    daily slot (D24.21 (4)). ``weights``: lever code -> weight; absent = 1.
    """

    def priority(c: ContentCandidate) -> float:
        return c.recoverable_gmv_per_day * (weights or {}).get(c.spec.lever_code, 1.0)

    return sorted(
        [*video, *live],
        key=lambda c: (-priority(c), c.kind, c.tiktok_product_id),
    )


__all__ = [
    "LIVE",
    "MAX_EVIDENCE_ROWS",
    "MIN_LIVE_CLICKS",
    "MIN_VIDEO_IMPRESSIONS",
    "VIDEO",
    "ContentCandidate",
    "EvidenceRow",
    "candidates_from_ranking",
    "merge_ranked",
    "product_rate",
]
