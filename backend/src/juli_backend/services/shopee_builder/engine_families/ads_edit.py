"""P100 B.15: an edit of a running Dịch vụ hiển thị campaign (``specs.AdsSpec``) -> ``OptionInput``.

Everything comes from the campaign's own measured history (never a prior):

- **Today** = the campaign's spend, direct ad orders and Shopee ad GMV per running day, over the
  option's days. Ad orders are placed orders × (1 − the shop's cancel rate).
- **After**, per lever: ``budget`` -- the new daily budget is the input; spend follows it only up
  to what the campaign spends when its budget does not hold it back (``measure.budget_state``);
  ``roas`` -- spend = daily budget × the share of the budget Shopee spent at a similar ROAS target
  (``measure.spend_utilisation``); ``remove_product`` -- the campaign loses that product's share
  of its spend / orders / GMV (the per-product lines of the ads report); ``add_product`` -- the
  product's own ad spend and CPA where it was advertised before. Orders after = spend after ÷ the
  measured CPA (the product's own CPA for add / remove).
- **Verdict**: CPA vs break-even CPA (= profit per order before ads of the campaign's products);
  profit after ads = ad orders × (break-even CPA − CPA). Shopee ROAS = ad GMV ÷ spend (reference).
- **Δ total profit / ROI** (the engine) come from the INCREMENTAL orders only: Δ ad orders × the
  share measured on the products' days with vs without ads (``measure.incremental_share``),
  each worth the profit per order before ads, minus Δ spend.
- Anything unmeasured -> the driver is ``not_estimable`` with the exact cost (or the maximum the
  edit can spend), and the evaluation says why.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_builder.engine.contract import (
    CARD_SOURCES,
    AddedTraffic,
    AdsEvaluation,
    Band,
    DriverEffect,
    OptionInput,
)
from juli_backend.services.shopee_builder.engine.vn import vnd
from juli_backend.services.shopee_builder.engine_families import common, measure
from juli_backend.services.shopee_builder.engine_families.common import point
from juli_backend.services.shopee_builder.engine_families.facts import AdsEditFacts, ProductAdRow

ZERO = Decimal(0)
ONE = Decimal(1)
DEFAULT_DAYS = 30
KIND_LABEL = "Dịch vụ hiển thị"

NOTE_NO_CANCEL_RATE = (
    "Chưa có tỉ lệ huỷ của shop (chưa có số đơn đã đặt và đã xác nhận của Tổng quan): "
    "số đơn quảng cáo là đơn đã đặt, chưa trừ đơn huỷ."
)
NOTE_NO_INCREMENTAL = (
    "chưa ước tính được — chưa đủ ngày có và không có quảng cáo để đo số đơn tăng thêm"
)
NOTE_NO_HISTORY = "Chiến dịch chưa có chi phí và đơn trong 30 ngày: chưa đo được CPA."
CHANGE_KINDS = {
    "budget": "ads_budget",
    "roas": "ads_roas_target",
    "add_product": "ads_add_product",
    "remove_product": "ads_remove_product",
}


def _pct(x: Decimal) -> str:
    return f"{float(x) * 100:.0f}%"


@dataclass(frozen=True)
class _Flow:
    """Ad traffic per running day (or a change of it): spend, impressions, clicks, direct orders
    (confirmed: × (1 − cancel rate)), direct GMV and Shopee's ad GMV (placed)."""

    spend: Decimal
    impressions: Decimal
    clicks: Decimal
    orders: Decimal
    direct_gmv: Decimal
    gmv: Decimal

    def times(self, k: Decimal) -> _Flow:
        return _Flow(
            self.spend * k,
            self.impressions * k,
            self.clicks * k,
            self.orders * k,
            self.direct_gmv * k,
            self.gmv * k,
        )

    def plus(self, o: _Flow) -> _Flow:
        return _Flow(
            self.spend + o.spend,
            self.impressions + o.impressions,
            self.clicks + o.clicks,
            self.orders + o.orders,
            self.direct_gmv + o.direct_gmv,
            self.gmv + o.gmv,
        )


def _rows_flow(rows: list[ProductAdRow], keep: Decimal) -> _Flow:
    """The product lines' traffic per day of their reports' periods."""
    out = _Flow(ZERO, ZERO, ZERO, ZERO, ZERO, ZERO)
    for r in rows:
        n = Decimal(max(1, r.days))
        out = out.plus(
            _Flow(
                r.spend / n,
                r.impressions / n,
                r.clicks / n,
                r.direct_orders * keep / n,
                r.direct_gmv / n,
                r.gmv / n,
            )
        )
    return out


def _share(part: Decimal, whole: Decimal) -> Decimal:
    return part / whole if whole > 0 else ZERO


@dataclass(frozen=True)
class _After:
    """The lever's answer: the change of the per-day flow (None = not estimable), the most it can
    spend extra over the option's days when not estimable, and the sentence that says how."""

    delta: _Flow | None
    basis: str
    text: str
    max_cost: Decimal = ZERO


def _budget(spec: sp.AdsSpec, now: _Flow, state: measure.BudgetState) -> _After:
    new = None if spec.unlimited else Decimal(spec.daily_budget or 0)
    r, u = state.rate, state.uncapped_rate
    spend: Decimal | None
    if not state.capped:
        assert u is not None  # budget_state gives an uncapped campaign its own rate
        basis = "not_capped"
        if new is None:
            spend = u
            text = (
                f"Chiến dịch chưa tiêu hết ngân sách (chi {vnd(u)}/ngày khi không chạm ngân "
                "sách): bỏ giới hạn ngân sách giữ mức chi này."
            )
        elif new >= u:
            spend = u
            text = (
                f"Chiến dịch chưa tiêu hết ngân sách (thực chi {vnd(u)}/ngày): ngân sách mới "
                f"{vnd(new)}/ngày không làm tăng chi tiêu."
            )
        else:
            spend = new
            text = (
                f"Ngân sách mới {vnd(new)}/ngày thấp hơn mức chiến dịch thực chi "
                f"({vnd(u)}/ngày): chi tiêu bằng ngân sách mới."
            )
    else:
        basis = "budget_capped"
        free = u if u is not None and u > r else None
        if new is not None and new <= r:
            spend = new
            text = (
                "Chiến dịch đang tiêu hết ngân sách mỗi ngày: chi tiêu theo ngân sách mới "
                f"{vnd(new)}/ngày."
            )
        elif free is not None:
            spend = free if new is None else min(new, free)
            text = (
                "Chiến dịch đang tiêu hết ngân sách; những ngày không chạm ngân sách chi "
                f"{vnd(free)}/ngày: chi tiêu tăng tối đa đến mức đó."
            )
        elif new is not None:
            spend = new
            text = (
                "Chiến dịch đang tiêu hết ngân sách mỗi ngày: tính là chi hết ngân sách mới "
                f"{vnd(new)}/ngày (chi phí tối đa); CPA đo ở mức chi hiện tại, chi nhiều hơn "
                "có thể làm CPA tăng."
            )
        else:
            return _After(
                None,
                "not_estimable",
                "Chiến dịch đang tiêu hết ngân sách mỗi ngày: chưa đo được mức chi khi không "
                "giới hạn ngân sách.",
            )
    return _After(_scaled_spend(now, spend), basis, text)


def _scaled_spend(now: _Flow, spend: Decimal) -> _Flow:
    """The change when spend per day becomes ``spend`` at the campaign's measured CPM / CTR /
    CPA (traffic and orders in proportion to spend)."""
    if now.spend <= 0:
        return _Flow(ZERO, ZERO, ZERO, ZERO, ZERO, ZERO)
    return now.times(spend / now.spend - ONE)


def _roas(spec: sp.AdsSpec, f: AdsEditFacts, now: _Flow, days: Decimal) -> _After:
    budget = f.daily_budget
    if spec.roas_mode == "system":
        util = measure.spend_utilisation_system(f.campaigns)
        target = "ROAS do Shopee tối ưu"
    else:
        assert spec.roas_target is not None
        util = measure.spend_utilisation(f.campaigns, Decimal(str(spec.roas_target)))
        target = f"ROAS mục tiêu {spec.roas_target:g}".replace(".", ",")
    if budget is None or budget <= 0:
        return _After(
            None,
            "not_estimable",
            "Chiến dịch không giới hạn ngân sách: chưa đo được mức chi ở " + target + ".",
        )
    if util is None:
        return _After(
            None,
            "not_estimable",
            f"Chưa có lịch sử ở {target} tương tự: chưa ước tính được; chi phí tối đa là tiêu "
            f"hết ngân sách {vnd(budget)}/ngày.",
            max(ZERO, budget - now.spend) * days,
        )
    spend = budget * util
    return _After(
        _scaled_spend(now, spend),
        "roas_history",
        f"Ở {target} tương tự, Shopee đã tiêu {_pct(util)} ngân sách: chi {vnd(spend)}/ngày "
        f"trên ngân sách {vnd(budget)}/ngày.",
    )


def _remove(spec: sp.AdsSpec, f: AdsEditFacts, now: _Flow, capped: bool) -> _After:
    key = f.campaign.key if f.campaign is not None else spec.campaign_key
    rows = [r for r in f.product_rows if r.campaign_key == key]
    if not rows:
        return _After(
            None,
            "not_estimable",
            "Chưa có báo cáo quảng cáo theo sản phẩm của chiến dịch: chưa tách được phần của "
            "sản phẩm này.",
        )
    mine = [r for r in rows if r.item_id == spec.item_id]
    if not mine:
        return _After(
            _Flow(ZERO, ZERO, ZERO, ZERO, ZERO, ZERO),
            "product_rows",
            "Sản phẩm chưa có chi phí trong chiến dịch: bỏ ra không đổi chi tiêu.",
        )

    def share(attr: str) -> Decimal:
        part = sum((getattr(r, attr) for r in mine), ZERO)
        return _share(part, sum((getattr(r, attr) for r in rows), ZERO))

    s_spend = share("spend")
    s_orders = share("direct_orders")
    delta = _Flow(
        -now.spend * s_spend,
        -now.impressions * share("impressions"),
        -now.clicks * share("clicks"),
        -now.orders * s_orders,
        -now.direct_gmv * share("direct_gmv"),
        -now.gmv * share("gmv"),
    )
    text = (
        f"Sản phẩm chiếm {_pct(s_spend)} chi phí và {_pct(s_orders)} đơn trực tiếp của chiến "
        "dịch (báo cáo theo sản phẩm): chiến dịch mất phần này."
    )
    if capped:
        text += (
            " Chiến dịch đang tiêu hết ngân sách: phần ngân sách này có thể chuyển sang sản "
            "phẩm khác."
        )
    return _After(delta, "product_rows", text)


def _add(
    spec: sp.AdsSpec,
    f: AdsEditFacts,
    now: _Flow,
    state: measure.BudgetState,
    keep: Decimal,
    days: Decimal,
) -> _After:
    key = f.campaign.key if f.campaign is not None else spec.campaign_key
    if any(r.campaign_key == key and r.item_id == spec.item_id for r in f.product_rows):
        return _After(
            _Flow(ZERO, ZERO, ZERO, ZERO, ZERO, ZERO),
            "product_rows",
            "Sản phẩm đã có trong chiến dịch: không đổi chi tiêu.",
        )
    budget = f.daily_budget
    room = None if budget is None else max(ZERO, budget - now.spend)
    if budget is not None and state.capped:
        return _After(
            None,
            "not_estimable",
            "Chiến dịch đang tiêu hết ngân sách: thêm sản phẩm chỉ chia lại ngân sách hiện có, "
            "chưa đo được phần chia lại.",
        )
    past = [r for r in f.product_rows if r.item_id == spec.item_id and r.spend > 0]
    if not past:
        return _After(
            None,
            "not_estimable",
            "Sản phẩm chưa từng chạy quảng cáo: chưa đo được CPA của sản phẩm"
            + (
                "."
                if room is None
                else f"; chi phí tối đa là phần ngân sách chưa dùng {vnd(room)}/ngày."
            ),
            ZERO if room is None else room * days,
        )
    own = _rows_flow(past, keep)
    if own.orders <= 0:
        return _After(
            None,
            "not_estimable",
            "Sản phẩm đã chạy quảng cáo nhưng chưa có đơn trực tiếp: chưa đo được CPA.",
            own.spend * days if room is None else min(own.spend, room) * days,
        )
    k = ONE if room is None or own.spend <= room else room / own.spend
    delta = own.times(k)
    text = (
        f"Sản phẩm đã chạy quảng cáo: chi {vnd(own.spend)}/ngày, CPA {vnd(own.spend / own.orders)} "
        "(đo trên chính sản phẩm này)."
    )
    if k < ONE:
        text += f" Phần ngân sách còn trống chỉ {vnd(room or ZERO)}/ngày: chi tăng tối đa đến đó."
    return _After(delta, "product_rows", text)


def _days(spec: sp.AdsSpec) -> int | None:
    if spec.start and spec.end:
        return (spec.end - spec.start).days + 1
    return None


def ads_edit_option(spec: sp.AdsSpec, f: AdsEditFacts) -> OptionInput:
    """One edit of one running campaign (``multi.expand`` splits ``campaign_keys``)."""
    duration = _days(spec)
    days = Decimal(duration or DEFAULT_DAYS)
    keep = ONE if f.cancel_rate is None else ONE - common.clamp01(f.cancel_rate)
    notes: list[str] = []
    if f.cancel_rate is None:
        notes.append(NOTE_NO_CANCEL_RATE)
    label = spec.label or f"{KIND_LABEL} · {f.name}"
    kind = CHANGE_KINDS[spec.lever]
    c = f.campaign
    state = None if c is None else measure.budget_state(c.spend, c.days, f.daily_budget, f.daily)
    if c is None or state is None or c.direct_orders <= 0 or c.clicks <= 0 or c.impressions <= 0:
        cost = ZERO
        if spec.lever == "budget" and spec.daily_budget is not None:
            cost = Decimal(spec.daily_budget) * days - (
                ZERO if state is None else state.rate * days
            )
        return OptionInput(
            kind=kind,
            label=label,
            drivers=(
                DriverEffect(
                    "views", CARD_SOURCES, "not_estimable", note=common.NOTE_ADS_NOT_ESTIMABLE
                ),
            ),
            duration_days=duration,
            fixed_cost=cost,
            note=" ".join([NOTE_NO_HISTORY, *notes]),
        )
    n = Decimal(state.running_days)
    now = _Flow(
        c.spend / n,
        c.impressions / n,
        c.clicks / n,
        c.direct_orders * keep / n,
        c.direct_gmv / n,
        (c.gmv if c.gmv is not None else c.direct_gmv) / n,
    )
    if spec.lever == "budget":
        after = _budget(spec, now, state)
    elif spec.lever == "roas":
        after = _roas(spec, f, now, days)
    elif spec.lever == "remove_product":
        after = _remove(spec, f, now, state.capped)
    else:
        after = _add(spec, f, now, state, keep, days)
    share = measure.incremental_share(f.days)
    ppo = f.profit_per_order_before_ads
    total_now = now.times(days)
    d = None if after.delta is None else after.delta.times(days)
    evaluation = AdsEvaluation(
        lever=spec.lever,
        campaign=f.name,
        days=int(days),
        spend_basis=after.basis,
        spend_text=after.text,
        spend_now=total_now.spend,
        spend_after=None if d is None else total_now.spend + d.spend,
        orders_now=total_now.orders,
        orders_after=None if d is None else total_now.orders + d.orders,
        gmv_now=total_now.gmv,
        gmv_after=None if d is None else total_now.gmv + d.gmv,
        break_even_cpa=ppo,
        incremental_share=share,
        cancel_rate=f.cancel_rate,
    )
    driver: DriverEffect
    if d is None:
        driver = DriverEffect(
            "views", CARD_SOURCES, "not_estimable", note=common.NOTE_ADS_NOT_ESTIMABLE
        )
        cost = after.max_cost
    else:
        cost = d.spend
        traffic = _traffic(d, share, ppo, keep)
        if share is None or traffic is None:
            # cost and break-even only: the break-even counts orders worth the profit before ads
            zero = (
                None
                if traffic is None
                else AddedTraffic(
                    point(ZERO), traffic.ctr, traffic.ctor, traffic.aov, point(ZERO), ppo
                )
            )
            driver = DriverEffect(
                "views",
                CARD_SOURCES,
                "not_estimable",
                added=zero,
                note=NOTE_NO_INCREMENTAL if share is None else common.NOTE_ADS_NOT_ESTIMABLE,
            )
        else:
            driver = DriverEffect("views", CARD_SOURCES, "measured", added=traffic)
    return OptionInput(
        kind=kind,
        label=label,
        drivers=(driver,),
        duration_days=duration,
        fixed_cost=cost,
        note=" ".join([after.text, *notes]),
        ads=evaluation,
    )


def _traffic(
    d: _Flow, share: Band | None, ppo: Decimal | None, keep: Decimal
) -> AddedTraffic | None:
    """The change as added (or removed) card traffic: views = Δ impressions with the change's own
    CTR / CTOR / AOV, so views × CTR × CTOR = Δ ad orders and × the share = the extra orders."""
    if d.impressions == 0 or d.clicks == 0 or d.orders == 0:
        if share is None:
            return None
        # nothing changes (a budget above what the campaign spends, a product not in it)
        return AddedTraffic(point(ZERO), ONE, ONE, ONE, share, ppo)
    return AddedTraffic(
        point(d.impressions),
        d.clicks / d.impressions,
        d.orders / d.clicks,
        d.direct_gmv * keep / d.orders,  # placed direct GMV per placed order
        share or point(ZERO),
        ppo,
    )


__all__ = ["CHANGE_KINDS", "NOTE_NO_CANCEL_RATE", "NOTE_NO_INCREMENTAL", "ads_edit_option"]
