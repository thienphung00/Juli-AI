"""The advisor's tools (#62, C1): thin readers over `DataPort.metrics` (= `metrics.query.query`),
the stored opportunities and OPP's `compare` / `draft_card`.

`metrics`, `rank`, `opportunities`, `open_cards`, `calendar`, `draft_card`, `compare`, `emit_plan`.
No calculation lives here: a value is what `query()` returned, a rank is an order over returned
rows, a filter is a comparison of returned values. The schemas are generated from the registry
(metric ids) and the kinds table (levers), never written per question (#53).
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from juli_backend.services.analytics_agent import cards as cardstage
from juli_backend.services.analytics_agent import compare as compare_mod
from juli_backend.services.analytics_agent import fmt, levers
from juli_backend.services.analytics_agent.windows import campaign_days
from juli_backend.services.metrics.registry import METRICS, Level

if TYPE_CHECKING:
    from juli_backend.services.analytics_agent.advisor import Ctx

UPCOMING_DAYS = 21  # the sale calendar the model sees ahead (double days, 15th, 25th)
MAX_RANK = 8
MAX_IDS = 8
MAX_DRAFTS = 3

#: The windows a tool may read (a validated enum; the model never writes a date).
WINDOWS = (
    "last_full_week_vs_week_before",
    "last_7d_vs_prev_7d",
    "last_30d_vs_prev_30d",
    "mtd_vs_same_days_last_month",
    "last_month_vs_month_before",
)
DEFAULT_WINDOW = WINDOWS[0]
BY = ("item", "campaign", "channel", "day")
OPS = ("lt", "gt")
SCOPES = ("shop", "products")

NO_PLAN_TOOL_VI = "Juli chưa tính được phương án cho việc này"
NO_OPPORTUNITY_VI = "chưa có cơ hội"
OUTCOME_VI = {
    "published": "đã có cơ hội",
    "ranked_out": "có tính nhưng xếp dưới các việc khác",
    "below_band": "lợi ích chưa đủ để đề xuất",
    "refused": "Juli không đề xuất việc này",
    "duplicate": "trùng với thẻ đã có",
}
#: Why an opportunity has no card (OPP reason codes), in words the model can act on.
NO_DRAFT_REASON_VI = {
    "kind_needs_a_product": "lever này cần item: truyền id một sản phẩm đã thấy ở công cụ khác",
    "generator_returned_none": "engine chưa thấy cơ hội cho lever này ở sản phẩm này",
    "not_estimable": "chưa đủ dữ liệu để tính thẻ này",
    "no_shopee_data": "chưa có dữ liệu Shopee",
    "no_generator_for_kind": "Juli chưa tạo được thẻ loại này",
}


def metric_ids() -> list[str]:
    """The registry ids a shop-level answer may ask for (generated, not hand-written): shop level,
    no share-of-revenue duplicates, no dates / statuses."""
    return [
        m
        for m, d in METRICS.items()
        if Level.shop in d.levels
        and d.unit.value not in ("date", "status", "days")
        and not m.endswith("_pct")
        and m not in ("contribution_rate", "margin_sale")
    ]


def reason_vi(reason: Any) -> str:
    r = str(reason or "")
    return NO_DRAFT_REASON_VI.get(r.split(":")[0], r if " " in r else "chưa tính được thẻ")


# ------------------------------------------------------------------ schemas

_NO_ARGS: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}
_WINDOW_PROP = {
    "type": "string",
    "enum": list(WINDOWS),
    "description": "kỳ so sánh (chọn một giá trị trong danh sách)",
}


def specs(kinds: list[str]) -> list[dict[str, Any]]:
    ids = metric_ids()
    cards = levers.card_kinds(kinds)
    metric = {"type": "string", "enum": ids}
    item = {"type": ["string", "null"], "description": "id sản phẩm lấy từ kết quả công cụ khác"}
    return [
        {
            "name": "metrics",
            "description": "Các chỉ số (id registry) của cả shop hoặc của sản phẩm trong một kỳ, "
            "kèm kỳ trước.",
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["ids", "window"],
                "properties": {
                    "ids": {"type": "array", "maxItems": MAX_IDS, "items": metric},
                    "window": _WINDOW_PROP,
                    "scope": {"type": "string", "enum": list(SCOPES)},
                    "items": {"type": "array", "maxItems": MAX_RANK, "items": item},
                },
            },
        },
        {
            "name": "rank",
            "description": "Xếp hạng theo một chỉ số: sản phẩm, chiến dịch, kênh hoặc ngày; có "
            "thể lọc (chỉ số nhỏ/lớn hơn một giá trị hoặc một chỉ số khác, ví dụ ROAS dưới ROAS "
            "hoà vốn, độ phủ giá vốn dưới 1).",
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["metric", "by", "window"],
                "properties": {
                    "metric": metric,
                    "by": {"type": "string", "enum": list(BY)},
                    "window": _WINDOW_PROP,
                    "n": {"type": "integer", "minimum": 1, "maximum": MAX_RANK},
                    "order": {"type": "string", "enum": ["desc", "asc"]},
                    "filter": {
                        "type": ["object", "null"],
                        "additionalProperties": False,
                        "required": ["metric", "op"],
                        "properties": {
                            "metric": metric,
                            "op": {"type": "string", "enum": list(OPS)},
                            "value": {"type": ["number", "null"]},
                            "than": {"type": ["string", "null"], "enum": [*ids, None]},
                        },
                    },
                },
            },
        },
        {
            "name": "opportunities",
            "description": "Cơ hội Juli đã tính sẵn (lever, sản phẩm, lợi nhuận tăng thêm, chi "
            "phí, kết quả và lý do). Mỗi lever hỏi đến đều có kết quả: chưa có cơ hội cũng là "
            "một câu trả lời.",
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "lever": {"type": ["string", "null"], "enum": [*cards, None]},
                    "item": item,
                },
            },
        },
        {
            "name": "open_cards",
            "description": "Các thẻ đang có trong Đề xuất (mã thẻ, loại, sản phẩm).",
            "input_schema": _NO_ARGS,
        },
        {
            "name": "calendar",
            "description": "Ngày sale sắp tới trong lịch (ngày đôi, 15, 25) và kỳ có ngày sale.",
            "input_schema": _NO_ARGS,
        },
        {
            "name": "draft_card",
            "description": "Tạo thẻ nháp (không gửi) từ một cơ hội đã đọc ở công cụ opportunities; "
            "trả card_ref để dùng trong emit_plan, hoặc báo đã có thẻ / chưa có cơ hội.",
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["opportunity_id"],
                "properties": {"opportunity_id": {"type": "string"}},
            },
        },
        {
            "name": "compare",
            "description": "So sánh đúng 4 phương án (cùng một loại thẻ, hoặc 4 lever khác "
            "nhau): cùng ba số (GMV tăng, lợi nhuận tăng, chi phí), một phương án được chọn.",
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "kind": {"type": ["string", "null"], "enum": [*cards, None]},
                    "levers": {
                        "type": "array",
                        "maxItems": 4,
                        "items": {"type": "string", "enum": cards},
                    },
                    "item": item,
                },
            },
        },
    ]


# ------------------------------------------------------------------ helpers


def preset(a: dict[str, Any]) -> str:
    """The window a tool reads: the last full week unless the model names one from the enum."""
    p = a.get("window") or DEFAULT_WINDOW
    if p not in WINDOWS:
        raise ValueError("bad_argument")
    return str(p)


def _ids(a: dict[str, Any], key: str = "ids") -> list[str]:
    ids = [str(i) for i in (a.get(key) or [])][:MAX_IDS]
    valid = set(metric_ids())
    if not ids or any(i not in valid for i in ids):
        raise ValueError("bad_argument")
    return ids


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


def _known(ctx: Ctx, item: Any) -> str | None:
    """An item id must come from an earlier tool result; anything else is refused."""
    if item in (None, ""):
        return None
    if str(item) not in ctx.known_items:
        raise ValueError("unknown_item")
    return str(item)


def _label(ctx: Ctx, metric_id: str) -> str:
    return (
        ctx.labels.metric(metric_id)
        if metric_id in ctx.labels.metrics
        else METRICS[metric_id].label_vi
    )


# ------------------------------------------------------------------ tools


async def metrics(ctx: Ctx, a: dict[str, Any]) -> dict[str, Any]:
    ids = _ids(a)
    scope = str(a.get("scope") or "shop")
    if scope not in SCOPES:
        raise ValueError("bad_argument")
    items = [i for i in (_known(ctx, x) for x in (a.get("items") or [])) if i]
    if scope == "products" and not items:
        raise ValueError("bad_argument")
    w = await ctx.window(preset(a))
    res = await ctx.data.metrics(ids, *w.cur, scope=scope, items=items or None)
    prev: dict[str, Any] = {}
    if w.prev is not None:  # the window the comparison names (sale-aware), not "the days before"
        prev = (await ctx.data.metrics(ids, *w.prev, scope=scope, items=items or None)).get(
            "values"
        ) or {}
    cov = res.get("coverage") or {}
    rows = []
    for i in ids:
        now = _f((res.get("values") or {}).get(i))
        row: dict[str, Any] = {"id": i, "tên": _label(ctx, i), "giá_trị": fmt.value_id(i, now)}
        if i in prev:
            old = _f(prev.get(i))
            row["kỳ_trước"] = fmt.value_id(i, old)
            row["thay_đổi"] = fmt.delta_id(i, now, old)["text_vi"]
        if cov.get(i) is not None and cov[i] < 1:
            row["phủ_dữ_liệu"] = fmt.value_id("cost_coverage", float(cov[i]))
        rows.append(row)
    names = await ctx.data.item_names(items) if items else {}
    for i in items:
        ctx.see(i, names.get(i))
    out: dict[str, Any] = {
        **ctx.head(w),
        "phạm_vi": ", ".join(names.get(i, i) for i in items) if items else "cả shop",
        "chỉ_số": rows,
    }
    if res.get("partial"):
        out["một_phần_dữ_liệu"] = True
    return out


def _passes(row: dict[str, Any], flt: dict[str, Any] | None) -> bool:
    """The filter is a comparison of two returned values; a missing value never passes."""
    if not flt:
        return True
    lhs = _f(row.get(flt["metric"]))
    rhs = _f(row.get(flt["than"])) if flt.get("than") else _f(flt.get("value"))
    if lhs is None or rhs is None:
        return False
    return lhs < rhs if flt["op"] == "lt" else lhs > rhs


async def rank(ctx: Ctx, a: dict[str, Any]) -> dict[str, Any]:
    metric = str(a.get("metric") or "")
    by = str(a.get("by") or "")
    if metric not in metric_ids() or by not in BY:
        raise ValueError("bad_argument")
    flt = a.get("filter") or None
    ids = [metric]
    if flt:
        if flt.get("metric") not in metric_ids() or flt.get("op") not in OPS:
            raise ValueError("bad_argument")
        than = flt.get("than")
        if than is not None and than not in metric_ids():
            raise ValueError("bad_argument")
        ids += [x for x in (flt["metric"], than) if x and x not in ids]
    n = min(int(a.get("n") or 5), MAX_RANK)
    w = await ctx.window(preset(a))
    res = await ctx.data.metrics(ids, *w.cur, scope="shop", group_by=by)
    rows = [r for r in res.get("rows", []) if _passes(r, flt)]
    desc = a.get("order") != "asc"
    have = [r for r in rows if r.get(metric) is not None]
    missing = [r for r in rows if r.get(metric) is None]
    have.sort(key=lambda r: float(r[metric]), reverse=desc)  # an order over returned rows
    picked = (have + missing)[:n]
    names: dict[str, str] = {}
    if by == "item":
        names = await ctx.data.item_names([str(r["item"]) for r in picked])
    products = await ctx.data.campaign_products(*w.cur) if by == "campaign" else {}
    out_rows = []
    for r in picked:
        key = str(r.get(by) if by != "item" else r["item"])
        row: dict[str, Any] = {"id": key}
        if by == "item":
            ctx.see(key, names.get(key))
            row["tên"] = names.get(key, key)
        elif by == "campaign":
            nm = str(r.get("campaign_name") or key)
            ctx.names.setdefault(key, nm)
            row["tên"] = nm
            ids_ = products.get(key, [])
            if ids_:  # the products it spends on: item ids draft / opportunities can take
                inames = await ctx.data.item_names(ids_)
                for i in ids_:
                    ctx.see(i, inames.get(i))
                row["sản_phẩm_chạy_quảng_cáo"] = [{"id": i, "tên": inames.get(i, i)} for i in ids_]
        elif by == "day":
            row["ngày"] = f"{r['day']:%d/%m}" if hasattr(r.get("day"), "strftime") else str(key)
        for i in ids:
            row[_label(ctx, i)] = fmt.value_id(i, _f(r.get(i)))
        out_rows.append(row)
    out: dict[str, Any] = {**ctx.head(w), "xếp_theo": _label(ctx, metric), "dòng": out_rows}
    if metric == "cost_coverage" and out_rows:
        out["thiếu_giá_vốn"] = [{"id": r["id"], "tên": r.get("tên", r["id"])} for r in out_rows]
    return out


def _opp_row(ctx: Ctx, o: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    item_ids = [str(i) for i in (o.get("item_ids") or [])]
    row: dict[str, Any] = {
        "mã": str(o.get("id")),
        "lever": o.get("kind"),
        "kết_quả": OUTCOME_VI.get(str(o.get("outcome")), str(o.get("outcome"))),
        "sản_phẩm": [{"id": i, "tên": names.get(i, i)} for i in item_ids] or None,
        "GMV_tăng": fmt.value_id("gmv", _f(o.get("delta_gmv"))),
        "lợi_nhuận_tăng": fmt.value_id("profit", _f(o.get("delta_profit"))),
        "chi_phí": fmt.value_id("cost_ads", _f(o.get("cost"))),
    }
    if o.get("outcome") != "published" and o.get("reason"):
        row["lý_do"] = reason_vi(o["reason"])
    if o.get("card_code"):
        row["thẻ"] = f"open:{o['card_code']}"
    return {k: v for k, v in row.items() if v is not None}


async def opportunities(ctx: Ctx, a: dict[str, Any]) -> dict[str, Any]:
    lever = a.get("lever") or None
    if lever is not None and lever not in levers.card_kinds(ctx.labels.kinds):
        raise ValueError("bad_argument")
    item = _known(ctx, a.get("item"))
    rows = await ctx.data.opportunities(kind=lever, item=item)
    ids = sorted({str(i) for o in rows for i in (o.get("item_ids") or [])})
    names = await ctx.data.item_names(ids) if ids else {}
    for i in ids:
        ctx.see(i, names.get(i))
    for o in rows:
        ctx.opps[str(o.get("id"))] = o
    # published first, then by profit gain: an order over the stored rows
    rows.sort(key=lambda o: (o.get("outcome") != "published", -(_f(o.get("delta_profit")) or 0.0)))
    out: dict[str, Any] = {"cơ_hội": [_opp_row(ctx, o, names) for o in rows[:MAX_RANK]]}
    if not rows:  # C3: no row = the answer, nothing is run
        out["kết_quả"] = NO_OPPORTUNITY_VI
        if lever:
            out["lever"] = lever
    return out


async def calendar(ctx: Ctx, _a: dict[str, Any]) -> dict[str, Any]:
    w = await ctx.window(DEFAULT_WINDOW)
    ahead = campaign_days(ctx.as_of + timedelta(days=1), ctx.as_of + timedelta(days=UPCOMING_DAYS))
    return {**ctx.head(w), "ngày_sale_sắp_tới": [f"{d:%d/%m}" for d in ahead]}


async def draft_card(ctx: Ctx, a: dict[str, Any]) -> dict[str, Any]:
    """A draft from a stored opportunity (C3). The row's outcome decides: no row, or an outcome
    other than published, answers from the row (no engine run, no retry)."""
    oid = str(a.get("opportunity_id") or "")
    opp = ctx.opps.get(oid)
    if opp is None:
        raise ValueError("unknown_opportunity")
    if opp.get("outcome") != "published":
        return {
            "kết_quả": NO_OPPORTUNITY_VI,
            "card_ref": None,
            "lý_do": reason_vi(opp.get("reason")) or OUTCOME_VI.get(str(opp.get("outcome")), ""),
        }
    if code := opp.get("card_code"):
        return {"kết_quả": "đã có thẻ", "card_ref": f"open:{code}"}
    if len(ctx.drafts) >= MAX_DRAFTS:
        return {"lỗi": "đã đủ số thẻ nháp"}
    kind = str(opp.get("kind"))
    item_ids = [str(i) for i in (opp.get("item_ids") or [])]
    item = item_ids[0] if opp.get("scope") == "product" and item_ids else None
    res = await ctx.data.draft_opportunity(oid)
    card = (res.get("card") or {}) if res.get("ok", True) else {}
    ctx.draft_log.append(
        {
            "kind": kind,
            "item": item,
            "status": "draft" if card else "none",
            "reason": res.get("reason"),
        }
    )
    if not card or not cardstage.estimable(card, kind):
        return {
            "kết_quả": NO_PLAN_TOOL_VI,
            "card_ref": None,
            "lý_do": reason_vi(res.get("reason") or "not_estimable"),
        }
    before = ctx.out.cost_usd
    ev = await cardstage.draft_event(ctx.out, ctx.data, ctx.jev, ctx.labels, kind, item, card)
    ctx.budget.cost += ctx.out.cost_usd - before
    ref = str(ctx.out.accepted[-1]["ref"])
    ctx.drafts[ref] = {"acc": ctx.out.accepted[-1], "event": ev}
    return {"kết_quả": "đã tạo thẻ nháp", "card_ref": f"draft:{ref}"}


async def compare(ctx: Ctx, a: dict[str, Any]) -> dict[str, Any]:
    kind = a.get("kind") or None
    lv = [str(x) for x in (a.get("levers") or [])]
    allowed = set(levers.card_kinds(ctx.labels.kinds))
    if (kind is not None and kind not in allowed) or any(x not in allowed for x in lv):
        raise ValueError("bad_argument")
    item = _known(ctx, a.get("item"))
    block = await compare_mod.build(
        ctx.data, ctx.labels, kind=kind, levers_=lv, item=item, as_of_vi=ctx.fresh()
    )
    return {"phương_án": block["rows"], "chọn": block["lead_figure_vi"]}


TOOLS = {
    "metrics": metrics,
    "rank": rank,
    "opportunities": opportunities,
    "calendar": calendar,
    "draft_card": draft_card,
    "compare": compare,
}
