"""The shop's ad campaigns as Seller Centre last showed them (Connector 0.3.7).

``ads_campaign_settings`` (every campaign on the Quảng cáo list) and ``ads_campaign_detail`` (the
edit-page limits of the ongoing / scheduled ones) are daily snapshots in
``platform_period_metrics``. :func:`ads_campaign_settings` returns, per campaign, the newest
settings and, when the Connector read its edit page, the newest detail -- what the builder needs
to offer "Chiến dịch đang chạy" with Shopee's own limits. Read-only; the caller holds the shop's
scope.
"""

from __future__ import annotations

import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.platform_data import PlatformPeriodMetric

if TYPE_CHECKING:
    from juli_backend.services.shopee_recommendations.env import RecoEnv

SETTINGS_DATASET = "ads_campaign_settings"
DETAIL_DATASET = "ads_campaign_detail"


async def _newest(
    session: AsyncSession, shop_id: uuid.UUID, dataset: str
) -> dict[str, PlatformPeriodMetric]:
    """The newest snapshot row of ``dataset`` per campaign id."""
    rows = (
        await session.execute(
            select(PlatformPeriodMetric)
            .where(
                PlatformPeriodMetric.shop_id == shop_id,
                PlatformPeriodMetric.platform == "shopee",
                PlatformPeriodMetric.dataset == dataset,
            )
            .order_by(PlatformPeriodMetric.period_end)
        )
    ).scalars()
    newest: dict[str, PlatformPeriodMetric] = {}
    for row in rows:
        campaign_id = (row.extra or {}).get("campaign_id")
        if isinstance(campaign_id, str):
            newest[campaign_id] = row  # ordered by day: the last one wins
    return newest


async def ads_campaign_settings(session: AsyncSession, shop_id: uuid.UUID) -> list[dict[str, Any]]:
    """Per campaign: its newest settings (``captured_on`` = that snapshot's day), with
    ``campaign_name`` and ``detail`` (the newest edit-page limits, or None when never read)."""
    settings = await _newest(session, shop_id, SETTINGS_DATASET)
    details = await _newest(session, shop_id, DETAIL_DATASET)
    out: list[dict[str, Any]] = []
    for campaign_id, row in sorted(settings.items()):
        detail = details.get(campaign_id)
        out.append(
            {
                **(row.extra or {}),
                "campaign_id": campaign_id,
                "campaign_name": row.platform_source,
                "captured_on": row.period_end.isoformat(),
                "detail": None
                if detail is None
                else {**(detail.extra or {}), "captured_on": detail.period_end.isoformat()},
            }
        )
    return out


def campaign_name_key(name: str | None) -> str:
    """One key for a campaign's name across sources: NFKC, case-folded, single spaces."""
    text = unicodedata.normalize("NFKC", name or "")
    return " ".join(text.casefold().split())


_RUNNING = ("ongoing", "running", "active", "live", "on")
_PAUSED = ("paused", "pause", "suspended", "off")
_SCHEDULED = ("scheduled", "pending", "upcoming")
_ENDED = ("ended", "closed", "finished", "expired", "terminated")


def type_label(info: Mapping[str, Any]) -> str | None:
    """Short label of a campaign's type: product (manual), GMV Max, shop, or the raw word."""
    raw = str(info.get("campaign_type") or "").casefold()
    if not raw:
        return "Chiến dịch nhóm" if info.get("is_group") else None
    if "gmv" in raw or "auto" in raw:
        return "GMV Max"
    if "shop" in raw:
        return "Shop"
    if "group" in raw or info.get("is_group"):
        return "Sản phẩm · nhóm"
    if "product" in raw or "manual" in raw:
        return "Sản phẩm"
    return str(info["campaign_type"])


def status_label(info: Mapping[str, Any]) -> str | None:
    state = str(info.get("state") or "").casefold()
    for words, text in (
        (_RUNNING, "đang chạy"),
        (_PAUSED, "tạm dừng"),
        (_SCHEDULED, "đã lên lịch"),
        (_ENDED, "đã kết thúc"),
    ):
        if any(w == state or (len(w) > 3 and w in state) for w in words):
            return text
    return None


@dataclass
class RealCampaigns:
    """The shop's real campaigns (those with a Shopee campaign id), by id and by name. Product-level
    rows of the ads report carry no campaign id and are not campaigns."""

    by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_name: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def known(self) -> bool:
        return bool(self.by_id)

    def match(self, name: str, key: str, setting: Any = None) -> dict[str, Any] | None:
        cid = getattr(setting, "campaign_id", None)
        if cid is not None and str(cid) in self.by_id:
            return self.by_id[str(cid)]
        for candidate in (name, key, getattr(setting, "name", None)):
            hit = self.by_name.get(campaign_name_key(candidate))
            if hit is not None:
                return hit
        return None

    def id_of(self, name: str, key: str, setting: Any = None) -> str | None:
        info = self.match(name, key, setting)
        if info is not None:
            return str(info["campaign_id"])
        cid = getattr(setting, "campaign_id", None)
        return None if cid is None else str(cid)

    def labels(self, info: Mapping[str, Any] | None) -> dict[str, Any]:
        if info is None:
            return {"campaign_type": None, "type_label": None, "status_label": None}
        return {
            "campaign_type": info.get("campaign_type"),
            "type_label": type_label(info),
            "status_label": status_label(info),
        }

    def running(self, info: Mapping[str, Any], fallback: bool | None) -> bool | None:
        label = status_label(info)
        return fallback if label is None else label == "đang chạy"


def real_campaigns(env: RecoEnv, snapshots: Sequence[Mapping[str, Any]]) -> RealCampaigns:
    """Campaigns with an id: the Connector's settings snapshots first, then the per-campaign
    daily rows' settings (``extra.campaign_id``)."""
    out = RealCampaigns()

    def put(info: dict[str, Any], *names: str | None) -> None:
        out.by_id.setdefault(str(info["campaign_id"]), info)
        for name in names:
            if name:
                out.by_name.setdefault(campaign_name_key(name), out.by_id[str(info["campaign_id"])])

    for snap in snapshots:
        if snap.get("campaign_id"):
            put(dict(snap), snap.get("campaign_name"))
    for setting in dict.fromkeys(env.campaigns.values()):
        if setting.campaign_id:
            put({"campaign_id": str(setting.campaign_id), "campaign_name": setting.name},
                setting.name, setting.key)  # fmt: skip
    return out


def dedupe_campaigns(
    rows: Sequence[dict[str, Any]], *, excluded_names: set[str] | None = None
) -> list[dict[str, Any]]:
    """One row per campaign (its id, else its name): the one with a settings match and the most
    spend wins; rows named like a product are dropped; biggest recent spender first."""
    excluded = excluded_names or set()
    best: dict[str, dict[str, Any]] = {}

    def rank(r: Mapping[str, Any]) -> tuple[int, float]:
        return (
            int(r.get("daily_budget") is not None or r.get("roas_target") is not None),
            float(r.get("spend_per_day") or 0),
        )

    id_by_name = {
        campaign_name_key(str(r.get("name") or "")): str(r["campaign_id"])
        for r in rows
        if r.get("campaign_id")
    }
    for row in rows:
        name = campaign_name_key(str(row.get("name") or ""))
        if name in excluded:
            continue
        ident = str(row.get("campaign_id") or "") or id_by_name.get(name) or name
        kept = best.get(ident)
        if kept is None or rank(row) > rank(kept):
            best[ident] = row
    return sorted(
        best.values(),
        key=lambda r: (-float(r.get("spend_per_day") or 0), campaign_name_key(str(r["name"]))),
    )
