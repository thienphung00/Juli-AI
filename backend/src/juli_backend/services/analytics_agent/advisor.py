"""The advisor (J1-J5, #52/#53): a plan / priority / "what first, which card" request answered by
LLM reasoning over the shop's own data, with every number and card checked by code.

A bounded tool loop (at most `MAX_TURNS` model turns, the last one forced to `emit_plan`). The
tools are read-only wrappers over the same readers every other answer uses; the shop is bound by
`DataPort`, a tool has no shop argument, and a window is a validated enum, never a free date. Each
tool result carries the findings it can show, tagged with the levers the finding -> lever table
(`levers.py`, data) allows. The final answer is `emit_plan`: a `lead` (findings with no lever,
premise corrections) and ordered `actions` {lever (enum from `kinds.py`), card_ref, why}. The model
chooses the levers; code only validates:

- every action needs a `card_ref` that resolves against the open Đề xuất cards or the drafts made
  in this run, and the card's kind must equal the lever (the one non-card lever, `nhap_gia_von`,
  is exempt). A missing / unknown / wrong-kind ref is refused: the loop tells the model to
  `draft_card` and emit again (one repair round); what is still invalid then is dropped;
- keeps only the sentences whose numbers trace to the tool results (`facts.numbers_check`) and
  that pass `writer.sanitise`;
- renders the ordered list, the card status, the window and the freshness day itself.

Cost: one cap per answer (env `JULI_AGENT_ADVISE_COST_CAP_USD`, default $0.02), checked before
every model turn. A cap hit, an LLM error or an empty plan raises `AdviceAborted`: the engine then
falls back to the weekly sections plus the template. Nothing is sent or executed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from juli_backend.services.analytics_agent import cards as cardstage
from juli_backend.services.analytics_agent import facts, fmt, levers, summary, weekly, writer
from juli_backend.services.analytics_agent.entities import campaign_order, campaign_row
from juli_backend.services.analytics_agent.lookup import run_lookup
from juli_backend.services.analytics_agent.types import (
    CardEnginePort,
    DataPort,
    JevPort,
    LabelTable,
    LLMPort,
)
from juli_backend.services.analytics_agent.windows import (
    anchor_for,
    build_windows,
    clip_to_freshness,
    sale_days_vi,
)

logger = logging.getLogger(__name__)

ADVISE_COST_CAP_ENV = "JULI_AGENT_ADVISE_COST_CAP_USD"
DEFAULT_COST_CAP_USD = 0.02
MAX_TURNS = 4
MAX_TOOLS_PER_TURN = 4
MAX_DRAFTS = 3
MAX_ITEMS = 6
MAX_REPAIR_TURNS = 2  # extra turns after a refused plan: draft the missing cards, emit again
TOP = 5
NO_PLAN_TOOL_VI = "Juli chưa tính được phương án cho việc này"

#: The windows a tool may read (a validated enum; the model never writes a date).
WINDOWS = (
    "last_full_week_vs_week_before",
    "last_7d_vs_prev_7d",
    "last_30d_vs_prev_30d",
    "mtd_vs_same_days_last_month",
    "last_month_vs_month_before",
)
METRICS = (
    "gmv",
    "orders",
    "units",
    "views",
    "clicks",
    "profit",
    "margin",
    "ads_spend",
    "roas",
    "ctr",
    "ctor",
    "aov",
)


def cost_cap_usd() -> float:
    """The per-answer cap from the environment; a bad or non-positive value -> the default."""
    try:
        v = float(os.environ.get(ADVISE_COST_CAP_ENV, "").strip())
    except ValueError:
        return DEFAULT_COST_CAP_USD
    return v if v > 0 else DEFAULT_COST_CAP_USD


class AdviceAborted(RuntimeError):
    """The advisor gave no usable plan (`reason`: cap | llm_error | no_plan | empty); the engine
    falls back to the weekly sections."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


@dataclass
class Budget:
    """The running cost of this answer (the parse and Jev calls already spent count)."""

    cap: float
    cost: float = 0.0

    def check(self) -> None:
        if self.cost >= self.cap:
            raise AdviceAborted("cap", f"{self.cost:.4f} >= {self.cap:.4f}")


@dataclass
class Advice:
    events: list[dict[str, Any]]
    accepted: list[dict[str, Any]]  # the drafts the plan points to (full card rows)
    lead: str  # the code-written lead sentence (window, freshness, first action)
    turns: int = 0
    tools: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ prompt and tool schemas

#: Worked examples for the prompt (synthetic numbers and names, never a real shop's). They show the
#: shape: the lead carries what has no lever, the actions carry a lever + card_ref + why.
FEW_SHOT: tuple[dict[str, Any], ...] = (
    {
        "câu_hỏi": "Tuần sau shop nên làm gì?",
        "đọc_được": "Sản phẩm A lỗ sau quảng cáo (chi quảng cáo 200.000đ, đóng góp trước quảng cáo "
        "âm); chiến dịch X ROAS 3,4 so với hoà vốn 3,0; 2 ngày chi dưới ngân sách và không có "
        "đơn; tuần có ngày sale kéo GMV; sản phẩm B chiếm 70% GMV.",
        "emit_plan": {
            "lead": "Tuần này có ngày sale kéo GMV lên, nên đừng lấy làm nền so sánh. Sản phẩm B "
            "chiếm 70% GMV, shop đang phụ thuộc vào một sản phẩm.",
            "actions": [
                {
                    "lever": "ads_remove_product",
                    "card_ref": "draft:d1",
                    "why": "Sản phẩm A lỗ sau quảng cáo, gỡ khỏi chiến dịch nhóm.",
                },
                {
                    "lever": "ads_budget",
                    "card_ref": "open:JC-0001",
                    "why": "2 ngày chi dưới ngân sách, không có đơn: đừng tăng ngân sách.",
                },
                {
                    "lever": "ads_roas_target",
                    "card_ref": "draft:d2",
                    "why": "Chiến dịch X lãi nhưng ROAS 3,4 chỉ hơn hoà vốn 3,0 một chút.",
                },
            ],
        },
    },
    {
        "câu_hỏi": "Doanh thu tuần này sụp mạnh, mình cứu kiểu gì đây?",
        "đọc_được": "GMV tuần này tăng so với tuần trước nhờ một ngày sale; sản phẩm A lỗ sau "
        "quảng cáo.",
        "emit_plan": {
            "lead": "Doanh thu tuần này không sụp: GMV tăng so với tuần trước, chủ yếu nhờ ngày "
            "sale. Việc đáng làm là cắt chỗ đang lỗ.",
            "actions": [
                {
                    "lever": "ads_remove_product",
                    "card_ref": "draft:d1",
                    "why": "Sản phẩm A lỗ sau quảng cáo.",
                }
            ],
        },
    },
    {
        "câu_hỏi": "Giá vốn của mình thiếu nhiều không?",
        "đọc_được": "cogs_gaps: không sản phẩm nào thiếu giá vốn.",
        "emit_plan": {
            "lead": "Giá vốn đã đủ cho các sản phẩm lớn, nên lợi nhuận đáng tin.",
            "actions": [],
        },
    },
    {
        "câu_hỏi": "Tháng này nên ưu tiên gì?",
        "đọc_được": "Kỳ tháng này tính đến hết hôm qua (mtd_vs_same_days_last_month); chiến dịch X "
        "lãi rõ; sản phẩm C thiếu giá vốn.",
        "emit_plan": {
            "lead": "Số liệu là từ đầu tháng đến hết hôm qua, so với cùng số ngày tháng trước.",
            "actions": [
                {
                    "lever": "ads_budget",
                    "card_ref": "open:JC-0002",
                    "why": "Chiến dịch X lãi rõ, xem lại ngân sách để tận dụng.",
                },
                {
                    "lever": "nhap_gia_von",
                    "card_ref": "none",
                    "why": "Sản phẩm C thiếu giá vốn nên lợi nhuận chưa đáng tin.",
                },
            ],
        },
    },
)

SYSTEM = (
    "Bạn là Juli, cố vấn cho người bán hàng Shopee, xưng 'bạn'. Người bán hỏi nên làm gì / ưu "
    "tiên gì. Hãy gọi các công cụ để đọc số liệu của chính shop (chỉ đọc), suy luận, rồi gọi "
    "emit_plan để trả lời. Quy tắc:\n"
    "- Mọi con số trong 'lead' và 'why' lấy nguyên văn từ kết quả công cụ (đã định dạng sẵn), "
    "không tự tính, không thêm số nào khác.\n"
    "- Mỗi kết quả công cụ có 'phát_hiện_và_lever': những phát hiện có thể thấy ở đó và các lever "
    "cho phép. Chỉ đưa vào 'actions' việc có phát hiện thật trong dữ liệu; chọn lever trong danh "
    "sách cho phát hiện đó. Phát hiện không có lever, câu hỏi có tiền đề sai (số liệu nói khác), "
    "kỳ có ngày sale, dữ liệu thiếu: viết vào 'lead', không đưa vào 'actions'. Khi tiền đề của "
    "người bán sai, nói đúng sự thật ở 'lead' trước, rồi vẫn liệt kê việc thật nếu có.\n"
    "- 'actions' sắp theo ưu tiên: mục đầu là việc nên làm trước. Mỗi mục: lever, card_ref, why "
    "(1-2 câu: điều dữ liệu cho thấy).\n"
    "- card_ref bắt buộc: 'open:<mã thẻ>' của một thẻ đang có trong open_cards, hoặc "
    "'draft:<ref>' do draft_card trả về. Loại thẻ phải đúng bằng lever. Chưa có thẻ thì gọi "
    "draft_card với đúng lever (kèm item nếu cần) trước khi emit_plan. Nếu draft_card báo chưa "
    "có phương án thì đưa việc đó vào 'lead' hoặc bỏ. Riêng lever nhap_gia_von (không phải thẻ) "
    "dùng card_ref 'none'.\n"
    "- Chiến dịch có nhiều sản phẩm mà một sản phẩm lỗ: ads_remove_product (chỉ ads_pause khi nó "
    "là sản phẩm duy nhất). Ngày chi dưới ngân sách là ngày chi dưới 30% ngân sách ngày và không "
    "có đơn quảng cáo. Câu hỏi về tháng: gọi công cụ với window mtd_vs_same_days_last_month.\n"
    "- Mỗi chiến dịch quảng cáo, mỗi sản phẩm chỉ nhắc một lần. Nếu có dữ liệu, hãy xét cả kênh "
    "lưu lượng (Organic / TTLK / Quảng cáo) và thiếu giá vốn.\n"
    "- Không lặp lại số liệu mà không kèm quyết định. Không viết giá trị hay dự báo của thẻ, "
    "không dùng từ kỹ thuật, không mã, không tiếng Anh.\n"
    "- Tối đa 3 lượt gọi công cụ, rồi emit_plan.\n"
    "Ví dụ (tên và số trong ví dụ là giả, không phải của shop này; đừng chép số):\n"
    + "\n".join(json.dumps(ex, ensure_ascii=False) for ex in FEW_SHOT)
)

_WINDOW_PROP = {
    "type": "string",
    "enum": list(WINDOWS),
    "description": "kỳ so sánh (chọn một giá trị trong danh sách)",
}
_NO_ARGS: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}
#: The week tools read the last full week by default; a month question passes a window.
_OPT_WINDOW: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"window": _WINDOW_PROP},
}


def tool_specs(kinds: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "name": "week_summary",
            "description": "GMV, đơn, chi phí quảng cáo, ROAS của tuần vừa rồi so với tuần trước.",
            "input_schema": _NO_ARGS,
        },
        {
            "name": "campaigns",
            "description": "Từng chiến dịch quảng cáo: ROAS so với ROAS hoà vốn (ba cấp), lỗ/lãi.",
            "input_schema": _OPT_WINDOW,
        },
        {
            "name": "idle_budget_days",
            "description": "Những ngày chi quảng cáo dưới ngân sách và không có đơn.",
            "input_schema": _OPT_WINDOW,
        },
        {
            "name": "traffic_sources",
            "description": "GMV theo kênh Organic / TTLK / Quảng cáo, kênh nào giảm.",
            "input_schema": _OPT_WINDOW,
        },
        {
            "name": "product_margins",
            "description": "Sản phẩm lớn nhất: tỷ trọng GMV, biên lợi nhuận đổi thế nào, tên còn "
            "ghi ngày sale đã hết.",
            "input_schema": _OPT_WINDOW,
        },
        {
            "name": "cogs_gaps",
            "description": "Sản phẩm thiếu giá vốn (lợi nhuận chưa đáng tin).",
            "input_schema": _OPT_WINDOW,
        },
        {
            "name": "open_cards",
            "description": "Các thẻ đang có trong Đề xuất (mã thẻ, loại, sản phẩm).",
            "input_schema": _NO_ARGS,
        },
        {
            "name": "metric_view",
            "description": "Một chỉ số của cả shop hoặc một sản phẩm trong một kỳ, so với kỳ "
            "trước.",
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["metric", "window"],
                "properties": {
                    "metric": {"type": "string", "enum": list(METRICS)},
                    "window": _WINDOW_PROP,
                    "item": {
                        "type": ["string", "null"],
                        "description": "id sản phẩm lấy từ kết quả công cụ khác; null = cả shop",
                    },
                },
            },
        },
        {
            "name": "product_profit",
            "description": "Lợi nhuận sau quảng cáo, đóng góp trước quảng cáo, chi quảng cáo và "
            "ROAS hoà vốn của một sản phẩm; không có item thì trả các sản phẩm kém nhất.",
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["window"],
                "properties": {
                    "window": _WINDOW_PROP,
                    "item": {
                        "type": ["string", "null"],
                        "description": "id sản phẩm lấy từ kết quả công cụ khác",
                    },
                },
            },
        },
        {
            "name": "draft_card",
            "description": "Tạo thẻ nháp (không gửi) cho một việc; trả card_ref để dùng trong "
            "emit_plan, hoặc báo đã có thẻ / chưa có phương án.",
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind"],
                "properties": {
                    "kind": {"type": "string", "enum": levers.card_kinds(kinds)},
                    "item": {"type": ["string", "null"], "description": "id sản phẩm nếu cần"},
                },
            },
        },
        plan_tool(kinds),
    ]


def plan_tool(kinds: Any = None) -> dict[str, Any]:
    """`emit_plan`: `lead` (no-lever findings, premise corrections) + `actions` {lever from the
    table's enum, card_ref (required), why}."""
    return {
        "name": "emit_plan",
        "description": "Trả lời cuối: 'lead' (phát hiện không có lever, sửa tiền đề sai, kỳ có "
        "ngày sale) và 'actions' (việc nên làm, sắp theo ưu tiên; mỗi việc cần lever và card_ref).",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["lead", "actions"],
            "properties": {
                "lead": {"type": "string"},
                "actions": {
                    "type": "array",
                    "maxItems": MAX_ITEMS,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["lever", "card_ref", "why"],
                        "properties": {
                            "lever": {"type": "string", "enum": levers.lever_enum(kinds)},
                            "card_ref": {
                                "type": "string",
                                "description": "open:<mã thẻ> | draft:<ref> | none (nhap_gia_von)",
                            },
                            "why": {"type": "string"},
                        },
                    },
                },
            },
        },
    }


PLAN_TOOL: dict[str, Any] = plan_tool()


# ------------------------------------------------------------------ the tools


@dataclass
class Ctx:
    data: DataPort
    engine: CardEnginePort | None
    jev: JevPort
    labels: LabelTable
    as_of: date
    budget: Budget
    out: cardstage.CardOutcome = field(default_factory=cardstage.CardOutcome)
    results: list[Any] = field(default_factory=list)  # every tool result = the fact set
    names: dict[str, str] = field(default_factory=dict)  # item id -> name (from tool results)
    known_items: set[str] = field(default_factory=set)
    windows: dict[str, str] = field(default_factory=dict)  # window label -> sale note
    drafts: dict[str, dict[str, Any]] = field(default_factory=dict)  # ref -> {acc, event}
    latest: date | None = None
    _rows: list[dict[str, Any]] | None = None
    _open: list[dict[str, Any]] | None = None

    async def shop_rows(self) -> list[dict[str, Any]]:
        if self._rows is None:
            self._rows = await self.data.shop_daily(self.as_of)
            self.latest = max((r["day"] for r in self._rows if r["complete"]), default=None)
        return self._rows

    async def open_cards(self) -> list[dict[str, Any]]:
        if self._open is None:
            self._open = await self.data.open_cards()
        return self._open

    async def window(self, preset: str) -> Any:
        await self.shop_rows()
        if self.latest is None:
            raise AdviceAborted("no_data")
        w = build_windows(preset, anchor_for(preset, self.as_of, self.latest), sale_aware=True)
        w = clip_to_freshness(w, self.latest)
        self.windows[w.label()] = sale_days_vi(w) or ""
        return w

    def fresh(self) -> str:
        return f"Số liệu đến hết {self.latest:%d/%m}" if self.latest else ""

    def head(self, w: Any) -> dict[str, Any]:
        return {"kỳ": w.label(), "số_liệu_đến": self.fresh()}

    def see(self, item: str, name: str | None) -> None:
        self.known_items.add(item)
        if name:
            self.names[item] = name


def _rows_out(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: r[k] for k in ("label_vi", "value_vi", "detail_vi") if r.get(k)} for r in rows]


async def _week_summary(ctx: Ctx, _a: dict[str, Any]) -> dict[str, Any]:
    w = await ctx.window(weekly.PRESET)
    assert w.prev is not None
    last = w.sale_prev or w.prev
    table = weekly.week_table(await ctx.shop_rows(), w, last)
    return {
        **ctx.head(w),
        "so_với": weekly.rng(last),
        "dòng": [
            {
                "chỉ_số": r["label_vi"],
                "tuần_này": r["value_vi"],
                "tuần_trước": r["detail_vi"],
                "thay_đổi": r["delta"]["text_vi"],
            }
            for r in table
        ],
    }


def _preset(a: dict[str, Any]) -> str:
    """The window a tool reads: the last full week unless the model names one from the enum."""
    preset = a.get("window") or weekly.PRESET
    if preset not in WINDOWS:
        raise ValueError("bad_argument")
    return str(preset)


async def _campaigns(ctx: Ctx, a: dict[str, Any]) -> dict[str, Any]:
    w = await ctx.window(_preset(a))
    camps = sorted(await ctx.data.campaign_rows(*w.cur), key=campaign_order)
    for c in camps:
        ctx.names.setdefault(str(c.get("key") or c["name"]), str(c["name"]))
    return {**ctx.head(w), "chiến_dịch": _rows_out([campaign_row(c) for c in camps[:8]])}


async def _idle(ctx: Ctx, a: dict[str, Any]) -> dict[str, Any]:
    w = await ctx.window(_preset(a))
    idle = weekly.idle_days(await ctx.data.budget_days(*w.cur), await ctx.shop_rows(), w.cur)
    return {
        **ctx.head(w),
        "ngày": [
            {
                "ngày": f"{b['day']:%d/%m}",
                "chi": fmt.value("ads_spend", float(b["spend"])),
                "ngân_sách": fmt.value("ads_spend", float(b["budget"])),
            }
            for b in idle
        ],
    }


async def _traffic(ctx: Ctx, a: dict[str, Any]) -> dict[str, Any]:
    w = await ctx.window(_preset(a))
    assert w.prev is not None
    srows = await ctx.data.source_daily(w.prev[0], w.cur[1])
    now, before = weekly.source_gmv(w.cur, srows), weekly.source_gmv(w.prev, srows)
    keys = sorted(set(now) | set(before))
    return {
        **ctx.head(w),
        "kênh": [
            {
                "kênh": ctx.labels.source(k),
                "kỳ_này": fmt.value("gmv", now.get(k, 0.0)),
                "kỳ_trước": fmt.value("gmv", before.get(k, 0.0)),
                "giảm": now.get(k, 0.0) < before.get(k, 0.0),
            }
            for k in keys
        ],
    }


async def _top_products(ctx: Ctx, w: Any) -> tuple[list[str], dict[str, float], dict[str, str]]:
    cur: dict[str, float] = {}
    for r in await ctx.data.product_daily(*w.cur):
        cur[r["item_id"]] = cur.get(r["item_id"], 0.0) + float(r["gmv"] or 0)
    top = sorted(cur, key=lambda k: -cur[k])[:TOP]
    names = await ctx.data.item_names(top)
    for k in top:
        ctx.see(k, names.get(k))
    return top, cur, names


async def _product_margins(ctx: Ctx, a: dict[str, Any]) -> dict[str, Any]:
    w = await ctx.window(_preset(a))
    assert w.prev is not None
    top, cur, names = await _top_products(ctx, w)
    total = sum(cur.values())
    rows = []
    for k in top:
        now_p = await ctx.data.product_profit(k, *w.cur)
        old_p = await ctx.data.product_profit(k, *w.prev)
        row: dict[str, Any] = {"id": k, "tên": names.get(k, k), "GMV": fmt.value("gmv", cur[k])}
        if total:
            row["tỷ_trọng"] = f"{100 * cur[k] / total:.0f}% GMV".replace(".", ",")
        m_now = None if not now_p or now_p["margin_pct"] is None else float(now_p["margin_pct"])
        m_old = None if not old_p or old_p["margin_pct"] is None else float(old_p["margin_pct"])
        if m_now is not None and m_old is not None:
            row["biên"] = fmt.delta("margin", m_now / 100, m_old / 100)["text_vi"]
        stale = weekly.ended_deal_in(names.get(k, ""), ctx.as_of + timedelta(days=1))
        if stale:
            row["tên_còn_ngày_sale_đã_hết"] = stale
        rows.append(row)
    return {**ctx.head(w), "sản_phẩm": rows}


async def _cogs_gaps(ctx: Ctx, a: dict[str, Any]) -> dict[str, Any]:
    w = await ctx.window(_preset(a))
    top, _cur, names = await _top_products(ctx, w)
    gaps = [k for k in top if weekly.has_cogs_gap(await ctx.data.product_profit(k, *w.cur))]
    return {
        **ctx.head(w),
        "thiếu_giá_vốn": [{"id": k, "tên": names.get(k, k)} for k in gaps],
    }


async def _open_cards(ctx: Ctx, _a: dict[str, Any]) -> dict[str, Any]:
    cards = await ctx.open_cards()
    ids = [str(c["item_id"]) for c in cards if c.get("item_id")]
    names = await ctx.data.item_names(ids) if ids else {}
    out = []
    for c in cards:
        item = c.get("item_id")
        if item:
            ctx.see(str(item), names.get(str(item)))
        out.append(
            {
                "mã": c.get("code"),
                "loại": ctx.labels.kind(str(c["kind"])),
                "sản_phẩm": names.get(str(item)) if item else None,
                "trạng_thái": c.get("status"),
                "thay_đổi": c.get("change_after"),
            }
        )
    return {"thẻ": out}


def _known(ctx: Ctx, item: Any) -> str | None:
    """An item id must come from an earlier tool result; anything else is refused."""
    if item in (None, ""):
        return None
    if str(item) not in ctx.known_items:
        raise ValueError("unknown_item")
    return str(item)


async def _metric_view(ctx: Ctx, a: dict[str, Any]) -> dict[str, Any]:
    metric, preset = a.get("metric"), a.get("window")
    if metric not in METRICS or preset not in WINDOWS:
        raise ValueError("bad_argument")
    item = _known(ctx, a.get("item"))
    await ctx.shop_rows()
    res = await run_lookup(
        ctx.data, ctx.labels, "metric_total", str(metric), str(preset), ctx.as_of, item_id=item
    )
    if res.get("stop") == "data_missing":
        return {"lỗi": "thiếu dữ liệu"}
    w = await ctx.window(str(preset))
    out = {
        **ctx.head(w),
        "chỉ_số": ctx.labels.metric(str(metric)),
        "phạm_vi": ctx.names.get(item, item) if item else "cả shop",
    }
    for src, dst in (
        ("value", "giá_trị"),
        ("before_vi", "kỳ_trước"),
        ("contribution_vi", "đóng_góp"),
    ):
        if res.get(src):
            out[dst] = res[src]
    if (res.get("delta") or {}).get("text_vi"):
        out["thay_đổi"] = res["delta"]["text_vi"]
    return out


async def _product_profit(ctx: Ctx, a: dict[str, Any]) -> dict[str, Any]:
    preset = a.get("window")
    if preset not in WINDOWS:
        raise ValueError("bad_argument")
    item = _known(ctx, a.get("item"))
    w = await ctx.window(str(preset))
    rows = await ctx.data.product_profit_rows(*w.cur)
    if item:
        rows = [r for r in rows if r["item_id"] == item]
    else:  # the worst products after ads first (None profit last)
        rows = sorted(rows, key=lambda r: (r["profit"] is None, float(r["profit"] or 0.0)))[:8]
    out = []
    for r in rows:
        ctx.see(str(r["item_id"]), r.get("name"))
        be, contrib = r.get("break_even_roas"), r.get("contribution_before_ads")
        row: dict[str, Any] = {
            "id": r["item_id"],
            "tên": r.get("name") or r["item_id"],
            "lợi_nhuận_sau_QC": fmt.value("profit", _f(r.get("profit"))),
            "đóng_góp_trước_QC": fmt.value("profit", _f(contrib)) if contrib is not None else None,
            "chi_QC": fmt.value("ads_spend", _f(r.get("ad_spend"))),
            "ROAS_hoà_vốn": fmt.value("roas", _f(be)) if be is not None else "chưa có",
        }
        if r.get("margin_pct") is not None:
            row["biên"] = fmt.value("margin", float(r["margin_pct"]) / 100)
        out.append({k: v for k, v in row.items() if v is not None})
    return {**ctx.head(w), "sản_phẩm": out}


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


async def _draft_card(ctx: Ctx, a: dict[str, Any]) -> dict[str, Any]:
    kind = a.get("kind")
    if kind not in ctx.labels.kinds:
        raise ValueError("bad_argument")
    item = _known(ctx, a.get("item"))
    engine = ctx.engine
    if engine is None:
        return {"kết_quả": NO_PLAN_TOOL_VI}
    if len(ctx.drafts) >= MAX_DRAFTS:
        return {"lỗi": "đã đủ số thẻ nháp"}
    before = ctx.out.cost_usd
    res = await weekly.resolve_action(
        ctx.out,
        ctx.data,
        engine,
        ctx.jev,
        ctx.labels,
        ctx.as_of,
        await ctx.open_cards(),
        str(kind),
        item,
    )
    ctx.budget.cost += ctx.out.cost_usd - before
    code = res["code"]
    if res["status"] == "same":
        return {"kết_quả": "đã có thẻ giống hệt", "card_ref": f"open:{code}"}
    if res["status"] == "none":
        if code:
            return {
                "kết_quả": "chưa có phương án mới, đã có thẻ cùng loại",
                "card_ref": f"open:{code}",
            }
        return {"kết_quả": NO_PLAN_TOOL_VI, "card_ref": None}
    ref = str(res["ref"])
    ctx.drafts[ref] = {"acc": ctx.out.accepted[-1], "event": res["event"]}
    out: dict[str, Any] = {"kết_quả": "đã tạo thẻ nháp", "card_ref": f"draft:{ref}"}
    if code:
        out["đã_có_thẻ_cùng_loại"] = f"open:{code}"
    return out


TOOLS = {
    "week_summary": _week_summary,
    "campaigns": _campaigns,
    "idle_budget_days": _idle,
    "traffic_sources": _traffic,
    "product_margins": _product_margins,
    "cogs_gaps": _cogs_gaps,
    "open_cards": _open_cards,
    "metric_view": _metric_view,
    "product_profit": _product_profit,
    "draft_card": _draft_card,
}


async def run_tool(ctx: Ctx, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """One tool call -> its JSON result. An unknown tool or bad argument is an error result the
    model can recover from; a data failure never leaks a trace."""
    fn = TOOLS.get(name)
    if fn is None:
        return {"lỗi": "công cụ không tồn tại"}
    try:
        res = await fn(ctx, args or {})
    except AdviceAborted:
        raise
    except ValueError as exc:
        return {"lỗi": str(exc)}
    except Exception:
        logger.exception("juli_advisor_tool_failed", extra={"tool": name})
        return {"lỗi": "không đọc được dữ liệu"}
    if name != "draft_card" and "lỗi" not in res and (tags := levers.tags_for(name)):
        res = {**res, "phát_hiện_và_lever": tags}
    ctx.results.append(res)
    return res


# ------------------------------------------------------------------ the guards

_SENTENCE = re.compile(r"(?<=[.!?…])\s+")


def keep_traced(text: str, fact_set: facts.Facts, names: list[str]) -> tuple[str, list[str]]:
    """Only the sentences whose numbers all trace to the tool results (dates are not checked;
    digits inside a product name are not claims). Returns (kept text, dropped sentences)."""
    kept: list[str] = []
    dropped: list[str] = []
    for sent in (s.strip() for s in _SENTENCE.split(text.strip())):
        if not sent:
            continue
        masked = sent
        for n in sorted(names, key=len, reverse=True):
            masked = masked.replace(n, " ")
        if facts.numbers_check("-\n" + masked, fact_set, card_figures=[]):
            dropped.append(sent)
        else:
            kept.append(sent)
    return " ".join(kept), dropped


def guard_text(
    text: str, fact_set: facts.Facts, id_names: dict[str, str], names: list[str]
) -> tuple[str, list[str]]:
    """sanitise (leaks refuse the whole text), then drop untraced sentences."""
    clean, leaks = writer.sanitise(text or "", id_names, names)
    if leaks:
        return "", [f"leak:{x}" for x in leaks]
    return keep_traced(clean, fact_set, names)


#: What `check_plan` found wrong with an action (the model sees these words in the refusal).
_PROBLEM_VI = {
    "no_ref": "thiếu card_ref",
    "unknown_ref": "card_ref không có trong open_cards hay thẻ nháp",
    "kind_mismatch": "thẻ của card_ref không đúng loại với lever",
    "bad_lever": "lever không nằm trong danh sách",
}


@dataclass
class _Checked:
    lever: str
    why: str
    problem: str | None = None  # a _PROBLEM_VI key
    ref: str | None = None
    code: str = ""  # open card code
    event: dict[str, Any] | None = None  # the draft's card event
    acc: dict[str, Any] | None = None


def check_plan(
    ctx: Ctx, open_by_code: dict[str, dict[str, Any]], actions: list[Any]
) -> list[_Checked]:
    """Schema, refs and kinds only: no lever is chosen here. An action is valid when its lever is in
    the enum and its card_ref is an open card or a draft of this run whose kind is the lever (the
    non-card levers need no card)."""
    allowed = set(levers.lever_enum(ctx.labels.kinds))
    out: list[_Checked] = []
    for raw in actions[:MAX_ITEMS]:
        if not isinstance(raw, dict):
            continue
        lever = str(raw.get("lever") or "")
        ref = raw.get("card_ref")
        c = _Checked(
            lever=lever, why=str(raw.get("why") or ""), ref=ref if isinstance(ref, str) else None
        )
        if lever not in allowed:
            c.problem = "bad_lever"
        elif lever in levers.CARD_EXEMPT:
            pass
        elif not c.ref or c.ref == "none":
            c.problem = "no_ref"
        elif c.ref.startswith("open:") and c.ref[5:] in open_by_code:
            c.code = c.ref[5:]
            if str(open_by_code[c.code].get("kind")) != lever:
                c.problem = "kind_mismatch"
        elif c.ref.startswith("draft:") and c.ref[6:] in ctx.drafts:
            draft = ctx.drafts[c.ref[6:]]
            c.event, c.acc = draft["event"], draft["acc"]
            if str(draft["acc"].get("kind")) != lever:
                c.problem = "kind_mismatch"
        else:
            c.problem = "unknown_ref"
        out.append(c)
    return out


def refusal(checked: list[_Checked]) -> dict[str, Any]:
    """The tool result that sends the plan back: which actions failed and what to do."""
    return {
        "lỗi": "kế hoạch chưa hợp lệ, chưa được nhận",
        "mục_lỗi": [
            {"lever": c.lever, "card_ref": c.ref, "vấn_đề": _PROBLEM_VI[c.problem]}
            for c in checked
            if c.problem
        ],
        "cách_sửa": "gọi draft_card đúng lever (kèm item nếu cần) rồi emit_plan lại; việc không "
        "tạo được thẻ thì chuyển vào lead hoặc bỏ",
    }


async def render(
    ctx: Ctx, plan: dict[str, Any], fact_set: facts.Facts, checked: list[_Checked] | None = None
) -> Advice:
    """Render the validated `emit_plan`: actions that still fail are dropped (recorded in
    `dropped`); raises `AdviceAborted("empty")` when neither an action nor a lead survives."""
    open_by_code = {str(c["code"]): c for c in await ctx.open_cards() if c.get("code")}
    names = sorted({*ctx.names.values(), *(str(v) for v in ctx.names.values())})
    if checked is None:
        checked = check_plan(ctx, open_by_code, list(plan.get("actions") or []))
    dropped: list[str] = []
    rows: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    used: set[str] = set()
    first_action = ""
    for c in checked:
        if c.problem:
            dropped.append(f"{c.problem}:{c.ref or c.lever}")
            continue
        if c.ref and c.ref != "none":
            if c.ref in used:
                dropped.append(f"duplicate_ref:{c.ref}")
                continue
            used.add(c.ref)
        why, why_drop = guard_text(c.why, fact_set, ctx.names, names)
        dropped += why_drop
        if c.lever in levers.NON_CARD_LEVERS:
            action, value = levers.NON_CARD_LEVERS[c.lever], ""
        else:
            action = ctx.labels.kind(c.lever)
            value = f"Đã có thẻ {c.code}" if c.code else "Thẻ nháp"
        if c.event is not None and c.acc is not None:
            cards.append(c.event)
            accepted.append(c.acc)
        rows.append(
            {
                "label_vi": f"{len(rows) + 1}. {action}",
                "value_vi": value,
                "detail_vi": why,
                "lever": c.lever,
            }
        )
        if not first_action:
            first_action = action
    lead_text, lead_drop = guard_text(str(plan.get("lead") or ""), fact_set, ctx.names, names)
    dropped += lead_drop
    if not rows and not lead_text:
        raise AdviceAborted("empty", ";".join(dropped))
    labels = list(ctx.windows)
    window_vi = " · ".join(labels[:2])
    events: list[dict[str, Any]] = []
    if rows:
        section: dict[str, Any] = {
            "type": "data_answer",
            "kind": "top_products",  # the UI's ranked-list kind: label / value / detail rows
            "title_vi": "Việc nên làm, theo thứ tự ưu tiên",
            "window_vi": window_vi,
            "fresh_vi": ctx.fresh(),
            "rows": rows,
            "stop": "data_answer",
        }
        if sale := next((v for v in ctx.windows.values() if v), None):
            section["sale_vi"] = sale
        events = [section, *cards]
    lead = f"{window_vi} · {ctx.fresh()}. " + (f"{lead_text} " if lead_text else "")
    lead += f"Việc nên làm trước: {first_action}." if first_action else ""
    return Advice(events=events, accepted=accepted, lead=lead.strip(), dropped=dropped)


# ------------------------------------------------------------------ the loop


#: The keys a replayed block keeps: the API adds others to its answers (e.g. ``caller`` on a
#: ``tool_use``), which the gate's block allowlist refuses (payload_shape) on the next turn.
_REPLAY_KEYS = {"text": ("type", "text"), "tool_use": ("type", "id", "name", "input")}


def _replay_block(block: dict[str, Any]) -> dict[str, Any]:
    """The block as the next turn sends it back: only the keys the Messages API needs."""
    return {k: block[k] for k in _REPLAY_KEYS[block["type"]] if k in block}


def _blocks(content: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [b for b in content if b.get("type") == kind]


async def run_advice(
    llm: LLMPort,
    data: DataPort,
    engine: CardEnginePort | None,
    jev: JevPort,
    labels: LabelTable,
    as_of: date,
    question: str,
    goal: str,
    budget: Budget,
) -> Advice:
    """The advisor's answer; raises `AdviceAborted` (cap / llm_error / no_plan / empty)."""
    ctx = Ctx(data=data, engine=engine, jev=jev, labels=labels, as_of=as_of, budget=budget)
    tools = tool_specs(sorted(labels.kinds))
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": json.dumps(
                {"câu_hỏi": question, "mục_tiêu": goal, "hôm_nay": f"{as_of:%d/%m/%Y}"},
                ensure_ascii=False,
            ),
        }
    ]
    plan: dict[str, Any] | None = None
    checked: list[_Checked] | None = None
    used: list[str] = []
    turns = 0
    max_turns = MAX_TURNS
    repaired = False
    turn = 0
    while turn < max_turns:
        budget.check()
        last = turn == max_turns - 1
        try:
            content, usage = await llm.agent(
                SYSTEM, tools, messages, force_tool="emit_plan" if last else None
            )
        except Exception as exc:
            raise AdviceAborted("llm_error", type(exc).__name__) from exc
        turns += 1
        turn += 1
        budget.cost += usage.cost_usd
        # the loop replays its turns: only text / tool_use go back (the gate refuses other blocks;
        # `GateLLM.agent` runs with thinking disabled, so none is needed for the next turn)
        content = [_replay_block(b) for b in content if b.get("type") in ("text", "tool_use")]
        messages.append({"role": "assistant", "content": content})
        uses = _blocks(content, "tool_use")
        final = next((u for u in uses if u.get("name") == "emit_plan"), None)
        if final is not None:
            plan = final.get("input") if isinstance(final.get("input"), dict) else None
            if plan is None:
                break
            open_by_code = {str(c["code"]): c for c in await ctx.open_cards() if c.get("code")}
            checked = check_plan(ctx, open_by_code, list(plan.get("actions") or []))
            if not repaired and any(c.problem for c in checked):
                # refused: the model drafts the missing cards and emits again (one repair round)
                repaired = True
                max_turns = min(turn + MAX_REPAIR_TURNS, MAX_TURNS + MAX_REPAIR_TURNS)
                result = json.dumps(refusal(checked), ensure_ascii=False)
                plan, checked = None, None
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": final.get("id"),
                                "content": result,
                            }
                        ],
                    }
                )
                continue
            break
        if not uses:
            messages.append({"role": "user", "content": "Hãy gọi emit_plan."})
            continue
        results = []
        for u in uses[:MAX_TOOLS_PER_TURN]:
            used.append(str(u.get("name")))
            res = await run_tool(ctx, str(u.get("name")), u.get("input") or {})
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": u.get("id"),
                    "content": json.dumps(res, ensure_ascii=False, default=str),
                }
            )
        for u in uses[MAX_TOOLS_PER_TURN:]:
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": u.get("id"),
                    "content": json.dumps({"lỗi": "quá nhiều công cụ trong một lượt"}),
                }
            )
        messages.append({"role": "user", "content": results})
    if (
        not isinstance(plan, dict)
        or not isinstance(plan.get("actions"), list)
        or not isinstance(plan.get("lead"), str)
        or not (plan["actions"] or plan["lead"].strip())
    ):
        raise AdviceAborted("no_plan")
    fact_set = summary.given_facts({"answers": ctx.results})
    advice = await render(ctx, plan, fact_set, checked)
    advice.turns, advice.tools = turns, used
    return advice


async def with_timeout(coro: Any, seconds: float) -> Any:
    try:
        return await asyncio.wait_for(coro, seconds)
    except TimeoutError as exc:
        raise AdviceAborted("llm_error", "timeout") from exc


__all__ = [
    "Advice",
    "AdviceAborted",
    "Budget",
    "cost_cap_usd",
    "run_advice",
    "tool_specs",
]
