"""Create a product discount on TikTok -- SANDBOX ONLY (fast track P65, D74).

The ``promotion_create`` tool domain: three tools the ``create_promotion`` playbook runs,
for a run bound to one of the shop's own products (the card's subject):

- ``get_promotion_candidates`` (READ / AUTO) -- the bound product and up to
  :data:`MAX_EXTRA_CANDIDATES` other selling products of the shop (Search Products /
  Get Product 202309) with their stock, the products already in a running or upcoming
  price promotion (Search Activities + Get Activity, Promotion 202309), the discount
  range the shop's rules allow (:func:`discount_bounds`, rules as data) and the dates
  the promotion may run.
- ``check_promotion_eligibility`` (READ / AUTO) -- the model's choice (1-2 products,
  discount %, end date) against the same read: every product a candidate, in stock,
  selling and in no other discount; the % within the range; the end date valid.
- ``create_product_discount`` (WRITE / CONFIRM) -- after the confirmation: re-checks all
  of the above, then the documented chain (``contract-collection.md`` B-5, B-7, A-25):
  Create Activity (``POST /promotion/202309/activities``, ``activity_type
  DIRECT_DISCOUNT``, ``product_level PRODUCT``), Update Activity Product (``PUT
  /promotion/202309/activities/{id}/products``, ``discount`` per product, ``skus: []``),
  then Get Activity (``GET /promotion/202309/activities/{id}``) to report TikTok's own
  status and products.

**Sandbox only (D13, D74).** The production write allowlist
(``integrations/tiktok/capabilities.PRODUCTION_WRITE_ALLOWED_REQUESTS``) has no
promotion write; only ``SandboxOnlyWriteGuard`` signs these requests. On top of that,
:func:`handle_create_product_discount` refuses any resources that are not
``SandboxWriteResources`` before a request exists, only the ``create_promotion``
playbook lists these tools, and ``services/agent/approval`` approves a
``create_promotion`` card only on the sandbox shop, for a partner reviewer, within the
daily cap.

No ROI / forecast: the sandbox has no real buyers, so Juli measures nothing here.

Failures are returned, never raised (``ok: false``, ``error_code``, ``summary_vi``):
a TikTok error is never reported as a promotion that exists.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field

from juli_backend.integrations.tiktok import SandboxWriteResources, TikTokAPIError
from juli_backend.services.agent.sanitize import VendorText, cap_text, to_json_safe
from juli_backend.services.agent.tools.domains import ToolDomain
from juli_backend.services.agent.tools.listing_rules import ProposalRefusal
from juli_backend.services.agent.tools.product import ProductToolContext
from juli_backend.services.agent.tools.product_domain import bind_product_context
from juli_backend.services.agent.tools.registry import (
    ToolClassification,
    ToolPolicy,
    ToolRegistry,
    ToolSpec,
)
from juli_backend.services.shop_rules.listing_edits import contains_term

logger = logging.getLogger(__name__)

PROMOTION_CREATE_DOMAIN = "promotion_create"
GET_PROMOTION_CANDIDATES_TOOL = "get_promotion_candidates"
CHECK_PROMOTION_ELIGIBILITY_TOOL = "check_promotion_eligibility"
CREATE_PRODUCT_DISCOUNT_TOOL = "create_product_discount"

#: The TikTok activity type of a percentage product discount (OAS: "product discount
#: activities with percentage off").
ACTIVITY_TYPE = "DIRECT_DISCOUNT"
#: Activity types that put a price promotion on a product: a product already in one
#: running or upcoming is not offered again.
PRICE_ACTIVITY_TYPES = frozenset({"FIXED_PRICE", "DIRECT_DISCOUNT", "FLASHSALE"})
ACTIVE_ACTIVITY_STATUSES = ("ONGOING", "NOT_START")

#: The discount range when the shop sets no rule (documented default, D74).
DISCOUNT_MIN_PCT = 5
DISCOUNT_DEFAULT_MAX_PCT = 30
#: A shop rule never raises the cap past this.
DISCOUNT_HARD_MAX_PCT = 90
#: The sandbox demo's default run length; a seller's default is 30 days (OP-FR-3).
SANDBOX_DEFAULT_DAYS = 7
SELLER_DEFAULT_DAYS = 30
MAX_DURATION_DAYS = 30
#: TikTok wants ``begin_time`` after "now": the create starts a little later.
BEGIN_DELAY = timedelta(minutes=2)
MAX_EXTRA_CANDIDATES = 3
MAX_ACTIVITIES_READ = 10
#: The model's title; Juli appends `` · HH:MM dd/mm`` (TikTok: unique, at most 50 chars).
TITLE_MAX_CHARS = 36
TIKTOK_TITLE_MAX = 50

ERROR_TIKTOK = "tiktok_error"
ERROR_NOT_SANDBOX = "sandbox_only"
ERROR_DISCOUNT_NOT_ALLOWED = "discount_not_allowed"
ERROR_DISCOUNT_OUT_OF_RANGE = "discount_out_of_range"
ERROR_END_DATE_INVALID = "end_date_invalid"
ERROR_SOURCE_REQUIRED = "source_product_required"
ERROR_PRODUCT_NOT_CANDIDATE = "product_not_candidate"
ERROR_PRODUCT_NOT_ELIGIBLE = "product_not_eligible"
ERROR_TITLE_RULE = "promotion_title_rule_violation"

#: TikTok activity status -> what the reviewer reads.
STATUS_LABELS_VI: Mapping[str, str] = {
    "DRAFT": "Bản nháp",
    "NOT_START": "Chưa bắt đầu",
    "ONGOING": "Đang diễn ra",
    "EXPIRED": "Đã hết hạn",
    "DEACTIVATED": "Đã tắt",
    "NOT_EFFECTIVE": "TikTok đã dừng",
}

SHOP_TZ = timezone(timedelta(hours=7))
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class PromotionCreateRefused(PermissionError):
    """The create was asked for outside the sandbox (fail closed, before any request)."""


def _now() -> datetime:
    """The clock (a seam for tests)."""
    return datetime.now(UTC)


def shop_today(now: datetime | None = None) -> date:
    return (now or _now()).astimezone(SHOP_TZ).date()


def _unwrap(payload: Any) -> Mapping[str, Any]:
    if isinstance(payload, Mapping) and isinstance(payload.get("data"), Mapping):
        return payload["data"]
    return payload if isinstance(payload, Mapping) else {}


def _vendor(value: Any, cap: int) -> dict[str, Any]:
    return to_json_safe(VendorText(text=cap_text(str(value or "").strip(), cap=cap).text))


def _vn_time(moment: datetime) -> str:
    return moment.astimezone(SHOP_TZ).strftime("%H:%M %d/%m/%Y")


def vn_date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


# -- rules as data ------------------------------------------------------------------------


def _pct(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # NaN


def discount_rules_for_run(
    default_max_pct: Any | None, sku_max_pct: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """The ``shop_rules.discount`` block a ``create_promotion`` run's opening context carries.

    ``default_max_pct``: the shop's ``default_max_discount_pct`` (unset: the documented
    default cap); ``sku_max_pct``: its ``max_discount_pct`` rules (TikTok SKU id -> %).
    """
    rule = _pct(default_max_pct)
    if rule is None:
        max_pct, source = DISCOUNT_DEFAULT_MAX_PCT, "default"
    else:
        max_pct, source = int(min(rule, DISCOUNT_HARD_MAX_PCT)), "default_max_discount_pct"
    caps = {
        str(sku): int(pct)
        for sku, raw in (sku_max_pct or {}).items()
        if (pct := _pct(raw)) is not None
    }
    block: dict[str, Any] = {
        "min_pct": DISCOUNT_MIN_PCT,
        "max_pct": max_pct,
        "max_source": source,
        "default_days": SANDBOX_DEFAULT_DAYS,
        "max_days": MAX_DURATION_DAYS,
    }
    if caps:
        block["sku_max_pct"] = caps
    return block


@dataclass(frozen=True)
class DiscountBounds:
    min_pct: int
    max_pct: int
    source: str
    sku_max_pct: Mapping[str, int] = field(default_factory=dict)

    @property
    def rule_vi(self) -> str:
        if self.source == "default_max_discount_pct":
            return f"Quy tắc của shop: giảm tối đa {self.max_pct}%"
        return f"Mặc định của Juli: giảm từ {self.min_pct}% đến {self.max_pct}%"

    def product_max(self, sku_ids: Sequence[str]) -> int:
        caps = [self.sku_max_pct[s] for s in sku_ids if s in self.sku_max_pct]
        return min([self.max_pct, *caps])


def discount_bounds(rules: Mapping[str, Any] | None) -> DiscountBounds:
    """The run's discount range, from its opening ``shop_rules.discount`` (defaults if absent)."""
    rules = rules if isinstance(rules, Mapping) else discount_rules_for_run(None)
    min_pct = _pct(rules.get("min_pct"))
    max_pct = _pct(rules.get("max_pct"))
    caps = rules.get("sku_max_pct")
    return DiscountBounds(
        min_pct=int(min_pct) if min_pct is not None else DISCOUNT_MIN_PCT,
        max_pct=int(max_pct) if max_pct is not None else DISCOUNT_DEFAULT_MAX_PCT,
        source=str(rules.get("max_source") or "default"),
        sku_max_pct=(
            {str(k): int(v) for k, v in caps.items() if _pct(v) is not None}
            if isinstance(caps, Mapping)
            else {}
        ),
    )


def check_discount(pct: int, low: int, high: int) -> str | None:
    """A Vietnamese refusal when ``pct`` is outside ``[low, high]``, else ``None``."""
    if high < low:
        return f"Quy tắc của shop không cho giảm từ {low}% trở lên"
    if not low <= pct <= high:
        return f"Mức giảm phải từ {low}% đến {high}%"
    return None


def parse_end_date(value: str, today: date) -> date | str:
    """The end date, or a Vietnamese refusal: tomorrow .. today + :data:`MAX_DURATION_DAYS`."""
    if not isinstance(value, str) or not _ISO_DATE.match(value.strip()):
        return "Ngày kết thúc cần theo dạng YYYY-MM-DD"
    try:
        end = date.fromisoformat(value.strip())
    except ValueError:
        return "Ngày kết thúc không hợp lệ"
    last = today + timedelta(days=MAX_DURATION_DAYS)
    if not today < end <= last:
        return (
            f"Ngày kết thúc phải sau hôm nay và không quá {MAX_DURATION_DAYS} ngày "
            f"(đến {vn_date(last)})"
        )
    return end


# -- the read -----------------------------------------------------------------------------


def _sku_ids(detail: Mapping[str, Any]) -> list[str]:
    return [
        str(sku["id"])
        for sku in detail.get("skus") or []
        if isinstance(sku, Mapping) and sku.get("id")
    ]


def _stock(detail: Mapping[str, Any]) -> int:
    total = 0
    for sku in detail.get("skus") or []:
        if not isinstance(sku, Mapping):
            continue
        for entry in sku.get("inventory") or []:
            if isinstance(entry, Mapping):
                try:
                    total += int(entry.get("quantity") or 0)
                except (TypeError, ValueError):
                    continue
    return total


def _price(detail: Mapping[str, Any]) -> tuple[str | None, str | None]:
    skus = detail.get("skus") or []
    sku = skus[0] if skus and isinstance(skus[0], Mapping) else {}
    raw = sku.get("price")
    price: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    amount = price.get("sale_price") or price.get("amount") or price.get("tax_exclusive_price")
    currency = price.get("currency")
    return (str(amount) if amount not in (None, "") else None), (
        str(currency) if currency else None
    )


@dataclass
class CandidateRead:
    source_id: str
    details: dict[str, Mapping[str, Any]]
    discounted: set[str]
    activities_read: bool
    active_count: int


def _discounted_products(promotion: Any) -> tuple[set[str], bool, int]:
    """Products in a running or upcoming price promotion; ``(ids, read_ok, count)``."""
    try:
        activities: list[Mapping[str, Any]] = []
        for status in ACTIVE_ACTIVITY_STATUSES:
            activities.extend(
                a
                for a in promotion.search_activities_all(status=status, page_size=50, max_pages=2)
                if isinstance(a, Mapping)
            )
    except TikTokAPIError as exc:
        logger.warning("promotion_create_activities_unread", extra={"tiktok_code": exc.code})
        return set(), False, 0
    priced = [a for a in activities if str(a.get("activity_type") or "") in PRICE_ACTIVITY_TYPES]
    ids: set[str] = set()
    read_ok = True
    for activity in priced[:MAX_ACTIVITIES_READ]:
        activity_id = str(activity.get("id") or activity.get("activity_id") or "")
        if not activity_id:
            continue
        try:
            detail = _unwrap(promotion.get_activity(activity_id))
        except TikTokAPIError as exc:
            logger.warning("promotion_create_activity_unread", extra={"tiktok_code": exc.code})
            read_ok = False
            continue
        ids |= {
            str(p["id"])
            for p in detail.get("products") or []
            if isinstance(p, Mapping) and p.get("id")
        }
    return ids, read_ok, len(priced)


def read_candidates(resources: Any, product_id: str) -> CandidateRead:
    """The bound product, up to :data:`MAX_EXTRA_CANDIDATES` more, and the running discounts.

    Raises ``TikTokAPIError`` only when the bound product itself cannot be read.
    """
    source = resources.products.get_details(product_id)
    details: dict[str, Mapping[str, Any]] = {product_id: source}
    try:
        page = _unwrap(resources.products.search(status="ACTIVATE", page_size=20))
        others = [
            str(p["id"])
            for p in page.get("products") or []
            if isinstance(p, Mapping) and p.get("id") and str(p["id"]) != product_id
        ]
    except TikTokAPIError as exc:
        logger.warning("promotion_create_search_failed", extra={"tiktok_code": exc.code})
        others = []
    for other in others:
        if len(details) > MAX_EXTRA_CANDIDATES:
            break
        try:
            detail = resources.products.get_details(other)
        except TikTokAPIError:
            continue
        if _stock(detail) > 0 and str(detail.get("status") or "") == "ACTIVATE":
            details[other] = detail
    discounted, read_ok, count = _discounted_products(resources.promotion)
    return CandidateRead(product_id, details, discounted, read_ok, count)


def _ineligible_reason(
    detail: Mapping[str, Any], discounted: set[str], product_id: str
) -> str | None:
    status = str(detail.get("status") or "")
    if status and status != "ACTIVATE":
        return "Sản phẩm chưa ở trạng thái đang bán"
    if _stock(detail) <= 0:
        return "Sản phẩm đã hết hàng"
    if product_id in discounted:
        return "Sản phẩm đang có khuyến mãi giá khác"
    return None


# -- get_promotion_candidates -------------------------------------------------------------


class GetPromotionCandidatesInput(BaseModel):
    """No fields: the bound product is the run's own."""


class PromotionCandidate(BaseModel):
    product_id: str
    title: dict[str, Any]
    stock: int
    price: str | None = None
    currency: str | None = None
    max_discount_pct: int
    eligible: bool
    reason_vi: str | None = None


class GetPromotionCandidatesOutput(BaseModel):
    ok: bool = True
    error_code: str | None = None
    source_product_id: str | None = None
    candidates: list[PromotionCandidate] = Field(default_factory=list)
    existing_price_promotions: int = 0
    existing_promotions_read: bool = True
    discount_min_pct: int = DISCOUNT_MIN_PCT
    discount_max_pct: int = DISCOUNT_DEFAULT_MAX_PCT
    discount_rule_vi: str = ""
    today: str | None = None
    default_end_date: str | None = None
    max_end_date: str | None = None
    summary_vi: str = ""


def handle_get_promotion_candidates(
    resources: Any, context: ProductToolContext, params: GetPromotionCandidatesInput
) -> GetPromotionCandidatesOutput:
    del params
    bounds = discount_bounds(context.discount_rules)
    try:
        read = read_candidates(resources, context.product_id)
    except TikTokAPIError as exc:
        logger.warning("promotion_create_candidates_failed", extra={"tiktok_code": exc.code})
        return GetPromotionCandidatesOutput(
            ok=False,
            error_code=ERROR_TIKTOK,
            summary_vi="TikTok chưa trả thông tin sản phẩm, vui lòng thử lại sau",
        )
    candidates: list[PromotionCandidate] = []
    for product_id, detail in read.details.items():
        price, currency = _price(detail)
        reason = _ineligible_reason(detail, read.discounted, product_id)
        candidates.append(
            PromotionCandidate(
                product_id=product_id,
                title=_vendor(detail.get("title"), 255),
                stock=_stock(detail),
                price=price,
                currency=currency,
                max_discount_pct=bounds.product_max(_sku_ids(detail)),
                eligible=reason is None,
                reason_vi=reason,
            )
        )
    today = shop_today()
    eligible = sum(1 for c in candidates if c.eligible)
    existing = (
        f"{read.active_count} khuyến mãi giá đang chạy hoặc sắp chạy"
        if read.activities_read
        else "chưa đọc được khuyến mãi hiện có"
    )
    return GetPromotionCandidatesOutput(
        source_product_id=context.product_id,
        candidates=candidates,
        existing_price_promotions=read.active_count,
        existing_promotions_read=read.activities_read,
        discount_min_pct=bounds.min_pct,
        discount_max_pct=bounds.max_pct,
        discount_rule_vi=bounds.rule_vi,
        today=today.isoformat(),
        default_end_date=(today + timedelta(days=SANDBOX_DEFAULT_DAYS)).isoformat(),
        max_end_date=(today + timedelta(days=MAX_DURATION_DAYS)).isoformat(),
        summary_vi=(
            f"Đã đọc {len(candidates)} sản phẩm ({eligible} còn hàng, đủ điều kiện), {existing}"
        ),
    )


GET_PROMOTION_CANDIDATES_SPEC = ToolSpec(
    name=GET_PROMOTION_CANDIDATES_TOOL,
    description=(
        "Read the bound product and a few other selling products of the shop (stock, price, "
        "whether each is eligible), the running price promotions, the discount range the "
        "shop's rules allow and the allowed end dates. Choose product_ids ONLY from "
        "candidates[].product_id with eligible=true; the bound product (source_product_id) "
        "is always included."
    ),
    seller_rationale_vi="Đọc sản phẩm và khuyến mãi hiện có.",
    input_model=GetPromotionCandidatesInput,
    output_model=GetPromotionCandidatesOutput,
    classification=ToolClassification.READ,
    policy=ToolPolicy.AUTO,
    timeout_seconds=30,
    domain=PROMOTION_CREATE_DOMAIN,
)


# -- the plan (check + create) ------------------------------------------------------------


class PromotionChoice(BaseModel):
    """The model's choice of products, discount and end date."""

    product_ids: list[str] = Field(min_length=1, max_length=2)
    discount_pct: int = Field(ge=1, le=99)
    end_date: str = Field(min_length=10, max_length=10)


@dataclass(frozen=True)
class PromotionPlan:
    products: list[tuple[str, str]]  # (product id, title)
    discount_pct: int
    end_date: date


class PlanRefusal(Exception):
    def __init__(self, code: str, summary_vi: str) -> None:
        super().__init__(code)
        self.code = code
        self.summary_vi = summary_vi


def plan_promotion(
    resources: Any, context: ProductToolContext, choice: PromotionChoice
) -> PromotionPlan:
    """The promotion plan for ``choice``, or :class:`PlanRefusal` (no write made)."""
    bounds = discount_bounds(context.discount_rules)
    if bounds.max_pct < bounds.min_pct:
        raise PlanRefusal(
            ERROR_DISCOUNT_NOT_ALLOWED,
            f"Quy tắc của shop không cho giảm từ {bounds.min_pct}% trở lên",
        )
    product_ids = list(dict.fromkeys(str(p).strip() for p in choice.product_ids))
    if context.product_id not in product_ids:
        raise PlanRefusal(ERROR_SOURCE_REQUIRED, "Khuyến mãi cần gồm sản phẩm của thẻ này")
    end = parse_end_date(choice.end_date, shop_today())
    if isinstance(end, str):
        raise PlanRefusal(ERROR_END_DATE_INVALID, end)
    read = read_candidates(resources, context.product_id)
    products: list[tuple[str, str]] = []
    product_max = bounds.max_pct
    for product_id in product_ids:
        detail = read.details.get(product_id)
        if detail is None:
            raise PlanRefusal(
                ERROR_PRODUCT_NOT_CANDIDATE,
                "Sản phẩm Juli chọn không nằm trong danh sách TikTok trả về",
            )
        reason = _ineligible_reason(detail, read.discounted, product_id)
        title = str(detail.get("title") or product_id)
        if reason is not None:
            raise PlanRefusal(ERROR_PRODUCT_NOT_ELIGIBLE, f"«{title}»: {reason}")
        product_max = min(product_max, bounds.product_max(_sku_ids(detail)))
        products.append((product_id, title))
    refusal = check_discount(choice.discount_pct, bounds.min_pct, product_max)
    if refusal is not None:
        raise PlanRefusal(ERROR_DISCOUNT_OUT_OF_RANGE, refusal)
    return PromotionPlan(products=products, discount_pct=choice.discount_pct, end_date=end)


class CheckPromotionEligibilityInput(PromotionChoice):
    """The choice to check (same fields the create takes)."""


class CheckPromotionEligibilityOutput(BaseModel):
    ok: bool
    error_code: str | None = None
    products: list[dict[str, Any]] = Field(default_factory=list)
    discount_pct: int | None = None
    end_date: str | None = None
    summary_vi: str = ""


def handle_check_promotion_eligibility(
    resources: Any, context: ProductToolContext, params: CheckPromotionEligibilityInput
) -> CheckPromotionEligibilityOutput:
    try:
        plan = plan_promotion(resources, context, params)
    except PlanRefusal as refusal:
        return CheckPromotionEligibilityOutput(
            ok=False, error_code=refusal.code, summary_vi=refusal.summary_vi
        )
    except TikTokAPIError as exc:
        logger.warning("promotion_create_check_failed", extra={"tiktok_code": exc.code})
        return CheckPromotionEligibilityOutput(
            ok=False,
            error_code=ERROR_TIKTOK,
            summary_vi="TikTok chưa trả thông tin sản phẩm, vui lòng thử lại sau",
        )
    return CheckPromotionEligibilityOutput(
        ok=True,
        products=[
            {"product_id": pid, "title": _vendor(title, 255)} for pid, title in plan.products
        ],
        discount_pct=plan.discount_pct,
        end_date=plan.end_date.isoformat(),
        summary_vi=(
            f"{len(plan.products)} sản phẩm đủ điều kiện · giảm {plan.discount_pct}% "
            f"đến {vn_date(plan.end_date)}"
        ),
    )


CHECK_PROMOTION_ELIGIBILITY_SPEC = ToolSpec(
    name=CHECK_PROMOTION_ELIGIBILITY_TOOL,
    description=(
        "Check product_ids (1-2, from get_promotion_candidates, the bound product included), "
        "discount_pct (whole percent within the allowed range) and end_date (YYYY-MM-DD, "
        "after today, at most max_end_date). ok=false means: fix the named value once."
    ),
    seller_rationale_vi="Kiểm tra điều kiện khuyến mãi.",
    input_model=CheckPromotionEligibilityInput,
    output_model=CheckPromotionEligibilityOutput,
    classification=ToolClassification.READ,
    policy=ToolPolicy.AUTO,
    timeout_seconds=30,
    domain=PROMOTION_CREATE_DOMAIN,
)


# -- create_product_discount ----------------------------------------------------------------


class CreateProductDiscountInput(PromotionChoice):
    """The promotion Juli proposes. The reviewer may edit discount_pct and end_date."""

    promotion_title: str = Field(min_length=4, max_length=TITLE_MAX_CHARS)
    #: One Vietnamese sentence: why these products and this discount.
    reason_vi: str = Field(min_length=1, max_length=300)


class CreateProductDiscountOutput(BaseModel):
    ok: bool
    error_code: str | None = None
    activity_id: str | None = None
    status: str | None = None
    status_label_vi: str | None = None
    title: dict[str, Any] | None = None
    discount_pct: int | None = None
    products_confirmed: int = 0
    begin_at: str | None = None
    end_at: str | None = None
    confirmed_at: str | None = None
    summary_vi: str = ""


def activity_title(title: str, begin: datetime) -> str:
    """TikTok wants a title unique across the shop's activities (at most 50 chars)."""
    stamp = begin.astimezone(SHOP_TZ).strftime("%H:%M %d/%m")
    return f"{' '.join(title.split())[:TITLE_MAX_CHARS]} · {stamp}"[:TIKTOK_TITLE_MAX]


def create_activity_body(title: str, begin: datetime, end: datetime) -> dict[str, Any]:
    return {
        "title": title,
        "activity_type": ACTIVITY_TYPE,
        "product_level": "PRODUCT",
        "begin_time": int(begin.timestamp()),
        "end_time": int(end.timestamp()),
        "participation_limit": [{"type": "BUYER_NO_LIMIT"}],
    }


def activity_products_body(activity_id: str, plan: PromotionPlan) -> dict[str, Any]:
    return {
        "activity_id": activity_id,
        "products": [
            {
                "id": product_id,
                "discount": str(plan.discount_pct),
                "quantity_limit": -1,
                "quantity_per_user": -1,
                "skus": [],
            }
            for product_id, _ in plan.products
        ],
    }


def _tiktok_reason(exc: TikTokAPIError) -> str:
    reason = " ".join(str(exc.message or "").split())[:300]
    return f": {reason}" if reason else ""


def _log_refusal(event: str, exc: TikTokAPIError) -> None:
    # TikTok's message goes in the line itself (the journal drops ``extra``), see #2156.
    logger.warning(
        "%s code=%s request_id=%s message=%s",
        event,
        exc.code,
        exc.request_id,
        " ".join(str(exc.message or "").split())[:300],
        extra={"tiktok_code": exc.code},
    )


def _fail(code: str, summary_vi: str, **extra: Any) -> CreateProductDiscountOutput:
    return CreateProductDiscountOutput(ok=False, error_code=code, summary_vi=summary_vi, **extra)


def handle_create_product_discount(
    resources: Any, context: ProductToolContext, params: CreateProductDiscountInput
) -> CreateProductDiscountOutput:
    """Create the discount on the SANDBOX shop, then read it back. See module docstring."""
    if not isinstance(resources, SandboxWriteResources):
        # Fail closed before any request: a promotion is never a production write (D13).
        raise PromotionCreateRefused(
            "create_product_discount runs only on the sandbox write resources (D13, D74)"
        )
    refusal = _title_refusal(params.promotion_title, context.banned_terms)
    if refusal is not None:
        return _fail(refusal.error_code, "Chưa tạo khuyến mãi: " + refusal.summary_vi)
    try:
        plan = plan_promotion(resources, context, params)
    except PlanRefusal as refused:
        return _fail(refused.code, "Chưa tạo khuyến mãi: " + refused.summary_vi)
    except TikTokAPIError as exc:
        _log_refusal("promotion_create_plan_failed", exc)
        return _fail(
            ERROR_TIKTOK,
            f"Chưa tạo khuyến mãi: TikTok chưa trả thông tin sản phẩm (mã lỗi {exc.code})"
            f"{_tiktok_reason(exc)}",
        )
    begin = _now() + BEGIN_DELAY
    end = datetime.combine(plan.end_date, time(23, 59, 59), tzinfo=SHOP_TZ)
    title = activity_title(params.promotion_title, begin)
    try:
        created = _unwrap(
            resources.promotion.create_activity(body=create_activity_body(title, begin, end))
        )
    except TikTokAPIError as exc:
        _log_refusal("promotion_create_create_failed", exc)
        return _fail(
            ERROR_TIKTOK, f"TikTok từ chối tạo khuyến mãi (mã lỗi {exc.code}){_tiktok_reason(exc)}"
        )
    activity_id = str(created.get("activity_id") or "")
    if not activity_id:
        return _fail(ERROR_TIKTOK, "TikTok không trả mã khuyến mãi mới")
    try:
        resources.promotion.update_activity_products(
            activity_id=activity_id, body=activity_products_body(activity_id, plan)
        )
    except TikTokAPIError as exc:
        _log_refusal("promotion_create_products_failed", exc)
        return _fail(
            ERROR_TIKTOK,
            f"TikTok từ chối thêm sản phẩm vào khuyến mãi (mã lỗi {exc.code})"
            f"{_tiktok_reason(exc)}. {_deactivate_empty(resources, activity_id)}",
            activity_id=activity_id,
        )
    confirmed_at = _now()
    status: str | None = str(created.get("status") or "") or None
    confirmed = 0
    try:
        after = _unwrap(resources.promotion.get_activity(activity_id))
        status = str(after.get("status") or "") or status
        ids = {str(p.get("id")) for p in after.get("products") or [] if isinstance(p, Mapping)}
        confirmed = sum(1 for product_id, _ in plan.products if product_id in ids)
        title = str(after.get("title") or title)
    except TikTokAPIError as exc:
        _log_refusal("promotion_create_read_back_failed", exc)
    label = STATUS_LABELS_VI.get(status or "", status or "chưa đọc lại được")
    logger.info(
        "promotion_create_activity_created",
        extra={"activity_id": activity_id, "status": status, "products": confirmed},
    )
    return CreateProductDiscountOutput(
        ok=True,
        activity_id=activity_id,
        status=status,
        status_label_vi=label,
        title=_vendor(title, TIKTOK_TITLE_MAX),
        discount_pct=plan.discount_pct,
        products_confirmed=confirmed,
        begin_at=begin.isoformat().replace("+00:00", "Z"),
        end_at=end.isoformat(),
        confirmed_at=confirmed_at.isoformat().replace("+00:00", "Z"),
        summary_vi=(
            f"Đã tạo khuyến mãi trên TikTok · mã {activity_id} · {label} · "
            f"giảm {plan.discount_pct}% cho {confirmed}/{len(plan.products)} sản phẩm "
            f"đến {vn_date(plan.end_date)} · TikTok xác nhận lúc {_vn_time(confirmed_at)}"
        ),
    )


def _deactivate_empty(resources: SandboxWriteResources, activity_id: str) -> str:
    """Best effort: an activity left with no product is turned off, and the reviewer told."""
    try:
        resources.promotion.deactivate(activity_id=activity_id)
    except TikTokAPIError as exc:
        _log_refusal("promotion_create_deactivate_failed", exc)
        return f"Khuyến mãi rỗng mã {activity_id} vẫn còn trên TikTok"
    return f"Juli đã tắt khuyến mãi rỗng mã {activity_id}"


def _title_refusal(title: str, banned_terms: Sequence[str]) -> ProposalRefusal | None:
    for term in banned_terms:
        if contains_term(title, term):
            return ProposalRefusal(
                error_code=ERROR_TITLE_RULE,
                summary_vi="tên khuyến mãi có từ shop không cho dùng",
                model_hint=(
                    f'promotion_title contains "{term.strip()}", one of the shop\'s banned '
                    "terms (shop_rules.banned_terms). Write it again without it."
                ),
            )
    return None


def precheck_create_product_discount(
    resources: Any, context: ProductToolContext, params: CreateProductDiscountInput
) -> ProposalRefusal | None:
    """Before the reviewer is asked: the title keeps the shop's banned terms; the choice
    keeps the discount range, the dates and the products' eligibility."""
    refusal = _title_refusal(params.promotion_title, context.banned_terms)
    if refusal is not None:
        refusal.summary_vi = "Tên khuyến mãi Juli soạn có từ shop không cho dùng, Juli soạn lại"
        return refusal
    try:
        plan_promotion(resources, context, params)
    except PlanRefusal as refused:
        return ProposalRefusal(
            error_code=refused.code,
            summary_vi="Đề xuất khuyến mãi chưa đúng điều kiện, Juli chọn lại",
            model_hint=f"{refused.code}: {refused.summary_vi}. Choose again within the limits.",
        )
    except TikTokAPIError as exc:
        # The create re-checks after the confirmation; do not block the proposal here.
        logger.warning("promotion_create_precheck_failed", extra={"tiktok_code": exc.code})
    return None


CREATE_PRODUCT_DISCOUNT_SPEC = ToolSpec(
    name=CREATE_PRODUCT_DISCOUNT_TOOL,
    description=(
        "Create the product discount on TikTok (percentage off, starts in a few minutes, ends "
        "on end_date) for the checked product_ids with your short Vietnamese promotion_title "
        "and reason_vi. Needs the reviewer's explicit approval first."
    ),
    seller_rationale_vi="Tạo khuyến mãi giảm giá trên TikTok cho sản phẩm Juli đề xuất.",
    input_model=CreateProductDiscountInput,
    output_model=CreateProductDiscountOutput,
    classification=ToolClassification.WRITE,
    policy=ToolPolicy.CONFIRM,
    timeout_seconds=60,
    domain=PROMOTION_CREATE_DOMAIN,
)


PROMOTION_CREATE_TOOL_HANDLERS: dict[str, Any] = {
    GET_PROMOTION_CANDIDATES_TOOL: handle_get_promotion_candidates,
    CHECK_PROMOTION_ELIGIBILITY_TOOL: handle_check_promotion_eligibility,
    CREATE_PRODUCT_DISCOUNT_TOOL: handle_create_product_discount,
}

PROMOTION_CREATE_TOOL_DOMAIN = ToolDomain(
    name=PROMOTION_CREATE_DOMAIN,
    handlers=PROMOTION_CREATE_TOOL_HANDLERS,
    prechecks={CREATE_PRODUCT_DISCOUNT_TOOL: precheck_create_product_discount},
    subject_types=frozenset({"product"}),
    bind_context=bind_product_context,
)


def register_promotion_create_tools(registry: ToolRegistry) -> None:
    """Register the three ``create_promotion`` playbook tools (sandbox-only, see module doc)."""
    registry.register(GET_PROMOTION_CANDIDATES_SPEC)
    registry.register(CHECK_PROMOTION_ELIGIBILITY_SPEC)
    registry.register(CREATE_PRODUCT_DISCOUNT_SPEC)


__all__ = [
    "CHECK_PROMOTION_ELIGIBILITY_TOOL",
    "CREATE_PRODUCT_DISCOUNT_TOOL",
    "GET_PROMOTION_CANDIDATES_TOOL",
    "PROMOTION_CREATE_DOMAIN",
    "PROMOTION_CREATE_TOOL_DOMAIN",
    "PromotionCreateRefused",
    "check_discount",
    "discount_bounds",
    "discount_rules_for_run",
    "handle_check_promotion_eligibility",
    "handle_create_product_discount",
    "handle_get_promotion_candidates",
    "parse_end_date",
    "precheck_create_product_discount",
    "register_promotion_create_tools",
    "shop_today",
]
