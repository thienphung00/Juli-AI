"""Xếp hạng (Shopee): which rows moved a cell, last window against the previous one.

A Shopee sibling of ``services/shop_diagnosis/rankings.py`` (ADR-109 d.5): the TikTok module is
a factor-chain decomposition over a stored ``Snapshot`` with TikTok's channel frame, so it is
reused for its conventions, not extended -- the same table shape (``down`` / ``up`` lists, the
closing rows ``few`` / ``others`` / ``mix``), the same thresholds (``ShopDiagnosisConfig``: 10 / 30
order floors, at most 10 rows, 1 % fold share) and the same confidence labels.

Parameters
- ``kind``: ``products`` | ``campaigns`` | ``kols`` | ``vouchers`` | ``keywords``.
- ``source``: ``all`` | a traffic flow (``the_san_pham_khac`` ``trang_shop`` ``live`` ``video``
  ``lien_ket``) with an optional Thẻ sản phẩm child ``sub`` | ``ads`` (placed-order overlay) | a
  price lever (``none`` ``voucher`` ``promo`` ``combo``). Which kinds support which source is in
  :data:`SUPPORTED`; an unsupported combination answers ``supported: false`` with the reason.
- ``xep_theo``: ``gmv_per_day`` (default) | ``profit_per_day`` | the five numbers: ``giam_gia``,
  ``thu_them`` (ΔGMV ÷ Δchi), ``bien``, ``orders``, ``aov``.

Adds up: for the additive measures (``gmv_per_day``, ``profit_per_day``, ``orders``) every table
satisfies ``Σ listed rows + few + others + mix == the cell's change``; ``mix`` ("Thay đổi cơ cấu")
is the cell's own figure minus the sum of ALL rows (rows of another basis, unattributed spend,
rounding), never a plug that hides a gap: it is shown and sized. Each direction view also carries
the opposite-sign rows as one closing line so it adds up by itself. Ratio measures cannot add up
and say so (``adds_up: null``).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from juli_backend.services.shop_diagnosis.confidence import Confidence, volume_label
from juli_backend.services.shop_diagnosis.config import ShopDiagnosisConfig
from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.fmt import ADS_BASIS, ADS_BASIS_NOTE, num
from juli_backend.services.shopee_analytics.loaders import CARD_CHILDREN
from juli_backend.services.shopee_profit.flows import Flow, FlowSource
from juli_backend.services.shopee_profit.money import ZERO, safe_div
from juli_backend.services.shopee_profit.sources import CellStats

KINDS = ("products", "campaigns", "kols", "vouchers", "keywords")
FLOW_SOURCES = tuple(f.value for f in Flow)
LEVER_SOURCES = ("none", "voucher", "promo", "combo")
SOURCES = ("all", *FLOW_SOURCES, "ads", *LEVER_SOURCES)
XEP_THEO = ("gmv_per_day", "profit_per_day", "giam_gia", "thu_them", "bien", "orders", "aov")
ADDITIVE = frozenset({"gmv_per_day", "profit_per_day", "orders"})
XEP_LABELS = {
    "gmv_per_day": "₫ GMV / ngày",
    "profit_per_day": "₫ lợi nhuận / ngày",
    "giam_gia": "% giảm giá",
    "thu_them": "Doanh thu thêm / chi thêm",
    "bien": "Biên cuối",
    "orders": "Số đơn / ngày",
    "aov": "AOV",
}
LEVER_KEY = {"none": "khong_uu_dai", "voucher": "voucher", "promo": "khuyen_mai", "combo": "combo"}
NOUNS: dict[str, tuple[str, str, str]] = {
    "products": ("sản phẩm", "Các sản phẩm khác", "Thay đổi cơ cấu sản phẩm"),
    "campaigns": ("chiến dịch", "Các chiến dịch khác", "Thay đổi cơ cấu chiến dịch"),
    "kols": ("KOL", "Các KOL khác", "Thay đổi cơ cấu KOL"),
    "vouchers": ("voucher", "Các voucher khác", "Thay đổi cơ cấu voucher"),
    "keywords": ("từ khoá", "Các từ khoá khác", "Thay đổi cơ cấu từ khoá"),
}
#: kind -> sources it can be split by.
SUPPORTED: dict[str, tuple[str, ...]] = {
    "products": SOURCES,
    "campaigns": ("all", "ads"),
    "kols": ("all", "lien_ket"),
    "vouchers": ("all", "voucher"),
    "keywords": ("all", "ads"),
}
#: kind -> xep_theo it can be ranked by (other combinations say why not).
RANKABLE: dict[str, tuple[str, ...]] = {
    "products": XEP_THEO,
    "campaigns": ("gmv_per_day", "orders", "aov", "thu_them"),
    "kols": ("gmv_per_day", "orders", "aov"),
    "vouchers": ("gmv_per_day", "orders", "aov"),
    "keywords": ("gmv_per_day", "orders", "aov"),
}
CONFIG = ShopDiagnosisConfig()


@dataclass
class M:
    """Raw sums of one row in one window; ratios are derived from these, never stored."""

    gmv: Decimal = ZERO
    orders: Decimal = ZERO
    profit: Decimal | None = None
    buyer_paid: Decimal = ZERO
    discount: Decimal = ZERO
    list_value: Decimal = ZERO
    spend: Decimal = ZERO
    chi: Decimal = ZERO  # QC + voucher + khuyến mãi + combo + hoa hồng (contract 5)
    extra: dict[str, Any] = field(default_factory=dict)


def _measure(m: M | None, key: str, days: int) -> Decimal | None:
    if m is None:
        return None
    d = Decimal(days)
    if key == "gmv_per_day":
        return m.gmv / d
    if key == "profit_per_day":
        return None if m.profit is None else m.profit / d
    if key == "orders":
        return m.orders / d
    if key == "aov":
        return safe_div(m.gmv, m.orders)
    if key == "bien":
        return None if m.profit is None else safe_div(m.profit * 100, m.buyer_paid)
    if key == "giam_gia":
        v = safe_div(m.discount * 100, m.list_value)
        return v
    return None


@dataclass
class _Out:
    id: str
    label: str
    now: M | None
    before: M | None
    product_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


Rows = dict[str, tuple[str, M, dict[str, Any]]]


# ---- row sources ---------------------------------------------------------------------


def _product_m(view: PeriodView, pid: str, source: str, sub: str | None) -> M | None:
    """One product's figures for a source in one window (None = the source has nothing)."""
    pp = view.profit.products.get(pid)
    pairs = [(ln, pb) for ln, pb in view.pairs if ln.product_id == pid]
    if source in LEVER_SOURCES:
        cell = view.matrix.lever.get((pid, LEVER_KEY[source]), CellStats())
        if cell.orders == 0:
            return None
        return M(
            cell.gmv,
            Decimal(cell.orders),
            cell.profit if not cell.orders_missing_profit else None,
            cell.buyer_paid_known,
        )
    if source in FLOW_SOURCES or sub:
        table = view.flows.products.get(pid) if view.flows else None
        if sub:
            agg = view.data.product_flows.children.get(pid, {}).get(sub)
            if agg is None or (agg.orders == 0 and agg.gmv == 0 and not agg.views):
                return None
            return M(
                agg.gmv, agg.orders, None, ZERO, extra={"views": agg.views, "clicks": agg.clicks}
            )
        if table is None:
            return None
        row = table.row(source)
        if row is None or (row.gmv == 0 and not row.orders and not row.views):
            return None
        return M(
            row.gmv,
            Decimal(row.orders),
            None,
            ZERO,
            extra={"views": row.views, "clicks": row.clicks},
        )
    if source == "ads":
        fig = view.ads.product_figures.get(pid)
        if fig is None:
            return None
        return M(
            fig.gmv or ZERO, ZERO, None, ZERO, spend=fig.spend, extra={"direct_gmv": fig.direct_gmv}
        )
    # all
    shopee = view.data.product_flows.totals.get(pid)
    gmv = shopee[0] if shopee else sum((ln.order_value for ln, _ in pairs), ZERO)
    orders = Decimal(shopee[1]) if shopee else Decimal(len({ln.order_id for ln, _ in pairs}))
    if gmv == 0 and orders == 0 and pp is None:
        return None
    carrying = [(ln, pb) for ln, pb in pairs if pb.excluded_reason is None]
    discount = sum((pb.promo_discount + pb.voucher + pb.bundle for _, pb in pairs), ZERO)
    commission = sum((pb.commission or ZERO for _, pb in carrying), ZERO)
    spend = view.ads.product_spend.get(pid, ZERO)
    return M(
        gmv,
        orders,
        pp.profit if pp and pp.buyer_paid_covered > 0 else None,
        pp.buyer_paid_covered if pp else ZERO,
        discount,
        sum((pb.list_value for _, pb in pairs), ZERO),
        spend,
        spend + discount + commission,
    )


def _products(view: PeriodView, source: str, sub: str | None) -> Rows:
    ids = (
        set(view.matrix.totals) | set(view.data.product_flows.totals) | set(view.ads.product_spend)
    )
    if view.flows:
        ids |= set(view.flows.products)
    out: Rows = {}
    for pid in ids:
        m = _product_m(view, pid, source, sub)
        if m is not None:
            out[pid] = (view.names.get(pid) or pid, m, {"product_id": pid})
    return out


def _cell_products(view: PeriodView, source: str, sub: str | None) -> M:
    if source in LEVER_SOURCES:
        agg = CellStats()
        for (_, lv), c in view.matrix.lever.items():
            if lv == LEVER_KEY[source]:
                agg = agg.plus(c)
        return M(agg.gmv, Decimal(agg.orders), agg.profit, agg.buyer_paid_known)
    if sub:
        a = view.data.traffic.children.get(sub)
        return M(a.gmv if a else ZERO, a.orders if a else ZERO)
    if source in FLOW_SOURCES:
        row = view.flows.shop.row(source) if view.flows else None
        return M(row.gmv if row else ZERO, Decimal(row.orders) if row else ZERO)
    if source == "ads":
        d = view.data.ads_daily
        return M(d.gmv, d.orders, None, ZERO, spend=d.spend)
    p = view.profit
    discount = sum((pb.promo_discount + pb.voucher + pb.bundle for _, pb in view.pairs), ZERO)
    return M(
        view.shop_gmv or ZERO,
        Decimal(view.shop_orders or 0),
        p.covered_margin_profit if p.margin_is_partial else p.profit_on_covered,
        p.buyer_paid_covered,
        discount,
        sum((pb.list_value for _, pb in view.pairs), ZERO),
        view.ads.total_spend,
    )


def _campaigns(view: PeriodView) -> Rows:
    return {
        c.key: (
            c.name,
            M(
                c.gmv,
                c.orders,
                None,
                ZERO,
                spend=c.spend,
                extra={"direct_gmv": c.direct_gmv, "running": c.running, "clicks": c.clicks},
            ),
            {"campaign_key": c.key},
        )
        for c in view.ads.campaigns
    }


def _kols(view: PeriodView) -> Rows:
    return {
        p.key: (
            p.handle or p.key,
            M(
                p.gmv,
                p.orders,
                None,
                ZERO,
                extra={"est_commission": p.est_commission, "clicks": p.clicks},
            ),
            {"kol_key": p.key},
        )
        for p in view.data.affiliate.partners
    }


def _vouchers(view: PeriodView) -> Rows:
    out: Rows = {}
    for i, v in enumerate(
        sorted(view.data.vouchers.rows, key=lambda r: (r.name, str(r.starts_at)))
    ):
        key = f"{v.name}|{v.starts_at}"
        out[key] = (
            v.name,
            M(v.gmv, v.orders, None, ZERO, spend=v.cost),
            {"voucher_cost": v.cost, "ordinal": i},
        )
    return out


def _keywords(view: PeriodView) -> Rows:
    acc: dict[str, M] = defaultdict(M)
    names: dict[str, str] = {}
    for r in view.data.ads_reports.keyword_rows:
        label = r.campaign.rsplit(" › ", 1)[-1] if " › " in r.campaign else r.campaign
        key = f"{r.item_id}|{label}"
        names[key] = f"{label} · {view.names.get(r.item_id) or r.item_id}" if r.item_id else label
        m = acc[key]
        m.gmv += r.gmv
        m.orders += r.orders
        m.spend += r.spend
    return {k: (names[k], m, {"keyword": k.split("|", 1)[1]}) for k, m in acc.items()}


def _cell_other(kind: str, view: PeriodView) -> M:
    if kind == "campaigns" or kind == "keywords":
        d = view.data.ads_daily
        if d.complete:
            return M(d.gmv, d.orders, None, ZERO, spend=d.spend)
        return M(
            sum((c.gmv for c in view.ads.campaigns), ZERO),
            sum((c.orders for c in view.ads.campaigns), ZERO),
            None,
            ZERO,
            spend=view.ads.total_spend,
        )
    if kind == "kols":
        a = view.data.traffic.sources.get(FlowSource.LIEN_KET)
        return M(a.gmv if a else ZERO, a.orders if a else ZERO)
    # vouchers: orders that used a shop voucher, from the order lines
    voucher_pairs = [(ln, pb) for ln, pb in view.pairs if ln.shop_voucher_share > 0]
    return M(
        sum((ln.order_value for ln, _ in voucher_pairs), ZERO),
        Decimal(len({ln.order_id for ln, _ in voucher_pairs})),
    )


# ---- ranking ---------------------------------------------------------------------------


def _confidence(now: M | None, before: M | None) -> Confidence:
    return volume_label(
        float(before.orders) if before else 0.0, float(now.orders) if now else 0.0, CONFIG
    )


def _row_json(r: _Out, xep: str, days_now: int, days_before: int, ordered: bool) -> dict[str, Any]:
    a, b = _measure(r.now, xep, days_now), _measure(r.before, xep, days_before)
    delta = None if a is None and b is None else (a or ZERO) - (b or ZERO)
    conf = _confidence(r.now, r.before)
    extra = {k: (num(v) if isinstance(v, Decimal) else v) for k, v in r.extra.items()}
    return {
        "id": r.id,
        "label": r.label,
        "now": num(a),
        "before": num(b),
        "delta": num(delta),
        "quantity": {
            "orders_now": num(r.now.orders) if r.now else 0,
            "orders_before": num(r.before.orders) if r.before else 0,
        },
        "spend": num(r.now.spend) if r.now and r.now.spend else None,
        "confidence": conf.value,
        "before_missing": r.before is None,
        "link": {"kpi": xep, "focus": r.id},
        **extra,
    }


def _sum(rows: list[dict[str, Any]]) -> Decimal:
    return sum((Decimal(str(r["delta"] or 0)) for r in rows), ZERO)


def rank(
    *,
    kind: str,
    rows_now: Rows,
    rows_before: Rows,
    cell_now: M,
    cell_before: M | None,
    xep: str,
    days_now: int,
    days_before: int,
    source: str,
    sub: str | None,
) -> dict[str, Any]:
    noun, others_label, mix_label = NOUNS[kind]
    ids = list(dict.fromkeys([*rows_now, *rows_before]))
    outs = [
        _Out(
            i,
            (rows_now.get(i) or rows_before[i])[0],
            rows_now[i][1] if i in rows_now else None,
            rows_before[i][1] if i in rows_before else None,
            extra=(rows_now.get(i) or rows_before[i])[2],
        )
        for i in ids
    ]
    items = [_row_json(o, xep, days_now, days_before, True) for o in outs]
    items = [it for it in items if it["delta"] is not None or it["now"] is not None]
    cell_a, cell_b = _measure(cell_now, xep, days_now), _measure(cell_before, xep, days_before)
    cell_delta = None if cell_a is None else cell_a - (cell_b or ZERO)
    additive = xep in ADDITIVE

    few = [it for it in items if it["confidence"] == Confidence.INSUFFICIENT.value]
    rest = [it for it in items if it["confidence"] != Confidence.INSUFFICIENT.value and it["delta"]]
    threshold = Decimal(str(CONFIG.ranking_fold_share)) * abs(cell_delta or ZERO)

    def side(sign: int) -> list[dict[str, Any]]:
        got = [
            it
            for it in rest
            if Decimal(str(it["delta"])) * sign > 0 and abs(Decimal(str(it["delta"]))) >= threshold
        ]
        got.sort(key=lambda it: (it["confidence"] != Confidence.CLEAR.value, -abs(it["delta"])))
        return got[: CONFIG.ranking_max_rows]

    down, up = side(-1), side(1)
    shown = {id(it) for it in (*down, *up)}
    others = [it for it in rest if id(it) not in shown]
    zero_rows = [it for it in items if it not in few and it not in rest]
    mix = None
    if additive and cell_delta is not None:
        mix = cell_delta - _sum(items)
    closing: dict[str, dict[str, Any]] = {
        "few": {
            "label": f"{len(few)} {noun} ít đơn",
            "count": len(few),
            "delta": num(_sum(few)) if additive else None,
        },
        "others": {
            "label": others_label,
            "count": len(others) + len(zero_rows),
            "delta": num(_sum(others + zero_rows)) if additive else None,
        },
        "mix": {"label": mix_label, "delta": num(mix) if additive else None},
    }
    adds_up: bool | None = None
    views: dict[str, Any] = {}
    if additive and cell_delta is not None and mix is not None:
        total = _sum(down) + _sum(up) + _sum(few) + _sum(others + zero_rows) + mix
        adds_up = abs(total - cell_delta) < Decimal("0.01")
        for name, own, opposite in (("down", down, up), ("up", up, down)):
            lines: list[dict[str, Any]] = [
                {"label": closing["few"]["label"], "delta": closing["few"]["delta"]},
                {"label": others_label, "delta": closing["others"]["delta"]},
                {
                    "label": f"Các {noun} " + ("kéo lên" if name == "down" else "kéo xuống"),
                    "delta": num(_sum(opposite)),
                },
                {"label": mix_label, "delta": closing["mix"]["delta"]},
            ]
            views[name] = {
                "rows": own,
                "closing": lines,
                "sum": num(_sum(own) + sum((Decimal(str(x["delta"] or 0)) for x in lines), ZERO)),
                "cell_delta": num(cell_delta),
            }
    return {
        "supported": True,
        "cell": {"now": num(cell_a), "before": num(cell_b), "delta": num(cell_delta)},
        "down": down,
        "up": up,
        "closing": closing,
        "views": views,
        "adds_up": adds_up,
        "adds_up_note": None
        if additive
        else "Đại lượng tỷ lệ (biên, AOV, % giảm giá, thu thêm / chi thêm) không cộng được; "
        "chỉ xếp theo thay đổi.",
        "row_count": len(items),
    }


def build_ranking(
    now: PeriodView,
    before: PeriodView,
    *,
    kind: str = "products",
    source: str = "all",
    sub: str | None = None,
    xep_theo: str = "gmv_per_day",
) -> dict[str, Any]:
    head: dict[str, Any] = {
        "platform": "shopee",
        "kind": kind,
        "source": source,
        "sub": sub,
        "xep_theo": {
            "key": xep_theo,
            "label": XEP_LABELS.get(xep_theo, xep_theo),
            "additive": xep_theo in ADDITIVE,
        },
        "window": now.window.json(),
        "previous": before.window.json(),
        "order_basis": {"key": "confirmed", "label": "Đơn đã xác nhận"},
        "ads_basis": ADS_BASIS if source == "ads" or kind in ("campaigns", "keywords") else None,
        "ads_note": ADS_BASIS_NOTE
        if source == "ads" or kind in ("campaigns", "keywords")
        else None,
    }

    def refuse(reason: str, message: str) -> dict[str, Any]:
        return {**head, "supported": False, "reason": reason, "message": message}

    if kind not in KINDS:
        return refuse("unknown_kind", f"kind phải là một trong {list(KINDS)}")
    if source not in SOURCES:
        return refuse("unknown_source", f"source phải là một trong {list(SOURCES)}")
    if xep_theo not in XEP_THEO:
        return refuse("unknown_xep_theo", f"xep_theo phải là một trong {list(XEP_THEO)}")
    if sub is not None and (source != "the_san_pham_khac" or sub not in CARD_CHILDREN):
        return refuse("unknown_sub", f"sub chỉ dùng với the_san_pham_khac: {list(CARD_CHILDREN)}")
    if source not in SUPPORTED[kind]:
        return refuse("source_not_supported", f"{kind} không tách được theo nguồn {source}")
    if xep_theo not in RANKABLE[kind]:
        return refuse("xep_theo_not_supported", f"{kind} không xếp được theo {xep_theo}")
    if source in FLOW_SOURCES and xep_theo in ("profit_per_day", "bien", "giam_gia", "thu_them"):
        return refuse(
            "not_split_by_flow",
            "Lợi nhuận, biên, % giảm giá và thu thêm / chi thêm không tách được theo luồng lưu "
            "lượng "
            "(đơn hàng không ghi nguồn lưu lượng).",
        )
    if source == "ads" and xep_theo not in ("gmv_per_day",):
        return refuse("ads_only_gmv", "Quảng cáo (đơn đã đặt) chỉ xếp được theo ₫ GMV / ngày.")

    if kind == "products":
        rn, rb = _products(now, source, sub), _products(before, source, sub)
        cn, cb = _cell_products(now, source, sub), _cell_products(before, source, sub)
    else:
        build: dict[str, Callable[[PeriodView], Rows]] = {
            "campaigns": _campaigns,
            "kols": _kols,
            "vouchers": _vouchers,
            "keywords": _keywords,
        }
        rn, rb = build[kind](now), build[kind](before)
        cn, cb = _cell_other(kind, now), _cell_other(kind, before)
        same_report = {
            "campaigns": now.data.ads_reports.campaign_choice.periods
            == before.data.ads_reports.campaign_choice.periods,
            "keywords": now.data.ads_reports.keyword_choice.periods
            == before.data.ads_reports.keyword_choice.periods,
            "kols": now.data.affiliate.choice.periods == before.data.affiliate.choice.periods,
            "vouchers": now.data.vouchers.choice.periods == before.data.vouchers.choice.periods,
        }[kind]
        if same_report and kind != "campaigns":
            rb = {}
            head["before_note"] = "Kỳ trước dùng cùng một báo cáo nên không có số kỳ trước riêng."
    result = rank(
        kind=kind,
        rows_now=rn,
        rows_before=rb,
        cell_now=cn,
        cell_before=cb,
        xep=xep_theo,
        days_now=now.window.days,
        days_before=before.window.days,
        source=source,
        sub=sub,
    )
    return {**head, **result}
