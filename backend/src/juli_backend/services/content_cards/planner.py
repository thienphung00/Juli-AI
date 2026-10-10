"""The content run: playbooks and the deterministic planner (P14-E, D24.18).

Like the cover-image / promotion flows (``lever_flows.planner``), a content run
is an ordinary ``workflow_runs`` row executed by the ordinary ``WorkflowRunner``
-- same ``tool.*`` / ``assistant.text`` / ``workflow.*`` SSE events, same ledger
-- with its own playbook and a deterministic planner in place of the tool-loop
model. The ONE model call per script version is made by the planner itself
through ``drafter`` (structured output), and its token usage rides on the turn
the planner returns, so the run's cost rollup counts it.

Order: read the content performance → the listing → SEO words (video) / the
LIVE flash sales already running (LIVE) → narrate the seller's rules → draft
(bản 1) → *wait for the seller* (``content_choice``: Dùng / Soạn lại / Không
thực hiện) → *wait for the video / the LIVE* (``content_publish``) → look for it
on TikTok (``find_new_content``) → done: measurement starts.

Nothing is written to TikTok: there is no CONFIRM step, and no Hoàn tác.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

from juli_backend.services.agent.llm.blocks import (
    AssistantTurn,
    FinalResponse,
    TextBlock,
    ToolCallBlock,
    Usage,
)
from juli_backend.services.agent.llm.config import LLMConfig
from juli_backend.services.agent.llm.service import Message, ToolDefinition
from juli_backend.services.agent.playbooks import content as _content_playbooks
from juli_backend.services.content_cards import run_state
from juli_backend.services.content_cards.constants import (
    CONTENT_PERFORMANCE_TOOL,
    FIND_NEW_CONTENT_TOOL,
    VIDEO,
    ContentKind,
)
from juli_backend.services.content_cards.copy import pct
from juli_backend.services.content_cards.drafter import ContentDrafter, DraftInputs, DraftOutcome
from juli_backend.services.content_cards.guardrails import ContentRules, DraftFacts
from juli_backend.services.content_cards.tools import shop_today
from juli_backend.services.lever_flows.flows import AwaitSeller

logger = logging.getLogger(__name__)

CONTENT_VIDEO_PLAYBOOK = _content_playbooks.CONTENT_VIDEO_PLAYBOOK
CONTENT_LIVE_PLAYBOOK = _content_playbooks.CONTENT_LIVE_PLAYBOOK
CHOICE_WAIT_POLICY = _content_playbooks.CHOICE_WAIT_POLICY
PUBLISH_WAIT_POLICY = _content_playbooks.PUBLISH_WAIT_POLICY
READ_TOOL = _content_playbooks.READ_TOOL
SEO_TOOL = _content_playbooks.SEO_TOOL
PROMOTIONS_TOOL = _content_playbooks.PROMOTIONS_TOOL


def _turn(*blocks: Any, usage: Usage | None = None) -> AssistantTurn:
    return AssistantTurn(
        blocks=tuple(blocks), usage=usage or Usage(input_tokens=0, output_tokens=0)
    )


def _results(messages: Sequence[Message]) -> dict[str, list[Any]]:
    results: dict[str, list[Any]] = {}
    for message in messages:
        if isinstance(message, Mapping) and message.get("role") == "tool":
            results.setdefault(str(message.get("tool_name")), []).append(message.get("content"))
    return results


def _assistant_texts(messages: Sequence[Message]) -> list[str]:
    return [
        str(message.get("content"))
        for message in messages
        if isinstance(message, Mapping) and message.get("role") == "assistant"
    ]


def _text(envelope: Any) -> str:
    if isinstance(envelope, Mapping):
        return str(envelope.get("text") or "")
    return str(envelope or "")


def _prices(product: Mapping[str, Any]) -> tuple[int, ...]:
    block = product.get("sku_prices")
    items = block.get("items") if isinstance(block, Mapping) else None
    out: list[int] = []
    for item in items if isinstance(items, list) else []:
        amount = item.get("amount") if isinstance(item, Mapping) else None
        if isinstance(amount, int | float) and amount > 0:
            out.append(round(amount))
    return tuple(sorted(set(out)))


def _seo_words(seo: Mapping[str, Any] | None) -> list[str]:
    block = seo.get("seo_words") if isinstance(seo, Mapping) else None
    items = block.get("items") if isinstance(block, Mapping) else None
    return [_text(i) for i in items if _text(i)] if isinstance(items, list) else []


def rules_sentence(rules: ContentRules) -> str:
    """The narrated rules read (step 2 of the LIVE run shows it)."""
    parts = [
        f"Trần giảm giá {rules.discount_cap_pct:g} %"
        if rules.discount_cap_pct is not None
        else "Chưa đặt trần giảm giá"
    ]
    if rules.protected_terms:
        parts.append(f"{len(rules.protected_terms)} từ bảo vệ")
    if rules.banned_terms:
        parts.append(f"{len(rules.banned_terms)} từ cấm")
    parts.append(f"giọng: {rules.tone}" if rules.tone else "chưa đặt giọng văn")
    return "Quy tắc của bạn: " + " · ".join(parts)


#: Fast track P16 (D25.8): the shop is over its monthly OpenAI cap set in Ops.
DRAFT_ERROR_OPENAI_CAP = "openai_cap_reached"
_CAP_REACHED_VI = (
    "Juli tạm dừng soạn kịch bản mới cho shop này: đã chạm trần chi phí AI của tháng. "
    "Đội ngũ Juli đã được báo."
)


@dataclass(frozen=True)
class DraftGate:
    """What Juli Ops says about drafting for this shop (D25.4 model, D25.8 cap)."""

    model: str | None = None
    cap_reached: bool = False
    spent_usd: float = 0.0
    cap_usd: float | None = None


@dataclass
class ContentPlanner:
    """A deterministic ``LLMService`` for one content run (module docstring).

    ``state`` is the run's content state (``run_state``), a mutable copy the
    ``ContentRunner`` writes back when the leg suspends or ends. ``facts`` /
    ``rules`` come from the database (the worker reads them); the reads of the
    run complete them.
    """

    kind: ContentKind
    state: dict[str, Any]
    drafter: ContentDrafter
    rules: ContentRules
    facts: DraftFacts
    today: Any = shop_today
    #: Set when this leg drafted a version (the runner wrapper persists it).
    drafted: list[DraftOutcome] = field(default_factory=list)
    #: Juli Ops overrides for drafting (model, monthly cap); None = defaults.
    draft_gate: DraftGate | None = None

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        system: str,
        tools: Sequence[ToolDefinition],
        config: LLMConfig,
        tool_choice: str | None = None,
    ) -> AssistantTurn:
        del system, tools, tool_choice  # deterministic; the drafter has its own prompt
        results = _results(messages)
        performance = results.get(CONTENT_PERFORMANCE_TOOL, [])
        if not performance:
            return _turn(
                ToolCallBlock(
                    call_id="content-performance",
                    tool_name=CONTENT_PERFORMANCE_TOOL,
                    arguments={"kind": self.kind},
                )
            )
        last = performance[-1] if isinstance(performance[-1], Mapping) else {}
        self._stamp("read_content", summary=_text(last.get("summary_vi")), slot="performance")
        if READ_TOOL not in results:
            return _turn(ToolCallBlock(call_id="content-product", tool_name=READ_TOOL))
        if self.kind == VIDEO and SEO_TOOL not in results:
            return _turn(ToolCallBlock(call_id="content-seo", tool_name=SEO_TOOL))
        if self.kind != VIDEO and PROMOTIONS_TOOL not in results:
            return _turn(
                ToolCallBlock(
                    call_id="content-promotions",
                    tool_name=PROMOTIONS_TOOL,
                    arguments={"promotion_type": "flash_sale"},
                )
            )
        sentence = rules_sentence(self.rules)
        self._stamp("read_product", summary=self._product_summary(results), slot="product")
        if sentence not in _assistant_texts(messages):
            return _turn(TextBlock(text=sentence))

        stage = self.state.get("stage")
        if stage == run_state.STAGE_DRAFTING:
            return await self._draft(results, config)
        if stage == run_state.STAGE_CHOICE:
            raise AwaitSeller(
                awaiting=run_state.AWAITING_CHOICE, narration=run_state.NARRATION_CHOICE
            )
        if stage == run_state.STAGE_PUBLISH:
            raise AwaitSeller(
                awaiting=run_state.AWAITING_PUBLISH,
                narration=run_state.NARRATION_PUBLISH[self.kind],
            )
        if stage == run_state.STAGE_PUBLISHED:
            return self._detect(results)
        if stage == run_state.STAGE_FAILED:
            return _turn(FinalResponse(content=_FAILED_VI))
        return _turn(
            FinalResponse(content="Juli đã ghi nhận. Không có gì thay đổi trên TikTok Shop.")
        )

    # -- steps -------------------------------------------------------------------------

    def _stamp(self, step: str, *, summary: str | None, slot: str) -> None:
        at = self.state.setdefault("step_at", {})
        if step not in at:
            at[step] = run_state.now_iso()
        if summary:
            self.state.setdefault("reads", {})[slot] = summary

    def _product_summary(self, results: Mapping[str, list[Any]]) -> str:
        if self.kind == VIDEO:
            words = _seo_words(results.get(SEO_TOOL, [None])[-1])
            quoted = ", ".join(f"“{w}”" for w in words[:2])
            return (
                f"Mô tả, ảnh, từ khoá {quoted}" if quoted else "Mô tả, ảnh, chưa có từ khoá TikTok"
            )
        return rules_sentence(self.rules).removeprefix("Quy tắc của bạn: ")

    def _inputs(self, results: Mapping[str, list[Any]]) -> DraftInputs:
        product = results.get(READ_TOOL, [{}])[-1]
        product = product if isinstance(product, Mapping) else {}
        performance = results.get(CONTENT_PERFORMANCE_TOOL, [{}])[-1]
        performance = performance if isinstance(performance, Mapping) else {}
        prices = _prices(product) or self.facts.prices_vnd
        inventory = product.get("total_inventory_quantity")
        facts = replace(
            self.facts,
            prices_vnd=prices,
            inventory=int(inventory) if isinstance(inventory, int) else self.facts.inventory,
        )
        rows_key = "videos" if self.kind == VIDEO else "sessions"
        rows = [r for r in performance.get(rows_key) or [] if isinstance(r, Mapping)]
        summary = {
            "chỉ_số": "CTR video" if self.kind == VIDEO else "CTOR trong LIVE",
            "hiện_tại": pct(performance.get("rate"))
            if performance.get("rate") is not None
            else None,
            "mục_tiêu": pct(self.state.get("target")) if self.state.get("target") else None,
            "trung_bình_shop": pct(performance.get("shop_rate"))
            if performance.get("shop_rate") is not None
            else None,
            "các_dòng": [
                {
                    "tiêu_đề": _text(r.get("title")),
                    "ngày": r.get("posted_on") or r.get("started_on"),
                    "tỉ_lệ": pct(r.get("ctr") if self.kind == VIDEO else r.get("product_ctor")),
                    **(
                        {"vị_trí_giỏ": r.get("basket_position")}
                        if self.kind != VIDEO and r.get("basket_position")
                        else {}
                    ),
                }
                for r in rows[:5]
            ],
        }
        examples = [
            {
                "tiêu_đề": _text(e.get("title")),
                "tỉ_lệ": pct(e.get("ctr") if self.kind == VIDEO else e.get("ctor")),
                **({"hashtag": e.get("hashtags")} if e.get("hashtags") else {}),
            }
            for e in performance.get("examples") or []
            if isinstance(e, Mapping)
        ]
        description = _text(product.get("description"))
        return DraftInputs(
            facts=facts,
            rules=self.rules,
            performance=summary,
            product={"description": description},
            seo_words=_seo_words(results.get(SEO_TOOL, [None])[-1]) if self.kind == VIDEO else [],
            examples=examples,
        )

    async def _draft(self, results: Mapping[str, list[Any]], config: LLMConfig) -> AssistantTurn:
        version = int(self.state.get("requested_version") or 1)
        previous = run_state.draft(self.state, version - 1) if version > 1 else None
        inputs = self._inputs(results)
        # What the seller's own edits are checked against later (the routes have
        # no TikTok read of their own).
        self.state["facts"] = {
            "product_label": inputs.facts.product_label,
            "product_title": inputs.facts.product_title,
            "prices_vnd": list(inputs.facts.prices_vnd),
            "inventory": inputs.facts.inventory,
            "basket_skus": list(inputs.facts.basket_skus),
        }
        self.state["rules"] = {
            "tone": self.rules.tone,
            "banned_terms": list(self.rules.banned_terms),
            "protected_terms": list(self.rules.protected_terms),
            "discount_cap_pct": self.rules.discount_cap_pct,
        }
        gate = self.draft_gate or DraftGate()
        if gate.cap_reached:
            # D25.8: no new drafting over the cap; the team is alerted by this
            # log line (and the Ops overview badge). Rule cards keep running.
            logger.warning(
                "ops_openai_cap_reached",
                extra={
                    "kind": self.kind,
                    "spent_usd": gate.spent_usd,
                    "cap_usd": gate.cap_usd,
                },
            )
            self.state["stage"] = run_state.STAGE_FAILED
            self.state["error"] = DRAFT_ERROR_OPENAI_CAP
            return _turn(FinalResponse(content=_CAP_REACHED_VI))
        if gate.model:
            config = replace(config, model=gate.model)
        outcome = await self.drafter.draft(
            kind=self.kind,
            inputs=inputs,
            version=version,
            previous=previous.get("script") if previous else None,
            config=config,
        )
        self.drafted.append(outcome)
        drafts = [d for d in self.state.get("drafts") or [] if d.get("version") != version]
        drafts.append(
            {
                "version": version,
                "script": outcome.script,
                "checks": outcome.verdict.to_json() if outcome.verdict else [],
                "error": outcome.error,
                "detail": outcome.detail,
                "model": outcome.model,
                "input_tokens": outcome.usage.input_tokens,
                "output_tokens": outcome.usage.output_tokens,
                "at": run_state.now_iso(),
            }
        )
        self.state["drafts"] = drafts
        self.state.setdefault("step_at", {})["draft"] = run_state.now_iso()
        if outcome.ok:
            self.state["stage"] = run_state.STAGE_CHOICE
            return _turn(
                TextBlock(text=f"Đã soạn kịch bản (bản {version}) · {run_state.MODEL_STEP_RESULT}"),
                usage=outcome.usage,
            )
        if version < run_state.MAX_VERSIONS:
            self.state["stage"] = run_state.STAGE_CHOICE
            return _turn(
                TextBlock(
                    text=(
                        f"Bản {version} chưa đạt kiểm tra nên Juli không hiển thị. "
                        "Bạn bấm Soạn lại để Juli soạn bản khác."
                    )
                ),
                usage=outcome.usage,
            )
        self.state["stage"] = run_state.STAGE_FAILED
        return _turn(FinalResponse(content=_FAILED_VI), usage=outcome.usage)

    def _detect(self, results: Mapping[str, list[Any]]) -> AssistantTurn:
        finds = results.get(FIND_NEW_CONTENT_TOOL, [])
        rounds = int(self.state.get("detect_rounds") or 1)
        since = str(self.state.get("chosen_at") or run_state.now_iso())[:10]
        if len(finds) < rounds:
            return _turn(
                ToolCallBlock(
                    call_id=f"content-find-{rounds}",
                    tool_name=FIND_NEW_CONTENT_TOOL,
                    arguments={"kind": self.kind, "since": since},
                )
            )
        latest = finds[-1] if isinstance(finds[-1], Mapping) else {}
        found = [f for f in latest.get("found") or [] if isinstance(f, Mapping)]
        detected = self.state.get("detected")
        if found and not detected:
            self.state["detected"] = dict(found[0])
            detected = self.state["detected"]
        if isinstance(detected, Mapping) and detected.get("day"):
            start = str(detected["day"])
        else:
            published = str(self.state.get("published_at") or "")[:10]
            start = published or self.today().isoformat()
        self.state["measurement_start"] = start
        self.state["stage"] = run_state.STAGE_MEASURING
        self.state.setdefault("step_at", {})["publish"] = run_state.now_iso()
        d0 = date.fromisoformat(start)
        if self.kind == VIDEO:
            from datetime import timedelta

            d7, d14 = d0 + timedelta(days=7), d0 + timedelta(days=14)
            text = (
                f"Juli bắt đầu đo CTR trên video mới từ {d0:%d/%m}: đo sơ bộ {d7:%d/%m} "
                f"(ngày 7), chốt {d14:%d/%m} (ngày 14)."
            )
        else:
            text = "Juli bắt đầu đo CTOR ở 3 phiên LIVE kế tiếp có bán sản phẩm."
        prefix = "Đã thấy trên TikTok. " if found else ""
        return _turn(FinalResponse(content=prefix + text))


_FAILED_VI = "Juli chưa soạn được kịch bản đạt kiểm tra. Không có gì thay đổi trên TikTok Shop."


def termination_policy_for(awaiting: str | None):
    """The reaper's policy for a content run waiting on ``awaiting``, else ``None``."""
    if awaiting == run_state.AWAITING_CHOICE:
        return CHOICE_WAIT_POLICY
    if awaiting == run_state.AWAITING_PUBLISH:
        return PUBLISH_WAIT_POLICY
    return None


__all__ = [
    "CHOICE_WAIT_POLICY",
    "CONTENT_LIVE_PLAYBOOK",
    "CONTENT_VIDEO_PLAYBOOK",
    "PUBLISH_WAIT_POLICY",
    "ContentPlanner",
    "rules_sentence",
    "termination_policy_for",
]
