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
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from juli_backend.services.analytics_agent import (
    advisor_tools,
    facts,
    levers,
    summary,
    writer,
)
from juli_backend.services.analytics_agent import cards as cardstage
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
MAX_DRAFTS = advisor_tools.MAX_DRAFTS
MAX_ITEMS = 6
MAX_REPAIR_TURNS = 2  # extra turns after a refused plan: draft the missing cards, emit again
TOP = 5
WINDOWS = advisor_tools.WINDOWS
NO_PLAN_TOOL_VI = advisor_tools.NO_PLAN_TOOL_VI


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
        self.detail = detail


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
    drafts: list[dict[str, Any]] = field(default_factory=list)  # draft_card outcomes (diagnosis)


# ------------------------------------------------------------------ prompt and tool schemas

#: Worked examples for the prompt (synthetic numbers and names, never a real shop's). They show the
#: shape: the lead carries what has no lever, the actions carry a lever + card_ref + why.
FEW_SHOT: tuple[dict[str, Any], ...] = (
    {
        "câu_hỏi": "Tuần sau shop nên làm gì?",
        "đọc_được": "Sản phẩm A lỗ sau quảng cáo (chi quảng cáo 200.000đ, lợi nhuận đóng góp "
        "âm); chiến dịch X ROAS 3,4 so với hoà vốn 3,0; 2 ngày chi dưới ngân sách và không có "
        "đơn; sản phẩm C thiếu giá vốn; tuần trước có ngày sale kéo GMV; sản phẩm B chiếm 70% GMV; "
        "open_cards có thẻ ngân sách JC-0001 (lever ads_budget).",
        "emit_plan": {
            "lead": "Tuần trước có ngày sale kéo GMV lên, nên đừng lấy làm nền so sánh. Sản phẩm B "
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
                {
                    "lever": "nhap_gia_von",
                    "card_ref": "none",
                    "why": "Sản phẩm C thiếu giá vốn nên lợi nhuận chưa đáng tin.",
                },
            ],
        },
    },
    {
        "câu_hỏi": "Quảng cáo đang lỗ nặng, tắt hết chiến dịch đúng không?",
        "đọc_được": "Cả hai chiến dịch X và Y đều lãi (ROAS cao hơn hoà vốn); chỉ sản phẩm A "
        "lỗ sau quảng cáo trong chiến dịch nhóm X.",
        "emit_plan": {
            "lead": "Quảng cáo không lỗ nặng: cả hai chiến dịch đều lãi nên không cần tắt. Chỉ có "
            "sản phẩm A đang lỗ.",
            "actions": [
                {
                    "lever": "ads_remove_product",
                    "card_ref": "draft:d1",
                    "why": "Sản phẩm A lỗ sau quảng cáo trong chiến dịch nhóm X, chỉ gỡ sản phẩm "
                    "này.",
                }
            ],
        },
    },
    {
        "câu_hỏi": "Mai là ngày 25, shop nên chuẩn bị gì?",
        "đọc_được": "calendar: ngày_sale_sắp_tới gồm 25/11 và 12/12; chưa có thẻ nào cho ngày "
        "sale; sản phẩm B bán chạy nhất.",
        "emit_plan": {
            "lead": "Ngày 25/11 là ngày sale, kế tiếp là 12/12.",
            "actions": [
                {
                    "lever": "flash_sale",
                    "card_ref": "draft:d1",
                    "why": "Sản phẩm B bán chạy nhất, đặt Flash Sale cho ngày 25/11.",
                },
                {
                    "lever": "min_spend_voucher",
                    "card_ref": "draft:d2",
                    "why": "Mã giảm giá đơn tối thiểu để kéo giá trị đơn trong ngày sale.",
                },
                {
                    "lever": "program_registration",
                    "card_ref": "draft:d3",
                    "why": "Đăng ký chương trình Shopee cho ngày sale sắp tới.",
                },
            ],
        },
    },
    {
        "câu_hỏi": "Khách xem nhiều mà ít chốt đơn, mình nên làm gì?",
        "đọc_được": "metrics ctor, ctr: tỷ lệ chốt đơn giảm so với kỳ trước; ctr ổn định.",
        "emit_plan": {
            "lead": "Khách vào xem đủ nhưng ít chốt đơn, vấn đề nằm ở trang sản phẩm chứ "
            "không phải lượt xem.",
            "actions": [
                {
                    "lever": "review_voucher",
                    "card_ref": "draft:d1",
                    "why": "Tỷ lệ chốt đơn giảm: thêm lý do tin tưởng bằng mã cho khách đánh giá.",
                },
                {
                    "lever": "description_first_line",
                    "card_ref": "draft:d2",
                    "why": "Dòng đầu mô tả là chỗ khách đọc trước khi quyết định.",
                },
                {
                    "lever": "cover_image",
                    "card_ref": "draft:d3",
                    "why": "Ảnh bìa cần nói rõ lợi ích chính để khách chốt đơn.",
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
    "không tự tính, không thêm số nào khác. Tên sản phẩm chép nguyên văn như trong kết quả công "
    "cụ, hoặc không nêu tên.\n"
    "- Mô tả mỗi công cụ cho biết nó có thể thấy phát hiện nào và lever nào cho phép; kết quả có "
    "'phát_hiện_và_lever'. Đọc dữ liệu theo câu hỏi trước (chiến dịch, sản phẩm, kênh, chỉ số, "
    "lịch sale); open_cards chỉ để xem thẻ có sẵn nào khớp lever, đọc sau cùng, đừng lấy danh "
    "sách thẻ làm danh sách việc.\n"
    "- Chỉ đưa vào 'actions' việc có phát hiện thật trong dữ liệu, chọn lever trong danh sách "
    "cho phát hiện đó. Phát hiện không có lever, câu hỏi có tiền đề sai (số liệu nói khác), kỳ "
    "có ngày sale, dữ liệu thiếu: viết vào 'lead', không đưa vào 'actions'. Khi tiền đề của "
    "người bán sai, nói đúng sự thật ở 'lead' trước, rồi vẫn liệt kê việc thật nếu có.\n"
    "- 'actions' sắp theo tác động: chỗ đang mất tiền trước (lỗ sau quảng cáo, chi quảng cáo "
    "không ra đơn), rồi ngân sách và ROAS, rồi tăng trưởng. Mỗi lever chỉ một mục: nhiều sản "
    "phẩm hoặc chiến dịch cùng lever thì gộp thành một mục và nêu trong why. Mỗi mục: lever, "
    "card_ref, why (1-2 câu: điều dữ liệu cho thấy).\n"
    "- Câu hỏi về ngày sale / sự kiện sắp tới: đọc calendar (ngày_sale_sắp_tới) và chọn lever "
    "sự kiện (flash_sale, program_registration, mega_sale, min_spend_voucher). Câu hỏi khách xem "
    "nhiều ít chốt đơn hoặc CTR thấp: đọc metrics (ctor, ctr) và chọn lever trang sản phẩm "
    "(review_voucher, description_first_line, cover_image, price_display, title).\n"
    "- Việc nên làm lấy từ công cụ opportunities (mỗi dòng có lever, kết quả, lợi nhuận tăng). "
    "Hỏi một lever không có dòng nào: trả lời 'chưa có cơ hội' kèm lý do của dòng, không thử lại. "
    "Tạo thẻ nháp bằng draft_card với mã cơ hội ('mã'). Muốn so sánh 4 phương án thì gọi compare.\n"
    "- card_ref bắt buộc: 'open:<mã thẻ>' của một thẻ đang có trong open_cards, hoặc "
    "'draft:<ref>' do draft_card trả về (theo mã cơ hội). Mỗi thẻ trong open_cards có trường "
    "'lever' (loại của thẻ): chỉ dùng open:<mã> cho action có lever đúng bằng lever của thẻ đó; "
    "việc khác lever thì gọi opportunities rồi draft_card với mã cơ hội đúng lever trước khi "
    "emit_plan. "
    "Nếu draft_card báo chưa có phương án, đọc 'lý_do': thử "
    "lại với item khác nếu được, không thì đưa việc đó vào 'lead' hoặc bỏ. Riêng lever "
    "nhap_gia_von (không phải thẻ, card_ref 'none') chỉ dùng khi rank (cost_coverage, lọc dưới "
    "1) báo thiếu giá vốn; "
    "giá vốn đã đủ thì nói ở 'lead', không đưa vào 'actions'. Kết quả rank theo chiến dịch liệt kê "
    "sản_phẩm_chạy_quảng_cáo của từng chiến dịch: dùng id đó làm item cho lever quảng cáo của "
    "chiến dịch.\n"
    "- Chiến dịch có nhiều sản phẩm mà một sản phẩm lỗ: ads_remove_product (chỉ ads_pause khi nó "
    "là sản phẩm duy nhất). Ngày chi dưới ngân sách là ngày chi dưới 30% ngân sách ngày và không "
    "có đơn quảng cáo. Câu hỏi về tháng: gọi công cụ với window mtd_vs_same_days_last_month.\n"
    "- Không lặp lại số liệu mà không kèm quyết định. Không viết giá trị hay dự báo của thẻ, "
    "không dùng từ kỹ thuật, không mã, không tiếng Anh.\n"
    "- Tối đa 3 lượt gọi công cụ, rồi emit_plan.\n"
    "Ví dụ (tên và số trong ví dụ là giả, không phải của shop này; đừng chép số):\n"
    + "\n".join(json.dumps(ex, ensure_ascii=False) for ex in FEW_SHOT)
)


def tool_specs(kinds: list[str]) -> list[dict[str, Any]]:
    """The tools, generated from the registry ids and the kinds table (#53)."""
    out = [*advisor_tools.specs(kinds), plan_tool(kinds)]
    for spec in out:  # each tool says which findings it can show and their allowed levers
        spec["description"] += levers.describe(spec["name"])
    return out


def plan_tool(kinds: Iterable[str] | None = None) -> dict[str, Any]:
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
    opps: dict[str, dict[str, Any]] = field(default_factory=dict)  # opportunity id -> stored row
    windows: dict[str, str] = field(default_factory=dict)  # window label -> sale note
    drafts: dict[str, dict[str, Any]] = field(default_factory=dict)  # ref -> {acc, event}
    draft_log: list[dict[str, Any]] = field(default_factory=list)  # every draft_card outcome
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
                "lever": card_lever(c),
                "loại": ctx.labels.kind(lv) if (lv := card_lever(c)) else None,
                "sản_phẩm": names.get(str(item)) if item else None,
                "trạng_thái": c.get("status"),
                "thay_đổi": c.get("change_after"),
            }
        )
    return {"thẻ": out}


def card_lever(card: dict[str, Any]) -> str | None:
    """The card's own kind id (the lever it answers). Stored `kind` is the coarse proposal kind
    ("ads", "other"); the card's `change_kind` is the lever id. A row without `change_kind` keeps
    a fine id in `kind` (older readers, tests); a coarse kind alone names no lever (None)."""
    fine = card.get("change_kind") or card.get("kind")
    return str(fine) if fine in levers.lever_enum() else None


TOOLS = {**advisor_tools.TOOLS, "open_cards": _open_cards}


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
    if (
        name not in ("draft_card", "compare")
        and "lỗi" not in res
        and (tags := levers.tags_for(name))
    ):
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
    """sanitise each sentence (a leaking sentence is dropped, the others stay), then drop the
    sentences whose numbers are untraced."""
    kept: list[str] = []
    dropped: list[str] = []
    for sent in (x.strip() for x in _SENTENCE.split((text or "").strip())):
        if not sent:
            continue
        clean, leaks = writer.sanitise(sent, id_names, names)
        if leaks:
            dropped += [f"leak:{x}" for x in leaks]
            continue
        kept.append(clean)
    text_out, untraced = keep_traced(" ".join(kept), fact_set, names)
    return text_out, dropped + untraced


#: What `check_plan` found wrong with an action (the model sees these words in the refusal).
_PROBLEM_VI = {
    "no_ref": "thiếu card_ref",
    "unknown_ref": "card_ref không có trong open_cards hay thẻ nháp",
    "kind_mismatch": "thẻ của card_ref không đúng loại với lever",
    "bad_lever": "lever không nằm trong danh sách",
    "no_evidence": "lever này chỉ dùng khi công cụ đã báo đúng phát hiện của nó (ví dụ rank "
    "cost_coverage "
    "báo thiếu giá vốn); chưa có thì bỏ hoặc ghi ở lead",
    "dup_lever": "lever đã dùng ở mục trước: gộp các việc cùng lever thành một mục, nêu các sản "
    "phẩm hoặc chiến dịch trong why",
}


@dataclass
class _Checked:
    lever: str
    why: str
    problem: str | None = None  # a _PROBLEM_VI key
    ref: str | None = None
    card_kind: str | None = None  # the kind id of the card the ref points to
    code: str = ""  # open card code
    event: dict[str, Any] | None = None  # the draft's card event
    acc: dict[str, Any] | None = None


def _has_evidence(ctx: Ctx, lever: str) -> bool:
    _tool, key = levers.EVIDENCE[lever]
    return any(isinstance(r, dict) and r.get(key) for r in ctx.results)


def check_plan(
    ctx: Ctx, open_by_code: dict[str, dict[str, Any]], actions: list[Any]
) -> list[_Checked]:
    """Schema, refs and kinds only: no lever is chosen here. An action is valid when its lever is in
    the enum and its card_ref is an open card or a draft of this run whose kind is the lever (the
    non-card levers need no card)."""
    allowed = set(levers.lever_enum(ctx.labels.kinds))
    out: list[_Checked] = []
    seen: set[str] = set()
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
        elif lever in seen:
            c.problem = "dup_lever"
        elif lever in levers.EVIDENCE and not _has_evidence(ctx, lever):
            c.problem = "no_evidence"
        elif lever in levers.CARD_EXEMPT:
            pass
        elif not c.ref or c.ref == "none":
            c.problem = "no_ref"
        elif c.ref.startswith("open:") and c.ref[5:] in open_by_code:
            c.code = c.ref[5:]
            card = open_by_code[c.code]
            c.card_kind = card_lever(card)
            if c.card_kind is None:  # a card that names no kind id (stored coarse kind only)
                same = cardstage.coarse(str(card.get("kind"))) == cardstage.coarse(lever)
            else:
                same = c.card_kind == lever
            if not same:
                c.problem = "kind_mismatch"
        elif c.ref.startswith("draft:") and c.ref[6:] in ctx.drafts:
            draft = ctx.drafts[c.ref[6:]]
            c.event, c.acc = draft["event"], draft["acc"]
            c.card_kind = str(draft["acc"].get("kind"))
            if c.card_kind != lever:
                c.problem = "kind_mismatch"
        else:
            c.problem = "unknown_ref"
        if not c.problem:
            seen.add(lever)
        out.append(c)
    return out


def refusal(checked: list[_Checked]) -> dict[str, Any]:
    """The tool result that sends the plan back: which actions failed and what to do."""
    return {
        "lỗi": "kế hoạch chưa hợp lệ, chưa được nhận",
        "mục_lỗi": [
            {
                "lever": c.lever,
                "card_ref": c.ref,
                "vấn_đề": _PROBLEM_VI[c.problem],
                **({"lever_của_thẻ": c.card_kind} if c.card_kind else {}),
            }
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


def _normalise(raw: Any) -> dict[str, Any] | None:
    """The plan as {lead: str, actions: list}: a missing lead or actions field is empty, not a
    failure (the model's tool input is not trusted to be complete)."""
    if not isinstance(raw, dict):
        return None
    lead, actions = raw.get("lead"), raw.get("actions")
    return {
        "lead": lead if isinstance(lead, str) else "",
        "actions": [a for a in actions if isinstance(a, dict)] if isinstance(actions, list) else [],
    }


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
            plan = _normalise(final.get("input"))
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
    if plan is None or not (plan["actions"] or plan["lead"].strip()):
        raise AdviceAborted("no_plan")
    fact_set = summary.given_facts({"answers": ctx.results})
    advice = await render(ctx, plan, fact_set, checked)
    advice.turns, advice.tools, advice.drafts = turns, used, ctx.draft_log
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
