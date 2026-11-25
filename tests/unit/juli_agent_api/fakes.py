"""Doubles for the Juli tab: a fake engine (T1's ``run``) and fake ports (T2's gate).

No network, no paid API: the engine emits a scripted event list through the real sink.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from juli_backend.services.juli_agent_api import Ports, TemplateInfo

TEMPLATES = [
    TemplateInfo("improve_gmv", "Tăng GMV"),
    TemplateInfo("improve_margin", "Tăng biên lợi nhuận"),
    TemplateInfo("improve_conversion", "Tăng tỉ lệ chuyển đổi"),
    TemplateInfo("reduce_cost", "Giảm chi phí"),
    TemplateInfo("increase_visibility", "Tăng hiển thị"),
]


def draft_card(ref: str = "d_000000000001") -> dict[str, Any]:
    """One ``AnswerResult.cards[i]`` as T1 returns it: the engine card from the recommendation
    engine (``cards_service.engine_card``), its versions with their stored results."""
    return {
        "draft_ref": ref,
        "kind": "product_discount",
        "item_id": "1001",
        "recommended": "Giảm 10%",
        "engine_card": {
            "kind": "product_discount",
            "title": "Giảm giá sản phẩm mẫu",
            "inputs": {"discount_pct": 10},
            "versions": [
                {
                    "label": "Giảm 10%",
                    "inputs": {"discount_pct": 10},
                    "result": {"estimable": True},
                },
                {"label": "Giảm 5%", "inputs": {"discount_pct": 5}, "result": {"estimable": True}},
            ],
        },
    }


DRAFT_CARD = draft_card()


def answer_events(*, with_card: bool = True) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = [
        {"type": "status", "payload": {"key": "thinking", "text_vi": "Đang tìm hiểu"}},
        {"type": "restated", "payload": {"text_vi": "Đang tìm hiểu: GMV 7 ngày qua"}},
        {"type": "text_delta", "payload": {"text": "GMV giảm "}},
        {"type": "text_delta", "payload": {"text": "vì đơn giảm."}},
    ]
    if with_card:
        events.append(
            {
                "type": "card",
                "payload": {
                    "draft_ref": "d_000000000001",
                    "kind": "product_discount",
                    "versions": [{"label_vi": "Giảm 10%", "recommended": True}],
                },
            }
        )
    events.append(
        {
            "type": "done",
            "payload": {
                "stop_reasons": ["explained"],
                "cost_usd": 0.0012,
                "routing": [{"intent": "why_changed", "answers": {"chain": {"choice": "gmv"}}}],
            },
        }
    )
    return events


@dataclass
class FakeResult:
    stop_reasons: list[str]
    cost_usd: float
    routing: list[dict[str, Any]]
    drafts: list[dict[str, Any]]
    as_of: Any = None


@dataclass
class FakeEngine:
    events: list[dict[str, Any]] = field(default_factory=answer_events)
    drafts: list[dict[str, Any]] | None = None  # None: one fresh draft per run
    raises: BaseException | None = None
    gate: asyncio.Event | None = None  # a run that waits (to test "running" / cancel)
    requests: list[dict[str, Any]] = field(default_factory=list)
    read_factories: list[Any] = field(default_factory=list)
    as_of: Any = None

    def templates(self) -> list[TemplateInfo]:
        return list(TEMPLATES)

    async def run(
        self,
        request: Mapping[str, Any],
        *,
        read_session_factory: Any,
        llm: Any,
        jev: Any,
        sink: Any,
    ) -> FakeResult:
        self.requests.append(dict(request))
        self.read_factories.append(read_session_factory)
        for event in self.events[:2]:
            await sink.emit(event)
        if self.gate is not None:
            await self.gate.wait()
        if self.raises is not None:
            raise self.raises
        for event in self.events[2:]:
            await sink.emit(event)
        return FakeResult(
            stop_reasons=["explained"],
            cost_usd=0.0012,
            routing=[{"intent": "why_changed", "answers": {"chain": {"choice": "gmv"}}}],
            drafts=list(self.drafts)
            if self.drafts is not None
            else [draft_card(f"d_{uuid.uuid4().hex[:12]}")],
            as_of=self.as_of,
        )


async def fake_ports(*, shop_id: uuid.UUID, platform: str, write_factory: Any) -> Ports:
    return Ports(llm=object(), jev=object())


__all__ = [
    "DRAFT_CARD",
    "draft_card",
    "TEMPLATES",
    "FakeEngine",
    "FakeResult",
    "answer_events",
    "fake_ports",
]
