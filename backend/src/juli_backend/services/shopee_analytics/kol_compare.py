"""Phân tích › KOL › So sánh: affiliate performance and its real cost by group (P100, 2026-11-13).

Built from the SAME rows as the KOL table (:func:`kol.compute`): a group (kênh / loại chiến dịch /
KOL) is the sum of its KOL x product x channel rows, so every figure ties back to the table.
Per creator x product nearly every pair is "Ít dữ liệu"; a group is "Ít dữ liệu" below
:data:`kol.ORDERS_THRESHOLD` orders of its own.

Per group (VND, the window's confirmed lines, "Theo báo cáo chuyển đổi KOL"):

- ``cost``: the commission Shopee charges (the report's ``Chi phí``, commission incl. its 8 %),
  the KOL table's ``commission``; ``sample_cost`` the Mẫu KOL cost, separate.
- ``net_profit``: after platform fees, giá vốn, đóng gói and commission; before shop ads (the KOL
  model's waterfall, never recomputed). ``profit_after_samples`` = net - samples.
- ``profit_per_order`` = net_profit / the group's profit-carrying orders.
- ``roi_incl_samples`` = (net - samples) / (cost + samples).
- ``share_gmv_pct``: the group's GMV in the affiliate GMV of all rows (same basis).

The stream strip puts Affiliate beside Ads and the shop's own flows for the same window. Each row
names its basis: affiliate cost and profit come from the conversion report, GMV / orders of the
flows from Seller Centre's traffic sources ("Theo nguồn lưu lượng"), ads on placed orders; the two
affiliate bases count differently and are never mixed in one ratio. A figure no source gives is
null with a reason.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.fmt import ADS_BASIS, ORDER_BASIS, num, pct_of, ratio
from juli_backend.services.shopee_analytics.kol import (
    LOW_DATA_LABEL,
    NO_ORDERS_CHANNEL,
    ORDERS_THRESHOLD,
    KolModel,
    KolRow,
)
from juli_backend.services.shopee_analytics.kol_labels import (
    NO_CAMPAIGN_TYPE,
    campaign_type_label,
    channel_label,
)
from juli_backend.services.shopee_profit.flows import Flow
from juli_backend.services.shopee_profit.money import ZERO, safe_div

GROUPS = ("channel", "campaign_type", "kol")
GROUP_LABELS = {"channel": "Kênh", "campaign_type": "Loại chiến dịch", "kol": "KOL"}
BASIS_KOL = {"key": "kol_conversion_report", "label": "Theo báo cáo chuyển đổi KOL"}
BASIS_FLOWS = {"key": "traffic_sources", "label": "Theo nguồn lưu lượng"}
BASIS_ADS = {"key": "ads_report", "label": "Theo báo cáo quảng cáo (đơn đã đặt)"}
COST_LABEL = "Hoa hồng Shopee thu (chi phí trong báo cáo, gồm 8 % phí trên hoa hồng)"
ORGANIC_FLOWS = (Flow.THE_SAN_PHAM_KHAC, Flow.TRANG_SHOP, Flow.VIDEO, Flow.LIVE)

NO_FLOWS = "Chưa có lưu lượng theo nguồn của Seller Centre trong kỳ."
NO_ADS = "Chưa có dữ liệu quảng cáo trong kỳ."
NO_SOURCE_PROFIT = (
    "Juli chỉ tính lợi nhuận ở cấp shop; quảng cáo nằm trong các luồng (trong đó), "
    "nên không tách được lợi nhuận riêng của nguồn này."
)


@dataclass
class _Group:
    key: str
    label: str
    rows: list[KolRow] = field(default_factory=list)

    def json(self, total_gmv: Decimal) -> dict[str, Any]:
        orders: set[str] = set()
        for r in self.rows:
            orders |= r.order_ids
        gmv = sum((r.gmv for r in self.rows), ZERO)
        cost = sum((r.commission for r in self.rows), ZERO)
        net = sum((r.net_profit for r in self.rows), ZERO)
        profit_orders = sum(r.profit_orders for r in self.rows)
        # a shipment without a price makes the group's sample cost unknown, as in the KOL totals
        unknown_sample = any(r.sample_cost is None and r.sample_qty for r in self.rows)
        sample = None if unknown_sample else sum((r.sample_cost or ZERO for r in self.rows), ZERO)
        after = net - (sample or ZERO)
        denominator = cost + (sample or ZERO)
        n = len(orders)
        return {
            "key": self.key,
            "label": self.label,
            "orders": n,
            "units": sum(r.units for r in self.rows),
            "gmv": num(gmv),
            "cost": num(cost),
            "cost_pct_gmv": pct_of(safe_div(cost, gmv)) if gmv > 0 else None,
            "sample_cost": None if sample is None else num(sample),
            "net_profit": num(net),
            "profit_after_samples": num(after),
            "profit_orders": profit_orders,
            "profit_per_order": num(net / profit_orders) if profit_orders else None,
            "roi_incl_samples": None if denominator <= 0 else ratio(after / denominator, 4),
            "kols": len({r.kol_key for r in self.rows}),
            "products": len({r.item_id for r in self.rows}),
            "share_gmv_pct": pct_of(safe_div(gmv, total_gmv)) if total_gmv > 0 else None,
            "low_data": n < ORDERS_THRESHOLD,
            "low_data_label": LOW_DATA_LABEL if n < ORDERS_THRESHOLD else None,
        }


def _key_of(group: str) -> Callable[[KolRow], tuple[str, str]]:
    def channel(r: KolRow) -> tuple[str, str]:
        label = channel_label(r.channel) or r.channel
        return label, label

    def campaign(r: KolRow) -> tuple[str, str]:
        if r.channel == NO_ORDERS_CHANNEL:  # a sample with no order yet carries no campaign
            return NO_ORDERS_CHANNEL, NO_ORDERS_CHANNEL
        label = campaign_type_label(r.campaign_type) or NO_CAMPAIGN_TYPE
        return label, label

    def kol(r: KolRow) -> tuple[str, str]:
        return r.kol_key, r.handle

    return {"channel": channel, "campaign_type": campaign, "kol": kol}[group]


def groups_json(model: KolModel, group: str) -> dict[str, Any]:
    if group not in GROUPS:
        raise ValueError(f"group must be one of {list(GROUPS)}")
    key_of = _key_of(group)
    found: dict[str, _Group] = {}
    for r in model.rows:
        key, label = key_of(r)
        found.setdefault(key, _Group(key, label)).rows.append(r)
    total_gmv = sum((r.gmv for r in model.rows), ZERO)
    rows = [g.json(total_gmv) for g in found.values()]
    rows.sort(key=lambda g: (-(g["gmv"] or 0), -(g["orders"] or 0), g["label"]))
    return {
        "group": group,
        "group_label": GROUP_LABELS[group],
        "rows": rows,
        "total": _Group("total", "Tổng Tiếp thị liên kết", list(model.rows)).json(total_gmv),
    }


# ----------------------------------------------------------------------------- stream strip


def _stream(
    key: str,
    label: str,
    *,
    gmv: Decimal | None,
    orders: Decimal | int | None,
    basis: dict[str, str],
    cost: Decimal | None,
    cost_basis: dict[str, str] | None,
    cost_pct_gmv: float | None,
    profit: Decimal | None,
    profit_reason: str | None,
    reason: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "gmv": num(gmv),
        "orders": num(orders),
        "basis": basis,
        "cost": num(cost),
        "cost_basis": cost_basis,
        "cost_pct_gmv": cost_pct_gmv,
        "profit_after_cost": num(profit),
        "profit_reason": profit_reason,
        "reason": reason,
        "note": note,
    }


def stream_strip(view: PeriodView, model: KolModel) -> dict[str, Any]:
    """Affiliate vs Ads vs the shop's own flows, same window, each with its basis."""
    table = view.flows.shop if view.flows else None
    aff_row = table.row(Flow.LIEN_KET.value) if table else None
    kol_total = _Group("total", "", list(model.rows)).json(sum((r.gmv for r in model.rows), ZERO))
    kol_gmv = Decimal(str(kol_total["gmv"] or 0))
    kol_cost = Decimal(str(kol_total["cost"] or 0))
    sample = kol_total["sample_cost"]
    aff_cost = None if sample is None else kol_cost + Decimal(str(sample))
    affiliate = _stream(
        "affiliate",
        "Tiếp thị liên kết",
        gmv=aff_row.gmv if aff_row else None,
        orders=aff_row.orders if aff_row else None,
        basis=BASIS_FLOWS,
        cost=aff_cost,
        cost_basis=BASIS_KOL,
        # cost ÷ the conversion report's own GMV: the two bases are never mixed in one ratio
        cost_pct_gmv=pct_of(safe_div(aff_cost, kol_gmv))
        if aff_cost is not None and kol_gmv > 0
        else None,
        profit=None if sample is None else Decimal(str(kol_total["profit_after_samples"])),
        profit_reason=None
        if sample is not None
        else "Có mẫu KOL chưa tính được chi phí (thiếu giá vốn).",
        reason=None if aff_row else NO_FLOWS,
        note="Chi phí = hoa hồng + chi phí mẫu; % chi phí và lợi nhuận tính trên GMV và đơn "
        "theo báo cáo chuyển đổi KOL.",
    )
    affiliate["conversion_report"] = {"gmv": num(kol_gmv), "orders": kol_total["orders"]}
    ads = view.ads
    daily = view.data.ads_daily
    has_ads = daily.days_covered > 0 or ads.total_spend > 0
    ads_gmv = daily.gmv if daily.days_covered else sum((c.gmv for c in ads.campaigns), ZERO)
    advertising = _stream(
        "ads",
        "Quảng cáo (Dịch vụ hiển thị)",
        gmv=ads_gmv if has_ads else None,
        orders=daily.orders if daily.days_covered else None,
        basis=BASIS_ADS,
        cost=ads.total_spend if has_ads else None,
        cost_basis=BASIS_ADS if has_ads else None,
        cost_pct_gmv=pct_of(safe_div(ads.total_spend, ads_gmv))
        if has_ads and ads_gmv > 0
        else None,
        profit=None,
        profit_reason=NO_SOURCE_PROFIT,
        reason=None if has_ads else NO_ADS,
        note=f"{daily.days_covered}/{daily.window_days} ngày có dữ liệu quảng cáo; quảng cáo nằm "
        "trong các luồng, không cộng thêm."
        if has_ads
        else None,
    )
    organic_rows = [table.row(f.value) for f in ORGANIC_FLOWS] if table else []
    present = [r for r in organic_rows if r is not None]
    organic = _stream(
        "organic",
        "Thẻ sản phẩm + Video/Live của shop",
        gmv=sum((r.gmv for r in present), ZERO) if present else None,
        orders=sum(r.orders for r in present) if present else None,
        basis=BASIS_FLOWS,
        cost=ZERO if present else None,
        cost_basis=BASIS_FLOWS if present else None,
        cost_pct_gmv=0.0 if present else None,
        profit=None,
        profit_reason=NO_SOURCE_PROFIT,
        reason=None if present else NO_FLOWS,
        note="Không trả hoa hồng; gồm cả đơn có quảng cáo (quảng cáo nằm trong các luồng)."
        if present
        else None,
    )
    return {
        "rows": [affiliate, advertising, organic],
        "shop_gmv": num(table.total_gmv) if table else None,
        "shop_orders": table.total_orders if table else None,
        "bases": {"kol": BASIS_KOL, "flows": BASIS_FLOWS, "ads": BASIS_ADS},
        "note": "Hai cách đếm Tiếp thị liên kết khác nhau: báo cáo chuyển đổi KOL đếm theo đơn "
        "KOL ghi nhận, nguồn lưu lượng đếm theo Seller Centre; không cộng hay chia chéo hai số.",
    }


def compare(view: PeriodView, model: KolModel, group: str = "channel") -> dict[str, Any]:
    body = groups_json(model, group)
    return {
        "window": model.window,
        **body,
        "streams": stream_strip(view, model),
        "basis": BASIS_KOL,
        "order_basis": ORDER_BASIS,
        "ads_order_basis": ADS_BASIS,
        "labels": {
            "cost": COST_LABEL,
            "net_profit": "sau phí sàn, giá vốn, đóng gói và hoa hồng; trước quảng cáo",
            "profit_per_order": "lợi nhuận ròng ÷ đơn đã có lợi nhuận (đã giao)",
            "roi_formula": "(lợi nhuận ròng − chi phí mẫu) ÷ (hoa hồng + chi phí mẫu)",
            "low_data": LOW_DATA_LABEL,
            "low_data_threshold": ORDERS_THRESHOLD,
            "share_gmv": "phần GMV Tiếp thị liên kết (theo báo cáo chuyển đổi KOL)",
        },
    }
