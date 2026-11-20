"""Public types and ports of the analytics agent (CONTRACT.md, T1 public API)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal, Protocol

AgentEvent = dict[str, Any]


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True)
class Template:
    key: str
    label_vi: str
    chain: str
    metric: str
    window: str = "last_7d_vs_prev_7d"
    allows_card_any_stop: bool = True


TEMPLATES: tuple[Template, ...] = (
    Template("improve_gmv", "Cải thiện GMV", "gmv_change", "gmv"),
    Template("improve_margin", "Cải thiện biên lợi nhuận", "profit_change", "margin"),
    Template("improve_conversion", "Cải thiện tỷ lệ chuyển đổi", "ctor_change", "ctor"),
    Template("reduce_cost", "Giảm chi phí", "cost_change", "cost_ratio"),
    Template("increase_visibility", "Tăng lượt hiển thị", "ctr_change", "views"),
)
TEMPLATE_BY_KEY = {t.key: t for t in TEMPLATES}


@dataclass(frozen=True)
class AskRequest:
    shop_id: uuid.UUID
    platform: Literal["shopee", "tiktok"]
    text: str | None = None
    template: str | None = None
    choice: dict[str, Any] | None = None
    pending: dict[str, Any] | None = None
    as_of: date | None = None


class LLMPort(Protocol):
    async def parse(
        self, system: str, tool: dict[str, Any], user: str
    ) -> tuple[dict[str, Any] | None, Usage]: ...

    def stream_text(self, system: str, user: str) -> AsyncIterator[str]: ...

    async def text(self, system: str, user: str) -> tuple[str, Usage]: ...


class JevPort(Protocol):
    async def ask(
        self, state: dict[str, Any], questions: dict[str, dict[str, Any]]
    ) -> tuple[dict[str, dict[str, Any]], Usage]: ...


class EventSink(Protocol):
    async def emit(self, event: AgentEvent) -> None: ...


@dataclass
class AnswerResult:
    events: list[AgentEvent] = field(default_factory=list)
    stop_reasons: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    routing: list[dict[str, Any]] = field(default_factory=list)
    cards: list[dict[str, Any]] = field(default_factory=list)  # full engine card JSON per draft_ref


class DataPort(Protocol):
    """Read-only data the chains need. The shop is bound by the implementation, never by a model."""

    async def shop_daily(self, end: date, item: str | None = None) -> list[dict[str, Any]]: ...
    async def source_daily(
        self, a: date, b: date, item: str | None = None
    ) -> list[dict[str, Any]]: ...
    async def product_daily(self, a: date, b: date) -> list[dict[str, Any]]: ...
    async def item_names(self, ids: list[str]) -> dict[str, str]: ...
    async def catalog_search(self, phrase: str) -> list[dict[str, Any]]: ...
    async def stock_events(self, a: date, b: date) -> list[dict[str, Any]]: ...
    async def open_cards(self) -> list[dict[str, Any]]: ...
    async def overview(self, a: date, b: date) -> dict[str, Any]: ...
    async def metric_view(
        self, metric: str, a: date, b: date, item: str | None
    ) -> dict[str, Any]: ...
    async def cost_lines(self, a: date, b: date, item: str | None = None) -> dict[str, Any]: ...
    async def cost_lines_pair(
        self, a1: date, b1: date, a0: date, b0: date, item: str | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]: ...
    async def critical(self, a: date, b: date) -> dict[str, Any]: ...


class CardEnginePort(Protocol):
    def allowed_kinds(self, metric: str) -> tuple[str, ...]: ...

    def needs_item(self, kind: str) -> bool: ...

    async def engine_card(self, kind: str, item: str | None, as_of: date) -> dict[str, Any]: ...


@dataclass(frozen=True)
class LabelTable:
    """Per-platform Vietnamese labels (sources, metrics, kinds). Unknown source codes -> "Khác"."""

    platform: str
    sources: dict[str, str]
    metrics: dict[str, str]
    kinds: dict[str, str]

    def source(self, code: str) -> str:
        return self.sources.get(code, "Khác")

    def metric(self, code: str) -> str:
        return self.metrics.get(code, code)

    def kind(self, code: str) -> str:
        return self.kinds.get(code, code)
