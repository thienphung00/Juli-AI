"""Assemble the shop diagnosis report from a snapshot — ADR-108 decisions 1–11.

One :class:`ShopDiagnosis` holds every number; the HTML page
(:mod:`~juli_backend.services.shop_diagnosis.render`), the JSON dump and the
seller message (:mod:`~juli_backend.services.shop_diagnosis.message`) are all
rendered from it, so the three cannot disagree (d.1).
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any

from juli_backend.services.optimize_product.live_video import Appearance, parse_appearances
from juli_backend.services.shop_diagnosis.channels import (
    ADDITIVE,
    AFFILIATE_SUB_ROWS,
    CONTENT,
    FIVE_CHANNELS,
    SELF_SEARCH,
    Channel,
    Counts,
    Series,
    build_series,
    daily_values,
    group_sum,
)
from juli_backend.services.shop_diagnosis.confidence import Confidence
from juli_backend.services.shop_diagnosis.config import ShopDiagnosisConfig
from juli_backend.services.shop_diagnosis.decomposition import (
    Conclusion,
    FunnelComparison,
    compare,
    decide,
)
from juli_backend.services.shop_diagnosis.heroes import (
    ENTERED,
    HeroSelection,
    Ranking,
    select_heroes,
)
from juli_backend.services.shop_diagnosis.promotions import (
    Band,
    FlashAnalysis,
    OrderDiscountShare,
    VoucherSummary,
    analyse_flash,
    analyse_vouchers,
    bands,
    order_discount_share,
    parse_activities,
    parse_vouchers,
)
from juli_backend.services.shop_diagnosis.snapshot import Snapshot, Windows
from juli_backend.services.shop_diagnosis.timeline import (
    ChannelTimeline,
    build_timelines,
    sale_days,
)


@dataclass(frozen=True)
class ChannelRow:
    channel: Channel
    comparison: FunnelComparison
    #: This channel's GMV change ÷ the shop's GMV change.
    share_of_change: float | None
    #: ``False`` for Shop Tab, which overlaps the other channels.
    additive: bool
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class GroupRow:
    label: str
    channels: tuple[Channel, ...]
    comparison: FunnelComparison
    share_of_change: float | None


@dataclass(frozen=True)
class Appearances:
    top_live: tuple[Appearance, ...]
    live_without_orders: int
    top_videos: tuple[Appearance, ...]
    videos_without_orders: int


@dataclass(frozen=True)
class HeroProfile:
    rank: int
    product_id: str
    title: str
    conclusion: Conclusion
    total: FunnelComparison
    self_search: FunnelComparison
    channels: tuple[ChannelRow, ...]
    affiliate_rows: tuple[ChannelRow, ...]
    #: GMV share by channel, ``{channel: (prior, last)}``.
    gmv_share: dict[Channel, tuple[float | None, float | None]]
    reading: str
    content_note: str
    bands: tuple[Band, ...]
    flash: FlashAnalysis
    discounts_prior: OrderDiscountShare
    discounts_last: OrderDiscountShare
    appearances: Appearances


@dataclass(frozen=True)
class WatchItem:
    product_id: str
    title: str
    reason: str
    gmv_prior: float
    gmv_last: float


@dataclass(frozen=True)
class ShopDiagnosis:
    shop_name: str
    end: date
    windows: Windows
    ranking: Ranking
    missing_days: tuple[date, ...]
    sale_days: tuple[date, ...]
    total: FunnelComparison
    channels: tuple[ChannelRow, ...]
    affiliate_rows: tuple[ChannelRow, ...]
    groups: tuple[GroupRow, ...]
    timelines: tuple[ChannelTimeline, ...]
    shop_bands: tuple[Band, ...]
    shop_flash: FlashAnalysis
    vouchers: VoucherSummary
    selection: HeroSelection
    profiles: tuple[HeroProfile, ...]
    rest_total: FunnelComparison
    rest_self_search: FunnelComparison
    rest_conclusion: Conclusion
    watch: tuple[WatchItem, ...]
    titles: dict[str, str]
    orders_present: bool

    def to_dict(self) -> dict[str, Any]:
        return _plain(dataclasses.asdict(self))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {_key(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(v) for v in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    return value


def _key(key: Any) -> str:
    if isinstance(key, Enum):
        return str(key.value)
    if isinstance(key, date):
        return key.isoformat()
    return str(key)


class _Builder:
    """Shared state of one build: the series, the present days of each window."""

    def __init__(self, snapshot: Snapshot, config: ShopDiagnosisConfig) -> None:
        self.snapshot = snapshot
        self.config = config
        self.windows = Windows.ending(snapshot.end, config.window_days)
        self.series: Series = build_series(snapshot.daily)
        present = set(snapshot.daily)
        self.prior_days = [d for d in self.windows.prior_days() if d in present]
        self.last_days = [d for d in self.windows.last_days() if d in present]
        if not self.prior_days or not self.last_days:
            raise ValueError("the snapshot needs daily files in both 30-day windows")
        self.missing = tuple(d for d in self.windows.all_days() if d not in present)

    def compare(
        self, channels: tuple[Channel, ...], products: list[str] | None = None
    ) -> FunnelComparison:
        return compare(
            daily_values(self.series, channels, self.prior_days, products),
            daily_values(self.series, channels, self.last_days, products),
            self.config,
        )

    def card_by_day(self, products: list[str] | None) -> dict[date, Counts]:
        days = self.windows.all_days()
        values = daily_values(self.series, [Channel.PRODUCT_CARD], days, products)
        return dict(zip(days, values, strict=True))


def _share_of(change: float, total_change: float) -> float | None:
    return change / total_change if total_change else None


def channel_tags(comparison: FunnelComparison, config: ShopDiagnosisConfig) -> tuple[str, ...]:
    """Short Vietnamese tags for one channel of a hero profile (d.8 part 3)."""
    tags: list[str] = []
    prior, last = comparison.prior, comparison.last
    if last.impressions < config.low_impressions_per_day:
        tags.append("ít lượt hiển thị")
    elif (
        prior.impressions > 0
        and last.impressions / prior.impressions - 1 >= config.impressions_surge
    ):
        tags.append("lượt hiển thị tăng mạnh")
    for name, factor in (("CTR", comparison.factors[1]), ("CTOR", comparison.factors[2])):
        if factor.prior is None or factor.last is None or factor.prior == factor.last:
            continue
        verb = "giảm" if factor.last < factor.prior else "tăng"
        if factor.confidence is Confidence.CLEAR:
            tags.append(f"{name} {verb} rõ")
        elif factor.confidence is Confidence.REFERENCE:
            tags.append(f"dấu hiệu {name} {verb}")
    return tuple(tags)


def reading_rule(rows: tuple[ChannelRow, ...], config: ShopDiagnosisConfig) -> str:
    """CTR down nearly everywhere → the product; only where impressions surged → diluted traffic."""
    with_data = [
        r
        for r in rows
        if r.comparison.prior.impressions >= config.low_impressions_per_day
        and r.comparison.last.impressions >= config.low_impressions_per_day
        and r.comparison.prior.ctr is not None
        and r.comparison.last.ctr is not None
    ]
    down = [r for r in with_data if (r.comparison.last.ctr or 0) < (r.comparison.prior.ctr or 0)]
    if len(with_data) >= 2 and len(down) >= config.ctr_down_nearly_all_share * len(with_data):
        return "CTR giảm ở gần như mọi kênh: nguyên nhân nằm ở chính sản phẩm."
    surged = [r for r in down if "lượt hiển thị tăng mạnh" in r.tags]
    if down and len(surged) == len(down):
        return (
            "CTR chỉ giảm ở kênh vừa nhận thêm nhiều lượt hiển thị: lưu lượng bị loãng, "
            "chưa nên sửa trang sản phẩm."
        )
    if not down:
        return "CTR không giảm ở kênh nào có đủ lượt hiển thị."
    return "CTR giảm ở một vài kênh, không đồng loạt: xem từng kênh bên dưới."


def _money_short(value: float) -> str:
    return f"{value / 1000:,.0f}k ₫".replace(",", ".")


def _content_note(content: FunnelComparison) -> str:
    p, q = content.prior, content.last
    change = (q.impressions / p.impressions - 1) if p.impressions else None
    pct = "" if change is None else f" ({change * 100:+.0f} %)".replace(".", ",")
    return (
        f"Nhóm nội dung: lượt hiển thị sản phẩm {p.impressions:,.0f} → {q.impressions:,.0f}/ngày"
        f"{pct}; GMV {_money_short(p.gmv)} → {_money_short(q.gmv)}/ngày."
    ).replace(",", ".")


def _appearances(
    snapshot: Snapshot, product_id: str, by_product: dict[str, list[Appearance]], count: int
) -> Appearances:
    items = by_product.get(product_id, [])
    live = [a for a in items if a.kind == "LIVE"]
    videos = [a for a in items if a.kind != "LIVE"]

    def top(entries: list[Appearance]) -> tuple[Appearance, ...]:
        ranked = sorted((a for a in entries if a.orders), key=lambda a: -(a.orders or 0))
        return tuple(ranked[:count])

    return Appearances(
        top(live),
        sum(1 for a in live if not a.orders),
        top(videos),
        sum(1 for a in videos if not a.orders),
    )


def _profile(
    builder: _Builder,
    rank: int,
    product_id: str,
    activity_promos: list,
    vouchers: list,
    appearances: dict[str, list[Appearance]],
) -> HeroProfile:
    config, snapshot, windows = builder.config, builder.snapshot, builder.windows
    products = [product_id]
    total = builder.compare((Channel.TOTAL,), products)
    self_search = builder.compare(SELF_SEARCH, products)
    card = builder.compare((Channel.PRODUCT_CARD,), products)
    rows: list[ChannelRow] = []
    for channel in FIVE_CHANNELS:
        comparison = (
            card if channel is Channel.PRODUCT_CARD else builder.compare((channel,), products)
        )
        rows.append(
            ChannelRow(
                channel,
                comparison,
                _share_of(comparison.gmv_change, total.gmv_change),
                channel in ADDITIVE,
                channel_tags(comparison, config),
            )
        )
    sub_rows = tuple(
        ChannelRow(c, builder.compare((c,), products), None, False) for c in AFFILIATE_SUB_ROWS
    )
    shares = {
        r.channel: (
            r.comparison.prior.gmv / total.prior.gmv if total.prior.gmv else None,
            r.comparison.last.gmv / total.last.gmv if total.last.gmv else None,
        )
        for r in rows
    }
    return HeroProfile(
        rank,
        product_id,
        snapshot.title(product_id),
        decide(self_search, card, config),
        total,
        self_search,
        tuple(rows),
        sub_rows,
        shares,
        reading_rule(tuple(rows), config),
        _content_note(builder.compare(CONTENT, products)),
        tuple(bands(activity_promos, vouchers, windows, product_id)),
        analyse_flash(
            activity_promos, windows, snapshot, builder.card_by_day(products), config, product_id
        ),
        order_discount_share(snapshot.orders, product_id, windows.prior_first, windows.prior_last),
        order_discount_share(snapshot.orders, product_id, windows.last_first, windows.last_last),
        _appearances(snapshot, product_id, appearances, config.appearances_listed),
    )


def _watch(builder: _Builder, selection: HeroSelection) -> tuple[WatchItem, ...]:
    config, series = builder.config, builder.series
    heroes = set(selection.heroes)
    items: list[WatchItem] = []
    seen: set[str] = set()

    def gmv(product_id: str) -> tuple[float, float]:
        prior = group_sum(series, [Channel.TOTAL], builder.prior_days, [product_id])
        last = group_sum(series, [Channel.TOTAL], builder.last_days, [product_id])
        return prior.gmv / len(builder.prior_days), last.gmv / len(builder.last_days)

    for product_id, move in selection.movers:
        prior, last = gmv(product_id)
        reason = "Vào top 5 của 30 ngày gần nhất" if move == ENTERED else "Rơi khỏi top 5"
        items.append(WatchItem(product_id, builder.snapshot.title(product_id), reason, prior, last))
        seen.add(product_id)
    candidates: list[tuple[float, WatchItem]] = []
    for product_id in series.get(Channel.TOTAL, {}):
        if product_id in heroes or product_id in seen:
            continue
        prior_c = group_sum(series, [Channel.TOTAL], builder.prior_days, [product_id])
        last_c = group_sum(series, [Channel.TOTAL], builder.last_days, [product_id])
        orders = max(prior_c.sku_orders or 0, last_c.sku_orders or 0)
        prior, last = gmv(product_id)
        if orders < config.watch_min_orders or prior <= 0:
            continue
        change = last / prior - 1
        if abs(change) >= config.watch_gmv_change:
            verb = "tăng" if change > 0 else "giảm"
            reason = f"GMV {verb} {abs(change) * 100:.0f} %"
            candidates.append(
                (
                    abs(last - prior),
                    WatchItem(product_id, builder.snapshot.title(product_id), reason, prior, last),
                )
            )
    candidates.sort(key=lambda c: -c[0])
    items += [item for _, item in candidates[: config.watch_max_products]]
    return tuple(items)


def build_report(
    snapshot: Snapshot,
    ranking: Ranking = Ranking.COMBINED_60D,
    config: ShopDiagnosisConfig | None = None,
) -> ShopDiagnosis:
    """Every number of the page, the JSON and the message, from one snapshot."""
    config = config or ShopDiagnosisConfig()
    builder = _Builder(snapshot, config)
    windows = builder.windows
    total = builder.compare((Channel.TOTAL,))
    rows = tuple(
        ChannelRow(
            channel,
            comparison := builder.compare((channel,)),
            _share_of(comparison.gmv_change, total.gmv_change),
            channel in ADDITIVE,
        )
        for channel in FIVE_CHANNELS
    )
    affiliate_rows = tuple(
        ChannelRow(c, builder.compare((c,)), None, False) for c in AFFILIATE_SUB_ROWS
    )
    groups = []
    for label, members in (("Nhóm khách tự tìm đến", SELF_SEARCH), ("Nhóm nội dung", CONTENT)):
        comparison = builder.compare(members)
        groups.append(
            GroupRow(label, members, comparison, _share_of(comparison.gmv_change, total.gmv_change))
        )

    activity_promos = parse_activities(snapshot.activities, snapshot.activity_details)
    vouchers = parse_vouchers(snapshot.coupons)
    shop_flash = analyse_flash(
        activity_promos, windows, snapshot, builder.card_by_day(None), config
    )
    flash_days = {
        d for d, share in shop_flash.coverage.items() if share >= config.flash_day_coverage
    }
    selection = select_heroes(builder.series, windows, ranking, config, snapshot.title)
    appearances = parse_appearances(
        snapshot.live_sessions, snapshot.live_products, snapshot.videos, snapshot.video_products
    )
    profiles = tuple(
        _profile(builder, i + 1, pid, activity_promos, vouchers, appearances)
        for i, pid in enumerate(selection.heroes)
    )
    rest = [p for p in builder.series.get(Channel.TOTAL, {}) if p not in set(selection.heroes)]
    rest_self = builder.compare(SELF_SEARCH, rest)
    rest_card = builder.compare((Channel.PRODUCT_CARD,), rest)
    all_days = windows.all_days()
    titles = {pid: snapshot.title(pid) for pid in builder.series.get(Channel.TOTAL, {})}
    return ShopDiagnosis(
        shop_name=snapshot.shop_name,
        end=snapshot.end,
        windows=windows,
        ranking=ranking,
        missing_days=builder.missing,
        sale_days=tuple(sale_days(all_days)),
        total=total,
        channels=rows,
        affiliate_rows=affiliate_rows,
        groups=tuple(groups),
        timelines=build_timelines(builder.series, all_days, config.rolling_days),
        shop_bands=tuple(bands(activity_promos, vouchers, windows)),
        shop_flash=shop_flash,
        vouchers=analyse_vouchers(vouchers, snapshot.orders, windows, flash_days, config),
        selection=selection,
        profiles=profiles,
        rest_total=builder.compare((Channel.TOTAL,), rest),
        rest_self_search=rest_self,
        rest_conclusion=decide(rest_self, rest_card, config),
        watch=_watch(builder, selection),
        titles=titles,
        orders_present=snapshot.orders is not None,
    )
