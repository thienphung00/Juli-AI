"""The analytics agent engine: question (or template) -> intent -> Jev routing -> chain or data
answer
-> gated card -> explanation -> a stream of events. Pure read-only (CONTRACT.md `run`).

LLM and Jev only through the ports; data only through `DataPort`; card values only from the
recommendation engine. Nothing is written, nothing persisted.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from juli_backend.services.analytics_agent import cards as cardstage
from juli_backend.services.analytics_agent import (
    entities,
    lookup,
    present,
    routing,
    windows,
    writer,
)
from juli_backend.services.analytics_agent.cards_service import ServiceCardEngine
from juli_backend.services.analytics_agent.chains import CHAIN_METRIC, ChainResult, run_chain
from juli_backend.services.analytics_agent.data_service import ServiceData, SessionFactory
from juli_backend.services.analytics_agent.types import (
    TEMPLATE_BY_KEY,
    TEMPLATES,
    AnswerResult,
    AskRequest,
    CardEnginePort,
    DataPort,
    EventSink,
    JevPort,
    LabelTable,
    LLMPort,
    Template,
)

VN = ZoneInfo("Asia/Ho_Chi_Minh")
CHAIN_TIMEOUT_ENV = "JULI_AGENT_CHAIN_TIMEOUT_S"
DEFAULT_CHAIN_TIMEOUT_S = 90.0
#: a chain must end before the run's own 120 s limit, so the answer is `busy`, not a cut-off stream
MAX_CHAIN_TIMEOUT_S = 110.0


def chain_timeout_s() -> float:
    """The chain's time limit: env, default 90 s, capped under the run limit; bad -> default."""
    try:
        value = float(os.environ.get(CHAIN_TIMEOUT_ENV, "").strip())
    except ValueError:
        return DEFAULT_CHAIN_TIMEOUT_S
    return min(value, MAX_CHAIN_TIMEOUT_S) if value > 0 else DEFAULT_CHAIN_TIMEOUT_S


UNSUPPORTED_VI = "Juli chưa hỗ trợ câu hỏi này"
NO_TIKTOK_CARD_VI = "Chưa có đề xuất cho TikTok"
ANALYTICS_PLATFORMS = ("shopee",)  # TikTok joins when P101 W3 opens its analytics routes (U12)
#: Platforms whose recommendation engine can fill a draft card (Shopee only for now).
CARD_PLATFORMS = ("shopee",)


class _Out:
    """Records every event for AnswerResult and forwards it to the sink."""

    def __init__(self, sink: EventSink, result: AnswerResult) -> None:
        self.sink, self.result = sink, result

    async def emit(self, event: dict[str, Any]) -> None:
        self.result.events.append(event)
        await self.sink.emit(event)


async def _latest(data: DataPort, as_of: date) -> date | None:
    """The newest complete day held (the freshness line); calendar windows do not depend on it."""
    rows = await data.shop_daily(as_of)
    return max((r["day"] for r in rows if r["complete"]), default=None)


def _platform_has_analytics(platform: str) -> bool:
    from juli_backend.services.capabilities.registry import Route, can

    return platform in ANALYTICS_PLATFORMS and can(platform, "read_shop_totals").route != Route.none


def _window_args(intent: dict[str, Any], dec: dict[str, Any]) -> dict[str, Any]:
    kw: dict[str, Any] = {}
    if intent.get("explicit_from") and intent.get("explicit_to"):
        try:
            kw["explicit"] = (
                date.fromisoformat(intent["explicit_from"]),
                date.fromisoformat(intent["explicit_to"]),
            )
        except ValueError:
            pass
    if intent.get("named_month") and dec.get("window") == "named_month_vs_previous":
        kw["named_month"] = intent["named_month"]
    return kw


def _other_platform(intent: dict[str, Any], platform: str) -> str | None:
    s = f"{intent.get('source_phrase') or ''} {intent.get('metric_phrase') or ''}".lower()
    for p in ("tiktok", "shopee"):
        if p != platform and p in s:
            return p
    return None


async def run(
    req: AskRequest,
    *,
    read_session_factory: SessionFactory | None = None,
    llm: LLMPort,
    jev: JevPort,
    sink: EventSink,
    labels: LabelTable,
    data: DataPort | None = None,
    card_engine: CardEnginePort | None = None,
    now: Callable[[], datetime] | None = None,
    max_intents: int | None = None,
) -> AnswerResult:
    """Run one ask. `data` / `card_engine` default to the service-backed adapters over
    `read_session_factory`."""
    t0 = time.monotonic()
    result = AnswerResult()
    out = _Out(sink, result)
    clock = now or (lambda: datetime.now(VN))
    if data is None:
        assert read_session_factory is not None, "read_session_factory or data is required"
        data = ServiceData(read_session_factory, req.shop_id)
        card_engine = card_engine or ServiceCardEngine(read_session_factory, req.shop_id)
    as_of = req.as_of or (clock().date() - timedelta(days=1))
    try:
        await out.emit(present.status("thinking"))
        await _run(req, out, result, data, card_engine, llm, jev, labels, as_of, max_intents)
    except TimeoutError:
        await out.emit({"type": "error", "code": "busy"})
        result.stop_reasons.append("error")
    except Exception:  # the seller sees "Juli đang gặp sự cố"; T3 logs the cause
        await out.emit({"type": "error", "code": "failed"})
        result.stop_reasons.append("error")
        raise
    finally:
        await out.emit(
            {
                "type": "done",
                "stop_reasons": result.stop_reasons,
                "cost_usd": round(result.cost_usd, 6),
                "ms": int((time.monotonic() - t0) * 1000),
                "routing": result.routing,
            }
        )
    return result


async def _unsupported(
    out: _Out, result: AnswerResult, platform: str, switch: str | None = None
) -> None:
    ev: dict[str, Any] = {
        "type": "unsupported",
        "text_vi": UNSUPPORTED_VI,
        "templates": [t.key for t in TEMPLATES],
    }
    if switch:
        ev["switch_platform"] = switch
    await out.emit(ev)
    result.stop_reasons.append("unsupported")


async def _run(
    req: AskRequest,
    out: _Out,
    result: AnswerResult,
    data: DataPort,
    engine: CardEnginePort | None,
    llm: LLMPort,
    jev: JevPort,
    labels: LabelTable,
    as_of: date,
    max_intents: int | None,
) -> None:
    template: Template | None = TEMPLATE_BY_KEY.get(req.template) if req.template else None
    # The window the seller sees is the window that runs (B2): one anchor per ask, kept in
    # `pending` across a clarifying choice.
    pinned = (req.pending or {}).get("anchor") if req.choice else None
    if pinned:
        as_of = date.fromisoformat(pinned)
    latest = await _latest(data, as_of) if _platform_has_analytics(req.platform) else None
    blocks: list[tuple[dict[str, Any], dict[str, Any]]] = []  # (intent, decision)
    more: list[dict[str, Any]] = []
    if req.template and template is None:
        await _unsupported(out, result, req.platform)
        return
    if template:
        restated = routing.RESTATE_PREFIX + template.label_vi
        blocks.append(
            (
                {},
                {
                    "outcome": "go",
                    "mode": "why",
                    "chain": template.chain,
                    "metric": template.metric,
                    "window": template.window,
                    "scope": "shop",
                },
            )
        )
    elif req.choice and req.pending:
        dec = routing.resume(req.pending, req.choice)
        restated = req.pending.get("restated") or routing.RESTATE_PREFIX
        blocks.append((req.pending["intent"], dec))
        # the intents queued behind the one that asked: every intent gets its answer (B4)
        blocks.extend((i, d) for i, d in req.pending.get("rest") or [])
        more = req.pending.get("more") or []
    else:
        parsed, usage = await routing.parse_intents(llm, req.text or "", as_of)
        result.cost_usd += usage.cost_usd
        if parsed is None:  # parse failed twice: template buttons (J11)
            await _unsupported(out, result, req.platform)
            return
        restated = parsed["restated"]
        intents = parsed["intents"][: max_intents or routing.MAX_INTENTS]
        more = parsed["more"] + parsed["intents"][max_intents or routing.MAX_INTENTS :]
        # one Jev routing request per intent, in parallel
        replies = await asyncio.gather(
            *(jev.ask(routing.jev_state(i), routing.routing_questions(i)) for i in intents)
        )
        for intent, (answers, u) in zip(intents, replies, strict=True):
            result.cost_usd += u.cost_usd
            dec = routing.decide(intent, answers)
            result.routing.append(
                {
                    "intent": routing.jev_state(intent)["intent"],
                    "checks": dec["checks"],
                    "outcome": dec["outcome"],
                    "answers": answers,
                }
            )
            blocks.append((intent, dec))
    await out.emit({"type": "restated", "text_vi": restated})
    total = len(blocks)
    for idx, (intent, dec) in enumerate(blocks, 1):
        if total > 1:
            await out.emit(
                {
                    "type": "intent_block",
                    "index": idx,
                    "total": total,
                    # Vietnamese always: the parsed intent is English (metric_phrase too)
                    "title_vi": f"Câu {idx}/{total}"
                    + (f" · {labels.metric(str(dec['metric']))}" if dec.get("metric") else ""),
                }
            )
        if dec["outcome"] == "unsupported":
            await _unsupported(out, result, req.platform, _other_platform(intent, req.platform))
            continue
        if (
            dec.get("window") == "this_week_vs_same_days_last_week"
            and windows.this_week_empty(as_of)
            and not (intent.get("explicit_from") and intent.get("explicit_to"))
        ):  # Monday: no complete day this week; offer last week, never a one-day window
            dec = {
                **dec,
                "outcome": "needs_choice",
                "remaining": [("window", ["last_full_week_vs_week_before"])],
            }
            no_day = True
        else:
            no_day = False
        if dec["outcome"] == "needs_choice":
            ev = routing.needs_choice_event(
                dec, intent, labels, as_of, dec.get("turns", 0), latest=latest
            )
            if no_day:
                ev["question_vi"] = routing.NO_FULL_DAY_VI
            ev["pending"]["anchor"] = as_of.isoformat()
            ev["pending"]["restated"] = restated
            ev["pending"]["more"] = more
            ev["pending"]["rest"] = [
                [i, {k: v for k, v in d.items() if k != "checks"}] for i, d in blocks[idx:]
            ]
            await out.emit(ev)
            result.stop_reasons.append("needs_choice")
            return  # one unclear item at a time; the tap resumes from pending
        await _answer(
            req, out, result, data, engine, llm, jev, labels, as_of, intent, dec, restated, template
        )
    if more:
        await out.emit(
            {
                "type": "more",
                "items": [
                    {
                        "label_vi": i.get("metric_phrase") or "Câu hỏi tiếp",
                        "text": i.get("metric_phrase") or "",
                    }
                    for i in more
                ],
            }
        )


async def _answer(
    req: AskRequest,
    out: _Out,
    result: AnswerResult,
    data: DataPort,
    engine: CardEnginePort | None,
    llm: LLMPort,
    jev: JevPort,
    labels: LabelTable,
    as_of: date,
    intent: dict[str, Any],
    dec: dict[str, Any],
    restated: str,
    template: Template | None,
) -> None:
    mode = dec.get("mode", "why")
    preset = dec.get("window") or "last_7d_vs_prev_7d"
    item_id: str | None = dec.get("item_id")
    if dec.get("scope") == "product" and not item_id and intent.get("product_phrase"):
        prod, u = await routing.resolve_product(data, jev, intent)
        result.cost_usd += u.cost_usd
        if prod["status"] == "found":
            item_id = prod["item_id"]
        else:
            opts = [
                {"label_vi": o["name"] or o["item_id"], "value": o["item_id"]}
                for o in prod.get("options", [])
            ]
            await out.emit(
                {
                    "type": "needs_choice",
                    "item": "product",
                    "question_vi": routing.QUESTION_VI["product"],
                    "options": opts,
                    "pending": {
                        "intent": intent,
                        "dec": {k: v for k, v in dec.items() if k not in ("remaining", "outcome")},
                        "remaining": [["product", [o["value"] for o in opts]]],
                        "turns": dec.get("turns", 0),
                        "restated": restated,
                        "anchor": as_of.isoformat(),
                    },
                }
            )
            result.stop_reasons.append("needs_choice")
            return
    if not _platform_has_analytics(req.platform):  # TikTok before P101 W3 (U12)
        await out.emit(
            {
                "type": "label",
                "stop_reason": "data_missing",
                "text_vi": "Thiếu dữ liệu",
                "detail_vi": None,
            }
        )
        await out.emit({"type": "no_card", "reason_vi": NO_TIKTOK_CARD_VI})
        result.stop_reasons.append("data_missing")
        return
    await out.emit(present.status("checking_data"))
    kw = _window_args(intent, dec)
    entity = routing.entity_kind(intent)
    prod_money = bool(item_id and dec.get("metric") in ("profit", "margin", "ads_spend", "roas"))
    if entity or prod_money:  # Q17: the entity's own rows, or "Juli chưa có số liệu này"
        names = await data.item_names([item_id]) if item_id else {}
        answers = await entities.run_entity(
            entity,
            data,
            intent,
            dec.get("metric"),
            preset,
            as_of,
            item_id=item_id,
            item_name=names.get(item_id) if item_id else None,
            **kw,
        )
        if not answers:
            await out.emit(
                {
                    "type": "label",
                    "stop_reason": "data_missing",
                    "text_vi": entities.NO_DATA_VI,
                    "detail_vi": None,
                }
            )
            result.stop_reasons.append("data_missing")
            return
        for a in answers:
            await out.emit(a)
        result.stop_reasons.append("data_answer")
        return
    if mode == "lookup":
        metric = dec.get("metric") or lookup.default_metric(dec.get("chain"))
        ans = await lookup.run_lookup(
            data,
            labels,
            dec.get("lookup", "metric_total"),
            metric,
            preset,
            as_of,
            item_id=item_id,
            **kw,
        )
        if ans.get("stop") == "data_missing":
            await out.emit(
                {
                    "type": "label",
                    "stop_reason": "data_missing",
                    "text_vi": "Thiếu dữ liệu",
                    "detail_vi": None,
                }
            )
            result.stop_reasons.append("data_missing")
            return
        ans.pop("stop", None)
        await out.emit(ans)
        result.stop_reasons.append("data_answer")
        return
    chain_name = dec.get("chain") or "gmv_change"
    metric = dec.get("metric") or CHAIN_METRIC.get(chain_name)
    if (
        metric
        and CHAIN_METRIC.get(chain_name) not in (None, metric)
        and metric not in routing.CHAIN_ALLOWED_METRICS.get(chain_name, set())
    ):
        metric = CHAIN_METRIC[chain_name]
    chain = await asyncio.wait_for(
        run_chain(data, chain_name, metric, preset, as_of, item_id=item_id, **kw), chain_timeout_s()
    )
    await out.emit(present.comparing(chain))
    await out.emit(present.status("finding_cause"))
    result.stop_reasons.append(chain.stop_reason)
    chain_json = chain.json(labels)
    path = present.path_steps(chain, labels)
    if path:
        await out.emit({"type": "path", "steps": path})
    lab = present.label_event(chain)
    if lab:
        await out.emit(lab)
    # card stage: chain -> card decision -> answer
    outcome = cardstage.CardOutcome()
    if req.platform in CARD_PLATFORMS and engine is not None:
        await out.emit(present.status("preparing_card"))
        outcome = await cardstage.card_stage(
            chains=[chain],
            data=data,
            engine=engine,
            jev=jev,
            labels=labels,
            as_of=as_of,
            template=template,
        )
        result.cost_usd += outcome.cost_usd
        result.routing.extend(outcome.routing)
    id_names = await data.item_names(
        sorted(
            {
                f.evidence_ref.split("product:")[1]
                for f in chain.findings
                if "product:" in (f.evidence_ref or "")
            }
        )
    )
    note = [{"loại": a["kind_vi"], "sản_phẩm": a["item_name"]} for a in outcome.accepted]
    expl, meta = await writer.write_explanation(
        llm,
        lambda t: out.emit({"type": "text_delta", "text": t}),
        lambda t: out.emit({"type": "text_replace", "text": t}),
        restated,
        [chain_json],
        outcome.accepted,
        labels,
        id_names,
        note,
        cardstage.card_figures(outcome.accepted),
    )
    result.cost_usd += meta["cost_usd"]
    result.routing.append(
        {
            "step": "writer",
            "rewrites": meta["rewrites"],
            "template": meta["template"],
            "issues": meta["issues"],
            "numbers_failed": meta["numbers_failed"],
        }
    )
    if (
        template
        and chain.stop_reason != "explained"
        and outcome.accepted
        and outcome.accepted[0].get("critical")
    ):
        c = outcome.accepted[0]
        await out.emit(
            {
                "type": "text_replace",
                "text": (
                    f"{expl}\n\nKhông có thay đổi lớn; cơ hội lớn nhất là {c['kind_vi'].lower()}"
                    + (f" cho {c['item_name']}" if c.get("item_name") else "")
                    + "."
                ),
            }
        )
    for ev in outcome.events:
        await out.emit(ev)
    for a in outcome.accepted:
        result.cards.append(
            {
                "draft_ref": a["ref"],
                "kind": a["kind"],
                "item_id": a["item_id"],
                "recommended": a["recommended"],
                "engine_card": a["engine_card"],
            }
        )


__all__ = ["run", "ChainResult"]
