"""Traffic-source check — ADR-106 amendment 4 (2026-10-07).

A product's CTR can fall because a campaign, LIVE or affiliate video poured
low-intent impressions onto it; fixing the listing is then the wrong move. This
module reads the six channel blocks of the A-34 rows (current and previous
30 days) and returns one verdict per product:

* ``UNIFORM`` ("đồng loạt"): CTR fell in at least two thirds of the qualifying
  channels (and there are at least two) — a common cause, cover / price / title
  cards stand;
* ``DILUTION`` ("loãng traffic"): every channel whose CTR fell is a spiking
  channel and every other qualifying channel's CTR is stable — the fall is
  dilution, a CTR-triggered card is not emitted;
* ``UNCLEAR`` ("không rõ"): anything else, including fewer than two qualifying
  channels — the card stands and the report says the check was inconclusive.

Pure. Thresholds live in :class:`StageDiagnosisConfig`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from juli_backend.services.optimize_product.config import StageDiagnosisConfig
from juli_backend.services.optimize_product.funnel import ZERO, to_decimal

UNIFORM = "đồng loạt"
DILUTION = "loãng traffic"
UNCLEAR = "không rõ"

#: key, label, A-34 block, impressions field, clicks field.
CHANNELS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "card",
        "Thẻ sản phẩm",
        "seller_product_card_performance",
        "product_impressions",
        "product_clicks",
    ),
    (
        "shop_tab",
        "Shop Tab",
        "shop_tab_performance",
        "shop_tab_product_impressions",
        "shop_tab_product_clicks",
    ),
    (
        "seller_video",
        "Video của shop",
        "seller_video_performance",
        "product_impressions",
        "product_clicks",
    ),
    (
        "seller_live",
        "LIVE của shop",
        "seller_live_performance",
        "product_impressions",
        "product_clicks",
    ),
    (
        "affiliate_video",
        "Video affiliate",
        "affiliate_video_performance",
        "product_impressions",
        "product_clicks",
    ),
    (
        "affiliate_live",
        "LIVE affiliate",
        "affiliate_live_performance",
        "product_impressions",
        "product_clicks",
    ),
)


def phrase(label: str) -> str:
    """A channel label inside a sentence: lower-case first letter unless it is a proper noun."""
    return label if label.startswith(("LIVE", "Shop")) else label[0].lower() + label[1:]


@dataclass(frozen=True)
class ChannelDelta:
    key: str
    label: str
    impressions_previous: Decimal
    impressions_current: Decimal
    impressions_per_day_previous: Decimal
    impressions_per_day_current: Decimal
    ctr_previous: Decimal | None
    ctr_current: Decimal | None
    #: Impressions reach the floor in both windows.
    qualifies: bool
    #: Impressions per day, current over previous, at least the spike ratio.
    spiking: bool
    #: Relative CTR change (current - previous) / previous; ``None`` without both CTRs.
    ctr_change: Decimal | None
    ctr_dropped: bool
    ctr_stable: bool

    @property
    def increase_per_day(self) -> Decimal:
        return self.impressions_per_day_current - self.impressions_per_day_previous

    @property
    def shown(self) -> bool:
        return self.impressions_previous > 0 or self.impressions_current > 0


@dataclass(frozen=True)
class TrafficAttribution:
    product_id: str
    verdict: str
    channels: list[ChannelDelta]
    #: Channel label with the largest absolute impressions/day increase; ``""`` when none grew.
    top_impression_source: str
    #: Labels of the channels that both spiked and lost CTR (the dilution culprits).
    diluting_channels: tuple[str, ...] = ()

    @property
    def top_channel(self) -> ChannelDelta | None:
        return next((c for c in self.channels if c.label == self.top_impression_source), None)


def _block(item: dict | None, name: str) -> dict:
    value = (item or {}).get(name)
    return value if isinstance(value, dict) else {}


def _counts(item: dict | None, channel: tuple[str, str, str, str, str]) -> tuple[Decimal, Decimal]:
    block = _block(item, channel[2])
    return to_decimal(block.get(channel[3])), to_decimal(block.get(channel[4]))


def _channel_delta(
    channel: tuple[str, str, str, str, str],
    current: dict | None,
    previous: dict | None,
    config: StageDiagnosisConfig,
    days_current: int,
    days_previous: int,
) -> ChannelDelta:
    imp_cur, clk_cur = _counts(current, channel)
    imp_prev, clk_prev = _counts(previous, channel)
    per_cur = imp_cur / Decimal(days_current)
    per_prev = imp_prev / Decimal(days_previous)
    floor = Decimal(config.traffic_min_channel_impressions)
    qualifies = imp_cur >= floor and imp_prev >= floor
    ctr_cur = clk_cur / imp_cur if imp_cur > 0 else None
    ctr_prev = clk_prev / imp_prev if imp_prev > 0 else None
    change = (
        (ctr_cur - ctr_prev) / ctr_prev
        if ctr_cur is not None and ctr_prev is not None and ctr_prev > 0
        else None
    )
    return ChannelDelta(
        key=channel[0],
        label=channel[1],
        impressions_previous=imp_prev,
        impressions_current=imp_cur,
        impressions_per_day_previous=per_prev,
        impressions_per_day_current=per_cur,
        ctr_previous=ctr_prev,
        ctr_current=ctr_cur,
        qualifies=qualifies,
        spiking=per_prev > 0 and per_cur / per_prev >= config.traffic_spike_ratio,
        ctr_change=change,
        ctr_dropped=change is not None and -change >= config.traffic_ctr_drop,
        ctr_stable=change is not None and abs(change) <= config.traffic_ctr_stable,
    )


def attribute_traffic(
    product_id: str,
    current: dict | None,
    previous: dict | None,
    config: StageDiagnosisConfig,
    *,
    days_current: int = 30,
    days_previous: int = 30,
) -> TrafficAttribution:
    """Verdict and per-channel deltas from two A-34 rows (current vs previous window)."""
    channels = [
        _channel_delta(c, current, previous, config, days_current, days_previous) for c in CHANNELS
    ]
    qualifying = [c for c in channels if c.qualifies]
    grown = max(channels, key=lambda c: c.increase_per_day)
    top = grown.label if grown.increase_per_day > ZERO else ""
    dropped = [c for c in qualifying if c.ctr_dropped]
    verdict = UNCLEAR
    diluting: tuple[str, ...] = ()
    if len(qualifying) >= 2:
        if len(dropped) * 3 >= len(qualifying) * 2:
            verdict = UNIFORM
        elif (
            dropped
            and all(c.spiking for c in dropped)
            and all(c.ctr_stable for c in qualifying if not c.spiking)
        ):
            verdict = DILUTION
            diluting = tuple(
                c.label for c in sorted(dropped, key=lambda c: c.increase_per_day, reverse=True)
            )
    return TrafficAttribution(product_id, verdict, channels, top, diluting)


def dilution_reason(attribution: TrafficAttribution) -> str:
    """The watch-list reason for a diluted CTR drop."""
    sources = " và ".join(phrase(label) for label in attribution.diluting_channels)
    return f"CTR giảm do lượt hiển thị tăng mạnh từ {sources}, không phải do trang sản phẩm"


def source_clause(attribution: TrafficAttribution) -> str | None:
    """Short reason clause when the biggest impression gain came from a spiking channel."""
    top = attribution.top_channel
    if top is None or not top.spiking:
        return None
    return f"lượt hiển thị tăng chủ yếu từ {phrase(top.label)}"
