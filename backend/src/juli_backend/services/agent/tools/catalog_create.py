"""Create a new TikTok listing from the shop's own catalog -- SANDBOX ONLY (P64, D73.3/D73.4).

The ``catalog_create`` tool domain: three tools the ``create_product`` playbook runs, for a
run bound to one of the shop's own products (the source -- the card's subject):

- ``get_category_candidates`` (READ / AUTO) -- the source listing's title, description
  excerpt, price and its own leaf category, plus a compact list of TikTok leaf categories
  (Get Categories, 202309) ranked by word overlap with the source title. The model picks
  ONE ``category_id`` from this list -- never a free value.
- ``check_listing_requirements`` (READ / AUTO) -- for the chosen category: is the id one of
  the candidates (``category_suggestion_invalid`` otherwise), does TikTok's Check Listing
  Prerequisites (202312) pass, and does the source listing carry every REQUIRED product
  attribute of the category (Get Attributes, 202309) -- ``required_attribute_missing``
  otherwise. Juli never guesses an attribute value.
- ``create_product`` (WRITE / CONFIRM) -- after the confirmation: re-checks all of the
  above, then Create Product (``POST /product/202309/products``) with the model's title /
  description, the chosen category, the source's own main image URIs, product attributes,
  package weight, price and warehouse, and a stock of :data:`NEW_LISTING_STOCK`; then reads
  the new product back (``GET /product/202309/products/{id}``) and reports TikTok's own
  status for it.

**Sandbox only (D13, D73.3).** A seller's production write allowlist has no product create
(``integrations/tiktok/capabilities.PRODUCTION_WRITE_ALLOWED_REQUESTS``); only the sandbox
allowlist (``SandboxOnlyWriteGuard``) carries ``POST /product/{v}/products``. On top of that
transport rule, :func:`handle_create_product` refuses any resources that are not
``SandboxWriteResources`` before a request exists, the playbook is the only one listing these
tools, and ``services/agent/approval`` approves a ``create_product`` card only on the
sandbox shop, for a partner reviewer, within the daily cap.

Failures a reviewer can act on are returned, never raised: ``ok: false``, an
``error_code`` and a Vietnamese ``summary_vi`` (the step's line in "Đang thực hiện").
"""

from __future__ import annotations

import html
import logging
import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field

from juli_backend.integrations.tiktok import (
    PRODUCT_CATEGORY_VERSION,
    SandboxWriteResources,
    TikTokAPIError,
)
from juli_backend.services.agent.sanitize import VendorText, cap_text, to_json_safe
from juli_backend.services.agent.tools.domains import ToolDomain
from juli_backend.services.agent.tools.listing_rules import (
    RULE_REFUSAL_SUMMARY_VI,
    ProposalRefusal,
    check_proposal,
    redact_terms,
    source_terms_not_in,
)
from juli_backend.services.agent.tools.listing_text_filter import (
    DESCRIPTION_MAX_CHARS,
    DESCRIPTION_MIN_CHARS,
    ERROR_LISTING_TEXT_REJECTED,
    ListingTextRejected,
    clean_listing_draft,
    normalize_create_product,
    screen_listing_draft,
)
from juli_backend.services.agent.tools.product import ProductToolContext
from juli_backend.services.agent.tools.product_domain import bind_product_context
from juli_backend.services.agent.tools.registry import (
    ToolClassification,
    ToolPolicy,
    ToolRegistry,
    ToolSpec,
)
from juli_backend.services.shop_rules.listing_edits import TITLE_MAX_CHARS, contains_term

logger = logging.getLogger(__name__)

CATALOG_CREATE_DOMAIN = "catalog_create"
GET_CATEGORY_CANDIDATES_TOOL = "get_category_candidates"
CHECK_LISTING_REQUIREMENTS_TOOL = "check_listing_requirements"
CREATE_PRODUCT_TOOL = "create_product"

#: Stock of the new listing (one SKU) -- owner D73.3.
NEW_LISTING_STOCK = 10
#: Candidates offered to the model (keeps the nano context small).
MAX_CANDIDATES = 12
MAX_MAIN_IMAGES = 9

ERROR_CATEGORY_INVALID = "category_suggestion_invalid"
ERROR_REQUIRED_ATTRIBUTE_MISSING = "required_attribute_missing"
ERROR_PREREQUISITES_FAILED = "listing_prerequisites_failed"
ERROR_SOURCE_INCOMPLETE = "source_listing_incomplete"
ERROR_TIKTOK = "tiktok_error"
ERROR_NOT_SANDBOX = "sandbox_only"

#: TikTok product status -> what the reviewer reads (the read-back, shown honestly).
STATUS_LABELS_VI: Mapping[str, str] = {
    "DRAFT": "Bản nháp",
    "PENDING": "Đang chờ TikTok duyệt",
    "FAILED": "TikTok không duyệt",
    "ACTIVATE": "Đang bán",
    "SELLER_DEACTIVATED": "Người bán đã tắt",
    "PLATFORM_DEACTIVATED": "TikTok đã tắt",
    "FREEZE": "Đang bị khoá",
    "DELETED": "Đã xoá",
}

_SHOP_TZ = timezone(timedelta(hours=7))
_WORD = re.compile(r"[0-9a-zA-ZÀ-ỹ]+")


class CreateProductRefused(PermissionError):
    """The create was asked for outside the sandbox (fail closed, before any request)."""


def _unwrap(payload: Any) -> Mapping[str, Any]:
    if isinstance(payload, Mapping) and isinstance(payload.get("data"), Mapping):
        return payload["data"]
    return payload if isinstance(payload, Mapping) else {}


def _vendor(value: Any, cap: int) -> dict[str, Any]:
    return to_json_safe(VendorText(text=cap_text(str(value or "").strip(), cap=cap).text))


def _plain(value: Any) -> str:
    return re.sub(r"<[^>]+>", " ", str(value or ""))


def _words(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text) if len(w) >= 2}


def _leaf_category(detail: Mapping[str, Any]) -> tuple[str | None, str | None]:
    for chain in detail.get("category_chains") or []:
        if isinstance(chain, Mapping) and chain.get("is_leaf"):
            return str(chain.get("id") or "") or None, str(chain.get("local_name") or "") or None
    return None, None


def _first_sku(detail: Mapping[str, Any]) -> Mapping[str, Any]:
    skus = detail.get("skus") or []
    return skus[0] if skus and isinstance(skus[0], Mapping) else {}


def _sku_price(sku: Mapping[str, Any]) -> tuple[str | None, str | None]:
    raw = sku.get("price")
    price: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    amount = price.get("sale_price") or price.get("amount") or price.get("tax_exclusive_price")
    currency = price.get("currency")
    amount_text = str(amount) if amount not in (None, "") else None
    return amount_text, (str(currency) if currency else None)


def _warehouse(sku: Mapping[str, Any]) -> str | None:
    for entry in sku.get("inventory") or []:
        if isinstance(entry, Mapping) and entry.get("warehouse_id"):
            return str(entry["warehouse_id"])
    return None


def _available(category: Mapping[str, Any]) -> bool:
    statuses = category.get("permission_statuses")
    return not statuses or "AVAILABLE" in statuses


def rank_candidates(
    categories: Sequence[Mapping[str, Any]],
    *,
    source_title: str,
    source_category_id: str | None,
    limit: int = MAX_CANDIDATES,
) -> list[dict[str, str]]:
    """Leaf, available categories ranked by word overlap with the source title.

    The source listing's own leaf category always comes first (when TikTok lists it).
    Deterministic: ties keep TikTok's order.
    """
    title_words = _words(source_title)
    leaves = [
        c
        for c in categories
        if isinstance(c, Mapping) and c.get("is_leaf") and c.get("id") and _available(c)
    ]
    scored: list[tuple[int, int, dict[str, str]]] = []
    for index, category in enumerate(leaves):
        category_id = str(category["id"])
        name = str(category.get("local_name") or category.get("name") or "").strip()
        score = len(title_words & _words(name))
        if category_id == source_category_id:
            score = 10_000
        scored.append((-score, index, {"category_id": category_id, "name": name}))
    scored.sort(key=lambda row: (row[0], row[1]))
    return [row[2] for row in scored[:limit]]


def _candidates(
    resources: Any, detail: Mapping[str, Any]
) -> tuple[list[dict[str, str]], str | None]:
    source_category_id, _ = _leaf_category(detail)
    categories = _unwrap(resources.products.get_categories()).get("categories") or []
    ranked = rank_candidates(
        categories,
        source_title=str(detail.get("title") or ""),
        source_category_id=source_category_id,
    )
    return ranked, source_category_id


# -- get_category_candidates ------------------------------------------------------------


class GetCategoryCandidatesInput(BaseModel):
    """No fields: the source product is the run's own."""


class CategoryCandidate(BaseModel):
    category_id: str
    name: dict[str, Any]


class GetCategoryCandidatesOutput(BaseModel):
    ok: bool = True
    error_code: str | None = None
    source_title: dict[str, Any] | None = None
    source_description: dict[str, Any] | None = None
    source_category_id: str | None = None
    price: str | None = None
    currency: str | None = None
    new_listing_stock: int = NEW_LISTING_STOCK
    candidates: list[CategoryCandidate] = Field(default_factory=list)
    summary_vi: str = ""


def handle_get_category_candidates(
    resources: Any, context: ProductToolContext, params: GetCategoryCandidatesInput
) -> GetCategoryCandidatesOutput:
    del params
    try:
        detail = resources.products.get_details(context.product_id)
        ranked, source_category_id = _candidates(resources, detail)
    except TikTokAPIError as exc:
        logger.warning("catalog_create_candidates_failed", extra={"tiktok_code": exc.code})
        return GetCategoryCandidatesOutput(
            ok=False,
            error_code=ERROR_TIKTOK,
            summary_vi="TikTok chưa trả danh mục sản phẩm, vui lòng thử lại sau",
        )
    price, currency = _sku_price(_first_sku(detail))
    # Never show the model a brand / manufacturer name the source title does not carry.
    title = str(detail.get("title") or "")
    description = redact_terms(
        _plain(detail.get("description")), source_terms_not_in(detail, title)
    )
    return GetCategoryCandidatesOutput(
        source_title=_vendor(detail.get("title"), 255),
        source_description=_vendor(description, 600),
        source_category_id=source_category_id,
        price=price,
        currency=currency,
        candidates=[
            CategoryCandidate(category_id=row["category_id"], name=_vendor(row["name"], 120))
            for row in ranked
        ],
        summary_vi=f"Đã lấy {len(ranked)} danh mục phù hợp từ TikTok",
    )


GET_CATEGORY_CANDIDATES_SPEC = ToolSpec(
    name=GET_CATEGORY_CANDIDATES_TOOL,
    description=(
        "Read the bound source product (title, description excerpt, price, its own leaf "
        "category) and a short list of TikTok leaf categories that fit it. Pick the new "
        "listing's category_id ONLY from candidates[].category_id."
    ),
    seller_rationale_vi="Đọc sản phẩm gốc và danh mục TikTok phù hợp.",
    input_model=GetCategoryCandidatesInput,
    output_model=GetCategoryCandidatesOutput,
    classification=ToolClassification.READ,
    policy=ToolPolicy.AUTO,
    timeout_seconds=30,
    domain=CATALOG_CREATE_DOMAIN,
)


# -- check_listing_requirements ---------------------------------------------------------


class ListingPlan(BaseModel):
    """Everything Create Product needs, derived from the source listing (server-side)."""

    category_id: str
    category_name: str
    main_images: list[dict[str, str]]
    product_attributes: list[dict[str, Any]]
    package_weight: dict[str, Any]
    package_dimensions: dict[str, Any] | None = None
    price: str
    currency: str
    warehouse_id: str
    #: The source's free-text values its title does not carry (``source_terms_not_in``).
    source_terms: list[str] = Field(default_factory=list)


class PlanRefusal(Exception):
    def __init__(self, code: str, summary_vi: str, missing: list[str] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.summary_vi = summary_vi
        self.missing = missing or []


def _required(attribute: Mapping[str, Any]) -> bool:
    # TikTok spells it ``is_requried`` (contract-collection.md §A-9); accept both.
    return bool(attribute.get("is_requried") or attribute.get("is_required"))


def copyable_attributes(
    detail: Mapping[str, Any],
    attribute_names: Mapping[str, str],
    required_ids: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """The source's attribute values the new listing carries, for the category's attributes.

    Only attributes the category knows (``attribute_names``), values copied verbatim
    (``id`` / ``name``) -- never invented:

    - an attribute the category REQUIRES (``required_ids``: TikTok VN's Manufacturer /
      Trader Name and Address, Country of origin ...) is a seller / legal fact, copied
      as it is -- its free-text values stay in the source-names rule data, so the
      drafted copy still cannot use them (``listing_rules``), and the model never
      reads them;
    - an optional attribute keeps a value TikTok picked from its own option list (it has
      an ``id``), and a free-text value only when the source TITLE carries it (D73.5).

    An attribute left with no value is dropped; if the category requires it, the plan
    says ``required_attribute_missing``.
    """
    title = str(detail.get("title") or "")
    copied: list[dict[str, Any]] = []
    for attribute in detail.get("product_attributes") or []:
        if not isinstance(attribute, Mapping) or not attribute.get("id"):
            continue
        attribute_id = str(attribute["id"])
        if attribute_id not in attribute_names:
            continue
        required = attribute_id in required_ids
        values: list[dict[str, Any]] = []
        for value in attribute.get("values") or []:
            if not isinstance(value, Mapping):
                continue
            text = str(value.get("name") or "").strip()
            if not required and not value.get("id") and not (text and contains_term(title, text)):
                continue
            kept = {k: v for k, v in value.items() if k in ("id", "name") and v}
            if kept:
                values.append(kept)
        if values:
            copied.append({"id": attribute_id, "values": values})
    return copied


def plan_listing(resources: Any, product_id: str, category_id: str) -> ListingPlan:
    """The create plan for ``category_id``, or :class:`PlanRefusal` (no write made)."""
    detail = resources.products.get_details(product_id)
    ranked, _ = _candidates(resources, detail)
    names = {row["category_id"]: row["name"] for row in ranked}
    if category_id not in names:
        raise PlanRefusal(
            ERROR_CATEGORY_INVALID,
            "Danh mục Juli gợi ý không nằm trong danh sách TikTok trả về",
        )
    prerequisites = _unwrap(resources.products.check_listing_prerequisites(category_id=category_id))
    failed = [
        str(row.get("check_item") or "")
        for row in prerequisites.get("check_results") or []
        if isinstance(row, Mapping) and row.get("is_failed")
    ]
    if failed:
        raise PlanRefusal(
            ERROR_PREREQUISITES_FAILED,
            "TikTok chưa cho đăng sản phẩm ở danh mục này: " + ", ".join(failed),
            failed,
        )
    attributes = _unwrap(resources.products.get_category_attributes(category_id=category_id))
    category_attrs = [a for a in attributes.get("attributes") or [] if isinstance(a, Mapping)]
    attribute_names = {str(a.get("id")): str(a.get("name") or "") for a in category_attrs}
    required_ids = frozenset(str(a.get("id")) for a in category_attrs if _required(a))
    product_attributes = copyable_attributes(detail, attribute_names, required_ids)
    copied_ids = {row["id"] for row in product_attributes}
    missing = [
        str(a.get("name") or a.get("id"))
        for a in category_attrs
        if _required(a)
        and str(a.get("type") or "PRODUCT_PROPERTY") == "PRODUCT_PROPERTY"
        and str(a.get("id")) not in copied_ids
    ]
    if missing:
        raise PlanRefusal(
            ERROR_REQUIRED_ATTRIBUTE_MISSING,
            "Sản phẩm gốc thiếu thuộc tính bắt buộc của danh mục: " + ", ".join(missing),
            missing,
        )
    images = [
        {"uri": str(image["uri"])}
        for image in detail.get("main_images") or []
        if isinstance(image, Mapping) and image.get("uri")
    ][:MAX_MAIN_IMAGES]
    sku = _first_sku(detail)
    price, currency = _sku_price(sku)
    warehouse_id = _warehouse(sku)
    weight = detail.get("package_weight")
    gaps = [
        label
        for label, value in (
            ("ảnh chính", images),
            ("giá", price),
            ("kho hàng", warehouse_id),
            ("cân nặng gói hàng", weight if isinstance(weight, Mapping) else None),
        )
        if not value
    ]
    if gaps:
        raise PlanRefusal(ERROR_SOURCE_INCOMPLETE, "Sản phẩm gốc thiếu: " + ", ".join(gaps), gaps)
    assert price is not None and warehouse_id is not None and isinstance(weight, Mapping)
    dimensions = detail.get("package_dimensions")
    return ListingPlan(
        category_id=category_id,
        category_name=names[category_id],
        main_images=images,
        product_attributes=product_attributes,
        package_weight=dict(weight),
        package_dimensions=dict(dimensions) if isinstance(dimensions, Mapping) else None,
        price=price,
        currency=currency or "VND",
        warehouse_id=warehouse_id,
        source_terms=source_terms_not_in(detail, str(detail.get("title") or "")),
    )


class CheckListingRequirementsInput(BaseModel):
    """The category Juli chose from get_category_candidates."""

    category_id: str = Field(min_length=1, max_length=32)


class CheckListingRequirementsOutput(BaseModel):
    ok: bool
    error_code: str | None = None
    category_name: dict[str, Any] | None = None
    missing: list[str] = Field(default_factory=list)
    attributes_copied: int = 0
    price: str | None = None
    currency: str | None = None
    new_listing_stock: int = NEW_LISTING_STOCK
    summary_vi: str = ""


def handle_check_listing_requirements(
    resources: Any, context: ProductToolContext, params: CheckListingRequirementsInput
) -> CheckListingRequirementsOutput:
    try:
        plan = plan_listing(resources, context.product_id, params.category_id)
    except PlanRefusal as refusal:
        return CheckListingRequirementsOutput(
            ok=False,
            error_code=refusal.code,
            missing=refusal.missing,
            summary_vi=refusal.summary_vi,
        )
    except TikTokAPIError as exc:
        logger.warning("catalog_create_requirements_failed", extra={"tiktok_code": exc.code})
        return CheckListingRequirementsOutput(
            ok=False,
            error_code=ERROR_TIKTOK,
            summary_vi="TikTok chưa trả điều kiện đăng bán, vui lòng thử lại sau",
        )
    return CheckListingRequirementsOutput(
        ok=True,
        category_name=_vendor(plan.category_name, 120),
        attributes_copied=len(plan.product_attributes),
        price=plan.price,
        currency=plan.currency,
        summary_vi=(
            f"Danh mục {plan.category_name}: đủ điều kiện đăng bán, "
            f"{len(plan.product_attributes)} thuộc tính lấy từ sản phẩm gốc"
        ),
    )


CHECK_LISTING_REQUIREMENTS_SPEC = ToolSpec(
    name=CHECK_LISTING_REQUIREMENTS_TOOL,
    description=(
        "Check the chosen category_id: it must be one of get_category_candidates' ids, "
        "TikTok's listing prerequisites must pass and the source listing must carry every "
        "required attribute. ok=false with error_code=category_suggestion_invalid means: "
        "choose again from the candidates (once)."
    ),
    seller_rationale_vi="Kiểm tra điều kiện đăng bán của danh mục đã chọn.",
    input_model=CheckListingRequirementsInput,
    output_model=CheckListingRequirementsOutput,
    classification=ToolClassification.READ,
    policy=ToolPolicy.AUTO,
    timeout_seconds=30,
    domain=CATALOG_CREATE_DOMAIN,
)


# -- create_product ---------------------------------------------------------------------


class CreateProductInput(BaseModel):
    """The new listing Juli drafted. Price, stock, images and attributes are server-side."""

    category_id: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=10, max_length=TITLE_MAX_CHARS)
    description: str = Field(min_length=DESCRIPTION_MIN_CHARS, max_length=DESCRIPTION_MAX_CHARS)
    #: One Vietnamese sentence: why this category (shown with the proposal).
    reason_vi: str = Field(min_length=1, max_length=300)


class CreateProductOutput(BaseModel):
    ok: bool
    error_code: str | None = None
    tiktok_product_id: str | None = None
    status: str | None = None
    status_label_vi: str | None = None
    audit_status: str | None = None
    title: dict[str, Any] | None = None
    category_name: dict[str, Any] | None = None
    price: str | None = None
    currency: str | None = None
    stock: int = NEW_LISTING_STOCK
    confirmed_at: str | None = None
    missing: list[str] = Field(default_factory=list)
    summary_vi: str = ""


def description_html(text: str) -> str:
    """Plain paragraphs -> TikTok's HTML description (escaped; no model-supplied markup)."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    return "".join(f"<p>{html.escape(p)}</p>" for p in paragraphs)


def create_body(plan: ListingPlan, *, title: str, description: str) -> dict[str, Any]:
    sku_ref = f"JULI-{uuid.uuid4().hex[:8].upper()}"
    price = {"amount": plan.price, "currency": plan.currency}
    body: dict[str, Any] = {
        "category_id": plan.category_id,
        # The id came from the V2 tree (get_categories); TikTok refuses a create
        # without the matching version (12052217, run 74aefd1a).
        "category_version": PRODUCT_CATEGORY_VERSION,
        "title": title.strip(),
        "description": description_html(description),
        "main_images": plan.main_images,
        "skus": [
            {
                "seller_sku": sku_ref,
                "price": price,
                "list_price": price,
                "inventory": [{"warehouse_id": plan.warehouse_id, "quantity": NEW_LISTING_STOCK}],
            }
        ],
        "package_weight": plan.package_weight,
    }
    if plan.product_attributes:
        body["product_attributes"] = plan.product_attributes
    if plan.package_dimensions:
        body["package_dimensions"] = plan.package_dimensions
    return body


def _vn_time(moment: datetime) -> str:
    local = moment.astimezone(_SHOP_TZ)
    return local.strftime("%H:%M %d/%m/%Y")


def handle_create_product(
    resources: Any, context: ProductToolContext, params: CreateProductInput
) -> CreateProductOutput:
    """Create the listing on the SANDBOX shop, then read it back. See module docstring."""
    if not isinstance(resources, SandboxWriteResources):
        # Fail closed before any request: product create is never a production write (D13).
        raise CreateProductRefused(
            "create_product runs only on the sandbox write resources (D13, D73.3)"
        )
    try:
        plan = plan_listing(resources, context.product_id, params.category_id)
    except PlanRefusal as refusal:
        return CreateProductOutput(
            ok=False,
            error_code=refusal.code,
            missing=refusal.missing,
            summary_vi="Chưa tạo sản phẩm: " + refusal.summary_vi,
        )
    violation = check_proposal(
        {"title": params.title, "description": params.description},
        banned_terms=context.banned_terms,
        source_terms=plan.source_terms,
    )
    if violation is not None:
        # Defence in depth: the runner's pre-confirmation check refuses this first; the
        # seller's own edit is held to the same rules. Nothing is sent to TikTok.
        logger.warning("catalog_create_rule_refused", extra={"error_code": violation.error_code})
        return CreateProductOutput(
            ok=False,
            error_code=violation.error_code,
            summary_vi="Chưa tạo sản phẩm: tiêu đề hoặc mô tả chưa đúng quy tắc của shop",
        )
    try:
        cleaned = clean_listing_draft(
            params.title, params.description, description_floor=DESCRIPTION_MIN_CHARS
        )
    except ListingTextRejected:
        # The filter (P69) would have sent the model back before the pause; a seller edit
        # that is empty or only filler is refused the same way. Nothing is sent to TikTok.
        return CreateProductOutput(
            ok=False,
            error_code=ERROR_LISTING_TEXT_REJECTED,
            summary_vi="Chưa tạo sản phẩm: tiêu đề hoặc mô tả quá ngắn hoặc chung chung",
        )
    params = params.model_copy(update={"title": cleaned.title, "description": cleaned.description})
    try:
        created = _unwrap(
            resources.products.create(
                body=create_body(plan, title=params.title, description=params.description)
            )
        )
    except TikTokAPIError as exc:
        # TikTok's own message is the only way to see which field it refused; it goes in
        # the log line itself (the journal drops ``extra``) and in the run summary.
        reason = " ".join(str(exc.message or "").split())[:300]
        logger.warning(
            "catalog_create_create_failed code=%s request_id=%s message=%s",
            exc.code,
            exc.request_id,
            reason,
            extra={"tiktok_code": exc.code},
        )
        detail = f": {reason}" if reason else ""
        return CreateProductOutput(
            ok=False,
            error_code=ERROR_TIKTOK,
            summary_vi=f"TikTok từ chối tạo sản phẩm (mã lỗi {exc.code}){detail}",
        )
    product_id = str(created.get("product_id") or "")
    if not product_id:
        return CreateProductOutput(
            ok=False,
            error_code=ERROR_TIKTOK,
            summary_vi="TikTok không trả mã sản phẩm mới",
        )
    confirmed_at = datetime.now(UTC)
    status: str | None = None
    audit_status: str | None = None
    title: str = params.title
    try:
        after = resources.products.get_details(product_id)
        status = str(after.get("status") or "") or None
        audit = after.get("audit")
        audit_status = str(audit.get("status")) if isinstance(audit, Mapping) else None
        title = str(after.get("title") or params.title)
    except TikTokAPIError as exc:
        logger.warning("catalog_create_read_back_failed", extra={"tiktok_code": exc.code})
    label = STATUS_LABELS_VI.get(status or "", status or "chưa đọc lại được")
    logger.info(
        "catalog_create_product_created",
        extra={"tiktok_product_id": product_id, "status": status},
    )
    return CreateProductOutput(
        ok=True,
        tiktok_product_id=product_id,
        status=status,
        status_label_vi=label,
        audit_status=audit_status,
        title=_vendor(title, 255),
        category_name=_vendor(plan.category_name, 120),
        price=plan.price,
        currency=plan.currency,
        confirmed_at=confirmed_at.isoformat().replace("+00:00", "Z"),
        summary_vi=(
            f"Đã tạo sản phẩm trên TikTok · mã {product_id} · {label} · "
            f"TikTok xác nhận lúc {_vn_time(confirmed_at)}"
        ),
    )


def precheck_create_product(
    resources: Any, context: ProductToolContext, params: CreateProductInput
) -> ProposalRefusal | None:
    """Before the reviewer is asked: the draft keeps the shop's listing rules (D73.5)
    and is specific, plain copy (P69 filter: no Juli / rule talk, filler or repeats)."""
    try:
        detail = resources.products.get_details(context.product_id)
    except TikTokAPIError as exc:
        # The create re-checks after the confirmation; do not block the proposal here.
        logger.warning("catalog_create_precheck_failed", extra={"tiktok_code": exc.code})
        return _screen_text(params)
    return check_proposal(
        {"title": params.title, "description": params.description},
        banned_terms=context.banned_terms,
        source_terms=source_terms_not_in(detail, str(detail.get("title") or "")),
    ) or _screen_text(params)


def _screen_text(params: CreateProductInput) -> ProposalRefusal | None:
    problem = screen_listing_draft(params.title, params.description)
    if problem is None:
        return None
    return ProposalRefusal(
        error_code=ERROR_LISTING_TEXT_REJECTED,
        summary_vi=RULE_REFUSAL_SUMMARY_VI,
        model_hint=problem,
    )


CREATE_PRODUCT_SPEC = ToolSpec(
    name=CREATE_PRODUCT_TOOL,
    description=(
        "Create the new listing on TikTok with your Vietnamese title and description in the "
        "checked category_id. Price, stock, images and attributes come from the source "
        "listing server-side. Needs the reviewer's explicit approval first."
    ),
    seller_rationale_vi="Tạo sản phẩm mới trên TikTok với tiêu đề, mô tả và danh mục Juli đề xuất.",
    input_model=CreateProductInput,
    output_model=CreateProductOutput,
    classification=ToolClassification.WRITE,
    policy=ToolPolicy.CONFIRM,
    timeout_seconds=60,
    domain=CATALOG_CREATE_DOMAIN,
)


CATALOG_CREATE_TOOL_HANDLERS: dict[str, Any] = {
    GET_CATEGORY_CANDIDATES_TOOL: handle_get_category_candidates,
    CHECK_LISTING_REQUIREMENTS_TOOL: handle_check_listing_requirements,
    CREATE_PRODUCT_TOOL: handle_create_product,
}

CATALOG_CREATE_TOOL_DOMAIN = ToolDomain(
    name=CATALOG_CREATE_DOMAIN,
    handlers=CATALOG_CREATE_TOOL_HANDLERS,
    prechecks={CREATE_PRODUCT_TOOL: precheck_create_product},
    normalizers={CREATE_PRODUCT_TOOL: normalize_create_product},
    subject_types=frozenset({"product"}),
    bind_context=bind_product_context,
)


def register_catalog_create_tools(registry: ToolRegistry) -> None:
    """Register the three ``create_product`` playbook tools (sandbox-only, see module doc)."""
    registry.register(GET_CATEGORY_CANDIDATES_SPEC)
    registry.register(CHECK_LISTING_REQUIREMENTS_SPEC)
    registry.register(CREATE_PRODUCT_SPEC)


__all__ = [
    "CATALOG_CREATE_DOMAIN",
    "CATALOG_CREATE_TOOL_DOMAIN",
    "CHECK_LISTING_REQUIREMENTS_TOOL",
    "CREATE_PRODUCT_TOOL",
    "CreateProductRefused",
    "copyable_attributes",
    "precheck_create_product",
    "ERROR_CATEGORY_INVALID",
    "ERROR_REQUIRED_ATTRIBUTE_MISSING",
    "GET_CATEGORY_CANDIDATES_TOOL",
    "NEW_LISTING_STOCK",
    "STATUS_LABELS_VI",
    "create_body",
    "description_html",
    "handle_check_listing_requirements",
    "handle_create_product",
    "handle_get_category_candidates",
    "plan_listing",
    "rank_candidates",
    "register_catalog_create_tools",
]
