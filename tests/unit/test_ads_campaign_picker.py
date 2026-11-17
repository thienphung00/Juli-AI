"""The Tự tạo DVHT campaign picker: one entry per real campaign, and the campaign id travels on
the card so the Connector can open the campaign page."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from juli_backend.services.shopee_builder.ads_campaigns import (
    RealCampaigns,
    dedupe_campaigns,
    real_campaigns,
    status_label,
    type_label,
)


@dataclass(frozen=True)
class _Setting:
    key: str
    name: str
    campaign_id: str | None


SNAPS = [
    {
        "campaign_id": "7001",
        "campaign_name": "CDN/01 - Bán chạy",
        "campaign_type": "product_manual",
        "state": "ongoing",
    },
    {
        "campaign_id": "7002",
        "campaign_name": "GMV Max shop",
        "campaign_type": "gmv_max",
        "state": "paused",
    },
]


def _env(settings=()):
    return SimpleNamespace(campaigns={s.key: s for s in settings})


def test_real_campaigns_match_by_name_even_when_the_daily_rows_have_no_id():
    real = real_campaigns(_env(), SNAPS)
    assert real.known
    assert real.id_of("  cdn/01 - Bán CHẠY ", "some-hash") == "7001"
    assert real.id_of("Hạt giống rau", "hash2") is None
    assert real.match("Hạt giống rau", "hash2") is None


def test_the_id_falls_back_to_the_daily_rows_setting():
    setting = _Setting("k1", "Chiến dịch A", "9009")
    real = real_campaigns(_env([setting]), [])
    assert real.id_of("Chiến dịch A", "k1", setting) == "9009"
    assert real.known


def test_type_and_status_labels():
    assert type_label(SNAPS[0]) == "Sản phẩm" and status_label(SNAPS[0]) == "đang chạy"
    assert type_label(SNAPS[1]) == "GMV Max" and status_label(SNAPS[1]) == "tạm dừng"
    assert RealCampaigns().running(SNAPS[1], True) is False


def test_duplicates_collapse_and_product_rows_go_and_biggest_spender_leads():
    rows = [
        {"campaign_key": f"h{n}", "name": "CDN/01 - Bán chạy", "campaign_id": "7001",
         "spend_per_day": 100 * n, "daily_budget": 100_000}
        for n in range(1, 11)
    ]  # fmt: skip
    rows.append({"campaign_key": "x", "name": "cdn/01 - bán chạy", "campaign_id": None,
                 "spend_per_day": 5})  # fmt: skip
    rows.append({"campaign_key": "g", "name": "GMV Max shop", "campaign_id": "7002",
                 "spend_per_day": 5_000})  # fmt: skip
    rows.append({"campaign_key": "p", "name": "Hạt giống rau", "campaign_id": None,
                 "spend_per_day": 9_999})  # fmt: skip
    out = dedupe_campaigns(rows, excluded_names={"hạt giống rau"})
    assert [r["name"] for r in out] == ["GMV Max shop", "CDN/01 - Bán chạy"]
    assert out[1]["campaign_key"] == "h10"
