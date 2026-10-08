"""Hero products: the top five by GMV, two ranking modes — ADR-108 decision 6.

GMV is the all-channel total. The operator picks the ranking: GMV over the 60
days combined (the default — ranking on the last 30 days drops exactly the
products whose CTOR collapsed) or over the last 30 days. Products in the top
five of one 30-day window but not in the chosen list are named *vào top* (top
of the last 30 days) or *rơi khỏi top* (top of the prior 30 days). When the
five carry under half of shop GMV the page warns that the top five does not
represent the shop.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from juli_backend.services.shop_diagnosis.channels import Channel, Series, window_sum
from juli_backend.services.shop_diagnosis.config import ShopDiagnosisConfig
from juli_backend.services.shop_diagnosis.snapshot import Windows


class Ranking(StrEnum):
    COMBINED_60D = "60d"
    LAST_30D = "30d"


RANKING_LABELS: dict[Ranking, str] = {
    Ranking.COMBINED_60D: "GMV 60 ngày gộp",
    Ranking.LAST_30D: "GMV 30 ngày gần nhất",
}
ENTERED = "vào top"
DROPPED = "rơi khỏi top"


@dataclass(frozen=True)
class HeroSelection:
    ranking: Ranking
    heroes: tuple[str, ...]
    #: Share of shop GMV the heroes carry over the ranking window.
    gmv_share: float | None
    #: ``(product id, ENTERED | DROPPED)`` for products outside the chosen five.
    movers: tuple[tuple[str, str], ...]
    #: The heroes carry under ``hero_min_gmv_share`` of shop GMV.
    dispersed: bool


def _gmv_by_product(series: Series, days: list) -> dict[str, float]:
    return {
        product_id: window_sum(series, Channel.TOTAL, days, [product_id]).gmv
        for product_id in series.get(Channel.TOTAL, {})
    }


def _top(gmv: dict[str, float], eligible: Callable[[str], bool], count: int) -> list[str]:
    ranked = sorted(
        (pid for pid, value in gmv.items() if value > 0 and eligible(pid)),
        key=lambda pid: (-gmv[pid], pid),
    )
    return ranked[:count]


def select_heroes(
    series: Series,
    windows: Windows,
    ranking: Ranking,
    config: ShopDiagnosisConfig,
    title_of: Callable[[str], str] = lambda _pid: "",
) -> HeroSelection:
    """Choose the five heroes and name the movers of the two 30-day windows."""
    patterns = tuple(p.lower() for p in config.exclude_title_patterns)

    def eligible(product_id: str) -> bool:
        title = title_of(product_id).lower()
        return not any(p in title for p in patterns)

    days = windows.all_days() if ranking is Ranking.COMBINED_60D else windows.last_days()
    ranked_gmv = _gmv_by_product(series, days)
    heroes = _top(ranked_gmv, eligible, config.hero_count)
    shop_gmv = sum(ranked_gmv.values())
    share = sum(ranked_gmv[p] for p in heroes) / shop_gmv if shop_gmv > 0 else None

    chosen = set(heroes)
    movers: list[tuple[str, str]] = []
    top_last = _top(_gmv_by_product(series, windows.last_days()), eligible, config.hero_count)
    top_prior = _top(_gmv_by_product(series, windows.prior_days()), eligible, config.hero_count)
    movers += [(p, ENTERED) for p in top_last if p not in chosen]
    movers += [(p, DROPPED) for p in top_prior if p not in chosen and p not in top_last]
    return HeroSelection(
        ranking,
        tuple(heroes),
        share,
        tuple(movers),
        share is not None and share < config.hero_min_gmv_share,
    )
