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
import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field

from juli_backend.integrations.tiktok import SandboxWriteResources, TikTokAPIError
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
#: The drafted title / description names a brand or manufacturer the source title does not.
ERROR_BRAND_NOT_IN_SOURCE = "brand_not_in_source"

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


# -- brand / manufacturer leakage guard (P64 walkthrough, D73.3) ------------------------
#
# The sandbox source listing carried a real customer's name as the value of TikTok's
# VN "Manufacturer/Trader Name" / "Manufacturer/Trader Address" attributes (101489 /
# 101490) and in its description; the model wrote it into the new title. A new listing
# never names a brand or a manufacturer that the source TITLE does not already name:
# such values are not copied into the create body, are redacted from what the model
# reads, and a drafted title / description that still carries one is refused.

#: TikTok VN's manufacturer / trader attributes (contract-collection.md §A-8).
BRAND_ATTRIBUTE_IDS = frozenset({"101489", "101490"})
_BRAND_NAME_HINTS = (
    "brand",
    "thương hiệu",
    "manufacturer",
    "nhà sản xuất",
    "trader",
    "importer",
    "nhập khẩu",
    "distributor",
    "phân phối",
)
_ADDRESS_HINTS = ("address", "địa chỉ")
_NO_BRAND = frozenset({"", "no brand", "không có thương hiệu", "none", "n/a"})
#: Generic company words: never a brand on their own.
_COMPANY_WORDS = frozenset(
    {
        "công", "ty", "tnhh", "cổ", "phần", "cp", "việt", "nam", "vn", "co", "ltd", "llc",
        "company", "jsc", "group", "tập", "đoàn", "thương", "mại", "dịch", "vụ", "sản",
        "xuất", "hộ", "kinh", "doanh", "cửa", "hàng", "shop", "store", "official",
    }
)  # fmt: skip
#: Letters outside the Vietnamese alphabet: a title word spelled with one that the source
#: title does not have is a foreign proper name -- a brand -- unless it is a common loanword.
_FOREIGN_LETTERS = re.compile(r"[fjwz]", re.IGNORECASE)
_LOANWORDS = frozenset(
    {"size", "freesize", "free", "zip", "wifi", "jean", "jeans", "film", "fan", "fashion",
     "fitness", "gift", "set", "zin", "laptop", "web", "pizza", "jar", "sofa", "fresh"}
)  # fmt: skip


def _norm(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold().strip()


def _attribute_is_brand(attribute_id: str, name: str) -> bool:
    folded = _norm(name)
    return attribute_id in BRAND_ATTRIBUTE_IDS or any(h in folded for h in _BRAND_NAME_HINTS)


def _value_names(attribute: Mapping[str, Any]) -> list[str]:
    return [
        str(value.get("name") or "").strip()
        for value in attribute.get("values") or []
        if isinstance(value, Mapping) and str(value.get("name") or "").strip()
    ]


def _contains(text: str, term: str) -> bool:
    needle = _norm(term)
    if not needle:
        return False
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", _norm(text)) is not None


def source_brand_terms(
    detail: Mapping[str, Any], attribute_names: Mapping[str, str] | None = None
) -> list[str]:
    """Brand / manufacturer names the source carries but its TITLE does not name.

    From the listing's ``brand`` (unless "No brand") and the values of its brand-like
    attributes (:data:`BRAND_ATTRIBUTE_IDS`, or a name such as "Thương hiệu",
    "Manufacturer/Trader Name"). A multi-word name also contributes its distinctive
    words ("Công ty TNHH Fujiwa" -> "Fujiwa"); an address contributes only itself.
    """
    title = str(detail.get("title") or "")
    title_words = {_norm(w) for w in _WORD.findall(title)}
    names = dict(attribute_names or {})
    candidates: list[tuple[str, bool]] = []
    brand = detail.get("brand")
    if isinstance(brand, Mapping) and _norm(str(brand.get("name") or "")) not in _NO_BRAND:
        candidates.append((str(brand["name"]).strip(), False))
    for attribute in detail.get("product_attributes") or []:
        if not isinstance(attribute, Mapping):
            continue
        attribute_id = str(attribute.get("id") or "")
        name = names.get(attribute_id) or str(attribute.get("name") or "")
        if not _attribute_is_brand(attribute_id, name):
            continue
        is_address = any(h in _norm(name) for h in _ADDRESS_HINTS)
        candidates.extend((value, is_address) for value in _value_names(attribute))
    terms: list[str] = []
    for value, is_address in candidates:
        if _norm(value) in _NO_BRAND or _contains(title, value):
            continue
        if value not in terms:
            terms.append(value)
        if is_address:
            continue
        for word in _WORD.findall(value):
            folded = _norm(word)
            if (
                len(folded) >= 3
                and folded not in _COMPANY_WORDS
                and folded not in title_words
                and not folded.isdigit()
                and word not in terms
            ):
                terms.append(word)
    return terms


def redact_terms(text: str, terms: Sequence[str]) -> str:
    """``text`` without any of ``terms`` (whole word, case-insensitive)."""
    for term in sorted(terms, key=len, reverse=True):
        text = re.sub(
            rf"(?<!\w){re.escape(unicodedata.normalize('NFC', term))}(?!\w)",
            "",
            unicodedata.normalize("NFC", text),
            flags=re.IGNORECASE,
        )
    return re.sub(r"[ \t]{2,}", " ", text)


def brand_leak(
    *, title: str, description: str, source_title: str, brand_terms: Sequence[str]
) -> tuple[str, str] | None:
    """``(field, offending term)`` when the draft names a brand the source title does not."""
    for field, text in (("title", title), ("description", description)):
        for term in brand_terms:
            if _contains(text, term):
                return field, term
    source_words = {_norm(w) for w in _WORD.findall(source_title)}
    for word in _WORD.findall(title):
        folded = _norm(word)
        if (
            _FOREIGN_LETTERS.search(folded)
            and folded not in source_words
            and folded not in _LOANWORDS
            and not any(ch.isdigit() for ch in folded)
        ):
            return "title", word
    return None


BRAND_LEAK_SUMMARY_VI = (
    "Tiêu đề hoặc mô tả Juli soạn có tên thương hiệu / nhà sản xuất không có trong tiêu đề "
    "sản phẩm gốc, nên Juli soạn lại"
)


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
    description = redact_terms(_plain(detail.get("description")), source_brand_terms(detail))
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
    #: The source title and the brand names it does not carry (:func:`source_brand_terms`).
    source_title: str = ""
    brand_terms: list[str] = Field(default_factory=list)


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
    detail: Mapping[str, Any], attribute_names: Mapping[str, str]
) -> list[dict[str, Any]]:
    """The source's attribute values the new listing may carry, for the category's attributes.

    Only attributes the category knows (``attribute_names``), values copied verbatim
    (``id`` / ``name``) -- never invented -- except a brand / manufacturer: a brand-like
    attribute keeps only values the source TITLE names, and no value of any attribute may
    carry a brand / manufacturer name the title does not (:func:`source_brand_terms`). An
    attribute left with no value is dropped; if the category requires it, the plan says
    ``required_attribute_missing`` rather than leaking the name.
    """
    title = str(detail.get("title") or "")
    terms = source_brand_terms(detail, attribute_names)
    copied: list[dict[str, Any]] = []
    for attribute in detail.get("product_attributes") or []:
        if not isinstance(attribute, Mapping) or not attribute.get("id"):
            continue
        attribute_id = str(attribute["id"])
        if attribute_id not in attribute_names:
            continue
        name = attribute_names.get(attribute_id) or str(attribute.get("name") or "")
        brand_like = _attribute_is_brand(attribute_id, name)
        values: list[dict[str, Any]] = []
        for value in attribute.get("values") or []:
            if not isinstance(value, Mapping):
                continue
            text = str(value.get("name") or "").strip()
            if brand_like and not (text and _contains(title, text)):
                continue
            if text and any(_contains(text, term) for term in terms):
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
    product_attributes = copyable_attributes(detail, attribute_names)
    copied_ids = {row["id"] for row in product_attributes}
    missing = [
        str(a.get("name") or a.get("id"))
        for a in category_attrs
        if _required(a)
        and str(a.get("type") or "PRODUCT_PROPERTY") == "PRODUCT_PROPERTY"
        and str(a.get("id")) not in copied_ids
    ]
    if missing:
        source_ids = {
            str(a.get("id"))
            for a in detail.get("product_attributes") or []
            if isinstance(a, Mapping)
        }
        withheld = any(
            str(a.get("id")) in source_ids and str(a.get("name") or a.get("id")) in missing
            for a in category_attrs
        )
        raise PlanRefusal(
            ERROR_REQUIRED_ATTRIBUTE_MISSING,
            "Sản phẩm gốc thiếu thuộc tính bắt buộc của danh mục: "
            + ", ".join(missing)
            + (
                " (Juli không sao chép tên thương hiệu / nhà sản xuất không có trong tiêu đề "
                "sản phẩm gốc)"
                if withheld
                else ""
            ),
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
        source_title=str(detail.get("title") or ""),
        brand_terms=source_brand_terms(detail, attribute_names),
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
    title: str = Field(min_length=10, max_length=255)
    description: str = Field(min_length=20, max_length=5_000)
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
    leak = brand_leak(
        title=params.title,
        description=params.description,
        source_title=plan.source_title,
        brand_terms=plan.brand_terms,
    )
    if leak is not None:
        # Defence in depth: the runner's pre-confirmation check refuses this first; the
        # seller's own edit is held to the same rule. Nothing is sent to TikTok.
        logger.warning("catalog_create_brand_leak_refused", extra={"field": leak[0]})
        return CreateProductOutput(
            ok=False,
            error_code=ERROR_BRAND_NOT_IN_SOURCE,
            summary_vi=(
                "Chưa tạo sản phẩm: tiêu đề hoặc mô tả có tên thương hiệu / nhà sản xuất "
                "không có trong tiêu đề sản phẩm gốc"
            ),
        )
    try:
        created = _unwrap(
            resources.products.create(
                body=create_body(plan, title=params.title, description=params.description)
            )
        )
    except TikTokAPIError as exc:
        logger.warning("catalog_create_create_failed", extra={"tiktok_code": exc.code})
        return CreateProductOutput(
            ok=False,
            error_code=ERROR_TIKTOK,
            summary_vi=f"TikTok từ chối tạo sản phẩm (mã lỗi {exc.code})",
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


class ProposalRefusal(BaseModel):
    """A CONFIRM proposal refused before the pause (the model may draft again, once)."""

    error_code: str
    #: Shown to the reviewer: never names the offending term.
    summary_vi: str
    #: Read by the model only: what to change.
    model_hint: str


def precheck_create_product(
    resources: Any, context: ProductToolContext, params: CreateProductInput
) -> ProposalRefusal | None:
    """Before the reviewer is asked: the draft must not name a brand the source title lacks."""
    try:
        detail = resources.products.get_details(context.product_id)
    except TikTokAPIError as exc:
        # The create re-checks after the confirmation; do not block the proposal here.
        logger.warning("catalog_create_precheck_failed", extra={"tiktok_code": exc.code})
        return None
    leak = brand_leak(
        title=params.title,
        description=params.description,
        source_title=str(detail.get("title") or ""),
        brand_terms=source_brand_terms(detail),
    )
    if leak is None:
        return None
    field, term = leak
    return ProposalRefusal(
        error_code=ERROR_BRAND_NOT_IN_SOURCE,
        summary_vi=BRAND_LEAK_SUMMARY_VI,
        model_hint=(
            f"error_code={ERROR_BRAND_NOT_IN_SOURCE}: the {field} names {term!r}, a brand or "
            "manufacturer the source title does not contain. Draft the title and description "
            "again without any brand, manufacturer or shop name that is not in the source "
            "title, then call create_product again (once)."
        ),
    )


CREATE_PRODUCT_SPEC = ToolSpec(
    name=CREATE_PRODUCT_TOOL,
    description=(
        "Create the new listing on TikTok with your Vietnamese title and description in the "
        "checked category_id. Never name a brand, manufacturer or shop that the source "
        "title does not name (refused with error_code=brand_not_in_source). Price, stock, "
        "images and attributes come from the source listing server-side. Needs the "
        "reviewer's explicit approval first."
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
    "BRAND_ATTRIBUTE_IDS",
    "CreateProductRefused",
    "ERROR_BRAND_NOT_IN_SOURCE",
    "ProposalRefusal",
    "brand_leak",
    "copyable_attributes",
    "precheck_create_product",
    "redact_terms",
    "source_brand_terms",
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
