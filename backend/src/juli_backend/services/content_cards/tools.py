"""Read-only TikTok tools of the content run (P14-E, D24.14, D24.19).

Two capabilities in their own ``content`` tool domain, bound to the run's
product exactly like the product tools (``ProductToolContext``):

- ``get_content_performance`` — video: the shop's videos of the last 30 days
  that tag the product (product impressions, clicks, CTR, views, orders, post
  day) and the shop's best videos as examples; LIVE: the sessions of the last
  30 days that sold the product (the product's clicks, SKU orders, CTOR in the
  session, its basket position when TikTok reports one) and the shop's best
  sessions as examples.
- ``find_new_content`` — after the seller films / goes live: a video posted
  since a day that tags the product and already has impressions, or a LIVE
  session since that day that sold the product.

TikTok numbers only (D24.19): titles, counts, rates, days. No raw vendor id
reaches the run's conversation (ADR-070 d.1): rows carry an opaque ``ref``.
Titles are vendor text (``VendorText``), capped.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from juli_backend.integrations.tiktok import TikTokAPIError, TransportGuardError
from juli_backend.services.agent.sanitize import VendorText, cap_text, to_json_safe
from juli_backend.services.agent.tools.domains import ToolDomain
from juli_backend.services.agent.tools.product import ProductToolContext
from juli_backend.services.agent.tools.product_domain import bind_product_context
from juli_backend.services.agent.tools.registry import (
    ToolClassification,
    ToolPolicy,
    ToolRegistry,
    ToolSpec,
)
from juli_backend.services.content_cards import constants as _constants

logger = logging.getLogger(__name__)

CONTENT_DOMAIN = "content"
CONTENT_PERFORMANCE_TOOL = _constants.CONTENT_PERFORMANCE_TOOL
FIND_NEW_CONTENT_TOOL = _constants.FIND_NEW_CONTENT_TOOL

WINDOW_DAYS = 30
#: Per-session product reads per call (each is one TikTok request).
MAX_LIVE_SESSIONS = 10
#: A video / session counts as an example of the shop's best with at least this much.
EXAMPLE_MIN_IMPRESSIONS = 1_000
EXAMPLE_MIN_CLICKS = 50
MAX_EXAMPLES = 3
MAX_ROWS = 10
_SHOP_TZ = timezone(timedelta(hours=7))
_POSITION_KEYS = ("position", "basket_position", "display_position", "sort_order", "order")


def shop_today(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(_SHOP_TZ).date()


def _f(value: Any) -> float:
    if isinstance(value, Mapping):
        value = value.get("amount")
    if isinstance(value, str):
        value = value.strip().rstrip("%")
        try:
            number = float(value)
        except ValueError:
            return 0.0
        return number
    if isinstance(value, bool):
        return 0.0
    return float(value) if isinstance(value, int | float) else 0.0


def _ref(kind: str, raw_id: str) -> str:
    return hashlib.sha256(f"{kind}:{raw_id}".encode()).hexdigest()[:12]


def _title(value: Any) -> dict[str, Any]:
    capped = cap_text(str(value or "").strip(), cap=120)
    return to_json_safe(VendorText(text=capped.text))


def _block(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _unwrap(payload: Any) -> Mapping[str, Any]:
    if isinstance(payload, Mapping) and isinstance(payload.get("data"), Mapping):
        return payload["data"]
    return payload if isinstance(payload, Mapping) else {}


def _rate(num: float, den: float) -> float | None:
    return num / den if den > 0 else None


def _video_day(row: Mapping[str, Any]) -> date | None:
    raw = str(row.get("video_post_time") or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("T", " ").removesuffix("Z")).date()
    except ValueError:
        return None


def _session_day(row: Mapping[str, Any]) -> date | None:
    raw = str(row.get("start_time") or "").strip()
    if not raw.isdigit():
        return None
    return datetime.fromtimestamp(int(raw), tz=UTC).astimezone(_SHOP_TZ).date()


def _tags(row: Mapping[str, Any], product_id: str) -> bool:
    for product in row.get("products") or []:
        if isinstance(product, Mapping) and str(product.get("id") or "") == product_id:
            return True
    return False


def _own(row: Mapping[str, Any]) -> bool:
    creator = row.get("creator")
    kind = creator.get("author_type") if isinstance(creator, Mapping) else None
    return kind is None or "AFFILIATE" not in str(kind).upper()


# -- outputs --------------------------------------------------------------------------


class VideoRow(BaseModel):
    ref: str
    title: dict[str, Any]
    posted_on: str | None = None
    own_account: bool = True
    product_impressions: int = 0
    product_clicks: int = 0
    ctr: float | None = None
    views: int = 0
    sku_orders: int = 0
    hashtags: list[str] = Field(default_factory=list)


class LiveRow(BaseModel):
    ref: str
    title: dict[str, Any]
    started_on: str | None = None
    product_impressions: int = 0
    product_clicks: int = 0
    product_sku_orders: int = 0
    product_ctor: float | None = None
    session_ctor: float | None = None
    basket_position: int | None = None
    products_in_session: int = 0


class GetContentPerformanceInput(BaseModel):
    """Which content the run is about; the product is the run's own."""

    kind: Literal["video", "live"]


class GetContentPerformanceOutput(BaseModel):
    kind: str
    window_days: int = WINDOW_DAYS
    videos: list[VideoRow] = Field(default_factory=list)
    sessions: list[LiveRow] = Field(default_factory=list)
    total_impressions: int = 0
    total_clicks: int = 0
    total_sku_orders: int = 0
    rate: float | None = None
    shop_rate: float | None = None
    examples: list[dict[str, Any]] = Field(default_factory=list)
    unavailable: bool = False
    summary_vi: str = ""


class FindNewContentInput(BaseModel):
    kind: Literal["video", "live"]
    #: The shop-local day (YYYY-MM-DD) from which a new video / session counts.
    since: str


class FoundContent(BaseModel):
    ref: str
    title: dict[str, Any]
    day: str | None = None
    product_impressions: int = 0
    product_clicks: int = 0
    product_sku_orders: int = 0


class FindNewContentOutput(BaseModel):
    kind: str
    since: str
    found: list[FoundContent] = Field(default_factory=list)
    unavailable: bool = False
    summary_vi: str = ""


# -- reads ----------------------------------------------------------------------------


def _window(today: date, days: int) -> tuple[str, str]:
    return (today - timedelta(days=days)).isoformat(), (today + timedelta(days=1)).isoformat()


def list_videos(resources: Any, first: str, end_lt: str) -> list[Mapping[str, Any]]:
    rows = resources.analytics.list_video_performance_all(
        start_date_ge=first, end_date_lt=end_lt, sort_field="gmv"
    )
    return [r for r in rows or [] if isinstance(r, Mapping)]


def list_sessions(resources: Any, first: str, end_lt: str) -> list[Mapping[str, Any]]:
    rows = resources.analytics.list_live_performance_all(start_date_ge=first, end_date_lt=end_lt)
    return [r for r in rows or [] if isinstance(r, Mapping)]


def session_product(
    resources: Any, live_id: str, product_id: str
) -> tuple[Mapping[str, Any] | None, int | None, int]:
    """(the product's row, its basket position if reported, products in the session)."""
    payload = _unwrap(resources.analytics.get_live_products_performance(live_id=live_id))
    products = [p for p in payload.get("products") or [] if isinstance(p, Mapping)]
    for product in products:
        if str(product.get("id") or "") != product_id:
            continue
        position = None
        for key in _POSITION_KEYS:
            value = product.get(key)
            if isinstance(value, int | str) and str(value).isdigit():
                position = int(value)
                break
        return product, position, len(products)
    return None, None, len(products)


def live_product_counts(row: Mapping[str, Any]) -> tuple[int, int, int]:
    """(impressions, clicks, SKU orders) of one product inside one session."""
    traffic = _block(row.get("traffic"))
    sales = _block(row.get("sales"))
    clicks = traffic.get("product_clicks", traffic.get("produt_clicks"))  # TikTok's own typo
    return (
        int(_f(traffic.get("product_impressions"))),
        int(_f(clicks)),
        int(_f(sales.get("sku_orders"))),
    )


def video_row(row: Mapping[str, Any]) -> VideoRow:
    impressions = int(_f(row.get("product_impressions")))
    clicks = int(_f(row.get("product_clicks")))
    day = _video_day(row)
    return VideoRow(
        ref=_ref("video", str(row.get("id") or "")),
        title=_title(row.get("title")),
        posted_on=day.isoformat() if day else None,
        own_account=_own(row),
        product_impressions=impressions,
        product_clicks=clicks,
        ctr=_rate(clicks, impressions),
        views=int(_f(row.get("views"))),
        sku_orders=int(_f(row.get("sku_orders"))),
        hashtags=[str(h) for h in row.get("hash_tags") or [] if isinstance(h, str)][:5],
    )


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}".replace(".", ",") + " %"


def _video_performance(resources: Any, product_id: str, today: date) -> GetContentPerformanceOutput:
    first, end_lt = _window(today, WINDOW_DAYS)
    rows = list_videos(resources, first, end_lt)
    mine = [video_row(r) for r in rows if _tags(r, product_id)]
    mine.sort(key=lambda v: -v.product_impressions)
    impressions = sum(v.product_impressions for v in mine)
    clicks = sum(v.product_clicks for v in mine)
    shop_impr = sum(int(_f(r.get("product_impressions"))) for r in rows)
    shop_clicks = sum(int(_f(r.get("product_clicks"))) for r in rows)
    best = sorted(
        (video_row(r) for r in rows if _f(r.get("product_impressions")) >= EXAMPLE_MIN_IMPRESSIONS),
        key=lambda v: -(v.ctr or 0.0),
    )[:MAX_EXAMPLES]
    rate = _rate(clicks, impressions)
    return GetContentPerformanceOutput(
        kind="video",
        videos=mine[:MAX_ROWS],
        total_impressions=impressions,
        total_clicks=clicks,
        rate=rate,
        shop_rate=_rate(shop_clicks, shop_impr),
        examples=[
            {"title": v.title, "ctr": v.ctr, "hashtags": v.hashtags, "own_account": v.own_account}
            for v in best
        ],
        summary_vi=(
            f"{len(mine)} video gắn sản phẩm · CTR {_pct(rate)}"
            if mine
            else "Chưa có video nào gắn sản phẩm trong 30 ngày"
        ),
    )


def _live_performance(resources: Any, product_id: str, today: date) -> GetContentPerformanceOutput:
    first, end_lt = _window(today, WINDOW_DAYS)
    sessions = sorted(
        list_sessions(resources, first, end_lt),
        key=lambda s: -int(_f(s.get("start_time"))),
    )
    rows: list[LiveRow] = []
    for session in sessions[:MAX_LIVE_SESSIONS]:
        live_id = str(session.get("id") or "")
        if not live_id:
            continue
        product, position, count = session_product(resources, live_id, product_id)
        if product is None:
            continue
        impressions, clicks, orders = live_product_counts(product)
        sales = _block(session.get("sales_performance"))
        traffic = _block(session.get("interaction_performance"))
        day = _session_day(session)
        rows.append(
            LiveRow(
                ref=_ref("live", live_id),
                title=_title(session.get("title") or "LIVE"),
                started_on=day.isoformat() if day else None,
                product_impressions=impressions,
                product_clicks=clicks,
                product_sku_orders=orders,
                product_ctor=_rate(orders, clicks),
                session_ctor=_rate(_f(sales.get("sku_orders")), _f(traffic.get("product_clicks"))),
                basket_position=position,
                products_in_session=count,
            )
        )
    clicks = sum(r.product_clicks for r in rows)
    orders = sum(r.product_sku_orders for r in rows)
    shop_clicks = sum(
        _f((s.get("interaction_performance") or {}).get("product_clicks")) for s in sessions
    )
    shop_orders = sum(_f((s.get("sales_performance") or {}).get("sku_orders")) for s in sessions)
    best = sorted(
        (
            s
            for s in sessions
            if _f((s.get("interaction_performance") or {}).get("product_clicks"))
            >= EXAMPLE_MIN_CLICKS
        ),
        key=lambda s: (
            -(
                _rate(
                    _f((s.get("sales_performance") or {}).get("sku_orders")),
                    _f((s.get("interaction_performance") or {}).get("product_clicks")),
                )
                or 0.0
            )
        ),
    )[:MAX_EXAMPLES]
    rate = _rate(orders, clicks)
    known = [r for r in rows if r.basket_position is not None]
    where = f" · vị trí {known[0].basket_position} trong giỏ" if known else ""
    return GetContentPerformanceOutput(
        kind="live",
        sessions=rows,
        total_impressions=sum(r.product_impressions for r in rows),
        total_clicks=clicks,
        total_sku_orders=orders,
        rate=rate,
        shop_rate=_rate(shop_orders, shop_clicks),
        examples=[
            {
                "title": _title(s.get("title") or "LIVE"),
                "ctor": _rate(
                    _f((s.get("sales_performance") or {}).get("sku_orders")),
                    _f((s.get("interaction_performance") or {}).get("product_clicks")),
                ),
            }
            for s in best
        ],
        summary_vi=(
            f"{len(rows)} phiên LIVE có bán sản phẩm · CTOR {_pct(rate)}{where}"
            if rows
            else "Chưa có phiên LIVE nào bán sản phẩm trong 30 ngày"
        ),
    )


def handle_get_content_performance(
    resources: Any, context: ProductToolContext, params: GetContentPerformanceInput
) -> GetContentPerformanceOutput:
    today = shop_today()
    try:
        if params.kind == "video":
            return _video_performance(resources, context.product_id, today)
        return _live_performance(resources, context.product_id, today)
    except (TikTokAPIError, TransportGuardError) as exc:
        logger.warning(
            "content_performance_unavailable",
            extra={"exception_type": type(exc).__name__, "detail": str(exc)[:300]},
        )
        return GetContentPerformanceOutput(
            kind=params.kind, unavailable=True, summary_vi="Chưa đọc được số liệu từ TikTok"
        )


def find_new_videos(
    resources: Any, product_id: str, since: date, today: date
) -> list[FoundContent]:
    rows = list_videos(resources, since.isoformat(), (today + timedelta(days=1)).isoformat())
    out: list[FoundContent] = []
    for row in rows:
        day = _video_day(row)
        if not _tags(row, product_id) or day is None or day < since:
            continue
        if _f(row.get("product_impressions")) <= 0:
            continue
        out.append(
            FoundContent(
                ref=_ref("video", str(row.get("id") or "")),
                title=_title(row.get("title")),
                day=day.isoformat(),
                product_impressions=int(_f(row.get("product_impressions"))),
                product_clicks=int(_f(row.get("product_clicks"))),
                product_sku_orders=int(_f(row.get("sku_orders"))),
            )
        )
    out.sort(key=lambda f: (f.day or "", f.ref))
    return out


def find_new_sessions(
    resources: Any, product_id: str, since: date, today: date, *, limit: int = 5
) -> list[FoundContent]:
    sessions = list_sessions(resources, since.isoformat(), (today + timedelta(days=1)).isoformat())
    sessions = sorted(
        (s for s in sessions if (_session_day(s) or date.min) >= since),
        key=lambda s: int(_f(s.get("start_time"))),
    )
    out: list[FoundContent] = []
    for session in sessions[:limit]:
        live_id = str(session.get("id") or "")
        if not live_id:
            continue
        product, _position, _count = session_product(resources, live_id, product_id)
        if product is None:
            continue
        impressions, clicks, orders = live_product_counts(product)
        day = _session_day(session)
        out.append(
            FoundContent(
                ref=_ref("live", live_id),
                title=_title(session.get("title") or "LIVE"),
                day=day.isoformat() if day else None,
                product_impressions=impressions,
                product_clicks=clicks,
                product_sku_orders=orders,
            )
        )
    return out


def handle_find_new_content(
    resources: Any, context: ProductToolContext, params: FindNewContentInput
) -> FindNewContentOutput:
    try:
        since = date.fromisoformat(params.since)
    except ValueError:
        since = shop_today()
    today = shop_today()
    try:
        found = (
            find_new_videos(resources, context.product_id, since, today)
            if params.kind == "video"
            else find_new_sessions(resources, context.product_id, since, today)
        )
    except (TikTokAPIError, TransportGuardError) as exc:
        logger.warning(
            "find_new_content_unavailable",
            extra={"exception_type": type(exc).__name__, "detail": str(exc)[:300]},
        )
        return FindNewContentOutput(
            kind=params.kind,
            since=since.isoformat(),
            unavailable=True,
            summary_vi="Chưa đọc được từ TikTok",
        )
    noun = "video mới" if params.kind == "video" else "phiên LIVE mới"
    return FindNewContentOutput(
        kind=params.kind,
        since=since.isoformat(),
        found=found,
        summary_vi=f"Tìm thấy {len(found)} {noun}" if found else f"Chưa thấy {noun} trên TikTok",
    )


GET_CONTENT_PERFORMANCE_SPEC = ToolSpec(
    name=CONTENT_PERFORMANCE_TOOL,
    description=(
        "Read, for the bound product, the last 30 days of the shop's videos that tag it "
        "(kind=video) or the LIVE sessions that sold it (kind=live): impressions, clicks, "
        "CTR / CTOR, basket position when TikTok reports it, plus the shop's best examples."
    ),
    seller_rationale_vi="Đọc số liệu video hoặc LIVE của sản phẩm này.",
    input_model=GetContentPerformanceInput,
    output_model=GetContentPerformanceOutput,
    classification=ToolClassification.READ,
    policy=ToolPolicy.AUTO,
    timeout_seconds=60,
    domain=CONTENT_DOMAIN,
)

FIND_NEW_CONTENT_SPEC = ToolSpec(
    name=FIND_NEW_CONTENT_TOOL,
    description=(
        "Look, read-only, for a video posted since a day that tags the bound product and "
        "has impressions (kind=video), or a LIVE session since that day that sold it (kind=live)."
    ),
    seller_rationale_vi="Tìm video hoặc phiên LIVE mới của sản phẩm này trên TikTok.",
    input_model=FindNewContentInput,
    output_model=FindNewContentOutput,
    classification=ToolClassification.READ,
    policy=ToolPolicy.AUTO,
    timeout_seconds=60,
    domain=CONTENT_DOMAIN,
)

CONTENT_TOOL_HANDLERS: dict[str, Any] = {
    GET_CONTENT_PERFORMANCE_SPEC.name: handle_get_content_performance,
    FIND_NEW_CONTENT_SPEC.name: handle_find_new_content,
}

CONTENT_TOOL_DOMAIN = ToolDomain(
    name=CONTENT_DOMAIN,
    handlers=CONTENT_TOOL_HANDLERS,
    subject_types=frozenset({"product"}),
    bind_context=bind_product_context,
)


def register_content_read_tools(registry: ToolRegistry) -> None:
    """Register the two content READ capabilities."""
    registry.register(GET_CONTENT_PERFORMANCE_SPEC)
    registry.register(FIND_NEW_CONTENT_SPEC)


def content_rows_text(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """Plain titles of tool rows (for prompts and step results)."""
    out: list[str] = []
    for row in rows:
        title = row.get("title")
        text = title.get("text") if isinstance(title, Mapping) else title
        if isinstance(text, str) and text.strip():
            out.append(text.strip())
    return out


__all__ = [
    "CONTENT_DOMAIN",
    "CONTENT_PERFORMANCE_TOOL",
    "CONTENT_TOOL_DOMAIN",
    "CONTENT_TOOL_HANDLERS",
    "FIND_NEW_CONTENT_SPEC",
    "FIND_NEW_CONTENT_TOOL",
    "GET_CONTENT_PERFORMANCE_SPEC",
    "FoundContent",
    "content_rows_text",
    "find_new_sessions",
    "find_new_videos",
    "handle_find_new_content",
    "handle_get_content_performance",
    "list_sessions",
    "list_videos",
    "live_product_counts",
    "register_content_read_tools",
    "session_product",
    "shop_today",
    "video_row",
]
