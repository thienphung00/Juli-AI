"""The "quét nhanh": first cards within minutes of connecting (fast track P17, D26).

Runs on the priority queue in parallel with the bootstrap fast phase. It reads
the shop's last **14 days** of product performance (A-34 list, 1-2 calls for
the whole shop), asks TikTok's listing diagnosis for the top products by GMV
(one call), and writes **1-3** Optimize Product cards whose action is the
listing's cover image, title or description -- the levers Juli carries out
itself -- labelled "Đề xuất nhanh · dựa trên 14 ngày", confidence "Tham khảo".

Rules and arithmetic only (D24.1: no LLM before approval). The diagnosis is
ADR-106 decision 4 (``diagnose_product``) on the 14-day window with TikTok's
own codes as evidence; no prior window (median trigger only) and no discount
cap (so no price lever). The expected GMV is the D22 formula
(``recoverable_gmv_per_day``) on the same 14 days, which the card states.

The cards go through the same ladder as the full pipeline
(``emit_optimize_product_cards``) and the emission budget, so they take the
day-1 Juli slots (D24.21: 3 Juli / 1 Seller Center / 1 nội dung). When the full
diagnosis runs, a quick card whose product gets the same lever is re-scored in
place; any other quick card is withdrawn (``optimize_product_cards``).

A product the catalog does not hold yet (the fast phase syncs it later) gets a
placeholder ``products`` row from Get Product with ``update_time`` at the epoch,
so the first real product sync overwrites every column.

Sandbox shop (P64, D73.3): a shop read through its OWN ``sandbox_write``
credential whose 14-day A-34 rows show no GMV and no click (TikTok Analytics is
all zeros for a sandbox) is scanned by its real paid orders instead
(``quick_scan_orders``): top products by order revenue, TikTok's diagnosis and the
listing, then a title or description card with a stored rule-based proposal.
Real shops never take that path.

Pure selection here (:func:`select_quick_proposals`); the I/O is
:func:`run_quick_scan`, which the Celery task in
``workers/tasks/shop_quick_scan.py`` calls.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security import resolve_read_credential_for_shop
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.integrations.tiktok import (
    ClientFactoryConfig,
    ProductionReadClientFactory,
    is_own_shop_sandbox_read,
)
from juli_backend.models.ingestion import (
    QUICK_SCAN_DONE,
    QUICK_SCAN_FAILED,
    QUICK_SCAN_RUNNING,
    QUICK_SCAN_SKIPPED,
)
from juli_backend.models.models import Product, Shop, TikTokCredential
from juli_backend.repositories import ShopIngestionStateRepo
from juli_backend.services.optimize_product.cards import reason_sentence
from juli_backend.services.optimize_product.config import StageDiagnosisConfig
from juli_backend.services.optimize_product.decision_cards import (
    LEVER_CODES,
    CardProposal,
    CatalogProduct,
    ShopCardPlan,
    _rule_proposal,
    exclusion_reason,
    recoverable_gmv_per_day,
)
from juli_backend.services.optimize_product.diagnosis import Angle, Diagnosis, diagnose_product
from juli_backend.services.optimize_product.eligibility import (
    gift_reason_from_raw,
    is_gift_product,
)
from juli_backend.services.optimize_product.funnel import FunnelWindow, ProductFunnel, ShopMedians
from juli_backend.services.optimize_product.listing_signals import (
    Evidence,
    parse_tiktok_diagnoses,
)

logger = logging.getLogger(__name__)

#: Shown on the card (D26).
QUICK_SCAN_LABEL = "Đề xuất nhanh · dựa trên 14 ngày"
QUICK_SCAN_CONFIDENCE = "Tham khảo"
#: The chip's tooltip -- seller-facing, so no decision ids or "mã" (P41, D47.7).
QUICK_SCAN_BASIS = (
    "GMV dự kiến tính trên 14 ngày gần nhất (trung bình/ngày) và chẩn đoán của TikTok"
)
WINDOW_DAYS = 14
#: The levers a quick card may carry: what Juli does itself on the listing.
QUICK_LEVERS: frozenset[Angle] = frozenset({Angle.ANH_BIA, Angle.TIEU_DE, Angle.MO_TA})

TOP_PRODUCTS_ENV = "QUICK_SCAN_TOP_PRODUCTS"
MAX_CARDS_ENV = "QUICK_SCAN_MAX_CARDS"
ENABLED_ENV = "QUICK_SCAN_ENABLED"
DEFAULT_TOP_PRODUCTS = 10
DEFAULT_MAX_CARDS = 3
#: A-34 pages read (``page_size`` 100, sorted by GMV): at most 200 products.
A34_PAGE_SIZE = 100
A34_MAX_PAGES = 2
#: Get Product calls for chosen products the catalog does not hold yet.
MAX_DETAIL_CALLS = 6
#: TikTok's statuses for a listing on sale (placeholder rows keep TikTok's own).
PLACEHOLDER_UPDATE_TIME = datetime(1970, 1, 1)
SHOP_UTC_OFFSET = timedelta(hours=7)


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return min(max(value, minimum), maximum)


def top_products() -> int:
    return _env_int(TOP_PRODUCTS_ENV, DEFAULT_TOP_PRODUCTS, minimum=1, maximum=50)


def max_cards() -> int:
    """1-3 cards (D26); the env can lower it, never raise it past the 3 Juli slots."""
    return _env_int(MAX_CARDS_ENV, DEFAULT_MAX_CARDS, minimum=1, maximum=3)


def enabled() -> bool:
    return os.getenv(ENABLED_ENV, "1").strip().lower() not in {"0", "false", "no", "off"}


def scan_window(now: datetime) -> tuple[date, date]:
    """``(start_date_ge, end_date_lt)``: the last 14 full local (UTC+7) days."""
    today = (now.astimezone(UTC) + SHOP_UTC_OFFSET).date()
    return today - timedelta(days=WINDOW_DAYS), today


# -- pure selection -----------------------------------------------------------


def funnels_from_a34(rows: Iterable[dict], *, days: int = WINDOW_DAYS) -> list[ProductFunnel]:
    """One 14-day funnel per A-34 row (``total_performance``); the 14-day GMV as ``gmv_28d``."""
    out: list[ProductFunnel] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        product_id = str(row.get("id") or "")
        if not product_id or product_id in seen:
            continue
        seen.add(product_id)
        total = row.get("total_performance")
        window = FunnelWindow.from_a34_total_performance(
            total if isinstance(total, dict) else {}, days=days
        )
        title = str(row.get("title") or row.get("product_name") or product_id)
        out.append(
            ProductFunnel(
                product_id=product_id,
                title=title,
                current=window,
                prior=None,
                gmv_28d=window.gmv,
            )
        )
    return out


def top_by_gmv(funnels: Iterable[ProductFunnel], limit: int) -> list[str]:
    ranked = sorted(funnels, key=lambda f: (f.current.gmv, f.current.clicks), reverse=True)
    return [f.product_id for f in ranked if f.current.gmv > 0 or f.current.clicks > 0][:limit]


def evidence_from_diagnoses(payload: Any) -> dict[str, list[Evidence]]:
    """``data.products[]`` of the diagnoses endpoint -> product id -> TikTok's codes."""
    data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
    products = data.get("products") if isinstance(data, dict) else None
    out: dict[str, list[Evidence]] = {}
    for entry in products if isinstance(products, list) else []:
        if isinstance(entry, dict) and entry.get("id"):
            out[str(entry["id"])] = parse_tiktok_diagnoses(entry)
    return out


@dataclass(frozen=True)
class QuickSelection:
    """The quick scan's ranked candidates (best first) and the shop medians."""

    proposals: list[CardProposal]
    medians: ShopMedians
    funnels: dict[str, ProductFunnel]
    asked: tuple[str, ...] = ()
    evidence: dict[str, list[Evidence]] = field(default_factory=dict)


def select_quick_proposals(
    funnels: list[ProductFunnel],
    evidence_by_id: dict[str, list[Evidence]],
    asked: Iterable[str],
    config: StageDiagnosisConfig | None = None,
) -> QuickSelection:
    """Every quick-eligible proposal among the products TikTok was asked about, ranked.

    Eligible: decision 4 finds a weak stage and the lever it picks (in branch
    order, backed by a TikTok code) is the cover image, title or description.
    Ranked by the D22 recoverable GMV per day on the 14 days (ties: gap × GMV).
    The caller keeps the first 1-3 that pass the catalog checks.
    """
    config = config or StageDiagnosisConfig()
    # Gift items (``eligibility``) are neither candidates nor peers of the medians.
    funnels = [
        f
        for f in funnels
        if not is_gift_product(title=f.title, extra_patterns=config.exclude_title_patterns)
    ]
    medians = ShopMedians.from_products(funnels, config)
    by_id = {f.product_id: f for f in funnels}
    asked_ids = tuple(pid for pid in asked if pid in by_id)
    proposals: list[CardProposal] = []
    for product_id in asked_ids:
        funnel = by_id[product_id]
        result = diagnose_product(
            funnel,
            medians,
            evidence_by_id.get(product_id, []),
            config,
            diagnoses_asked=True,
            discount_cap_set=False,
        )
        if not isinstance(result, Diagnosis) or result.angle not in QUICK_LEVERS:
            continue
        if not any(e.source.value == "tiktok" for e in result.evidence):
            continue
        reason = reason_sentence(result, full_median_peers=config.full_median_peers)
        proposal = _rule_proposal(result, reason, config)
        value, basis = recoverable_gmv_per_day(proposal.stage, proposal.gaps, funnel.current)
        proposals.append(replace(proposal, recoverable_gmv_per_day=value, recoverable_basis=basis))
    proposals.sort(
        key=lambda p: (
            p.recoverable_gmv_per_day is not None,
            p.recoverable_gmv_per_day or Decimal(0),
            p.rank_score,
        ),
        reverse=True,
    )
    return QuickSelection(
        proposals=proposals,
        medians=medians,
        funnels=by_id,
        asked=asked_ids,
        evidence={pid: evidence_by_id.get(pid, []) for pid in asked_ids},
    )


def quick_scan_block(scanned_at: datetime) -> dict[str, Any]:
    """``diagnosis.quick_scan`` of a quick card's payload (contract §1)."""
    return {
        "label": QUICK_SCAN_LABEL,
        "confidence": QUICK_SCAN_CONFIDENCE,
        "window_days": WINDOW_DAYS,
        "scanned_at": scanned_at.isoformat(),
        "basis": QUICK_SCAN_BASIS,
    }


# -- I/O ---------------------------------------------------------------------------

ResolveCredentialFn = Callable[[AsyncSession, uuid.UUID], Awaitable[TikTokCredential]]
CreateResourcesFn = Callable[[ClientFactoryConfig], Any]
SessionFactory = Callable[[], Any]


@dataclass
class QuickScanResult:
    shop_id: uuid.UUID
    status: str | None = None
    skipped_reason: str | None = None
    cards: int = 0
    surfaced: int = 0
    #: P64: a card of the last emission stands surfaced for the seller.
    shown: bool = False
    calls: int = 0
    candidates: int = 0
    seconds_since_connect: float | None = None
    error: str | None = None
    #: P67 (D75 Q1): why a product (or ``product/lever``) got no card this run -- the
    #: operator's forced sandbox scan logs it on one line, so "no card" is never silent.
    reasons: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class _Fetched:
    funnels: list[ProductFunnel]
    asked: list[str]
    evidence: dict[str, list[Evidence]]
    calls: int


def fetch_quick_inputs(
    resources: Any, *, start: date, end_lt: date, top_n: int, sleep_s: float = 0.0
) -> _Fetched:
    """A-34 (≤ 2 pages) then the diagnoses of the top ``top_n``. Sync; run in a thread."""
    rows: list[dict] = []
    calls = 0
    token: str | None = None
    for _page in range(A34_MAX_PAGES):
        data = resources.analytics.list_product_performance(
            start_date_ge=start.isoformat(),
            end_date_lt=end_lt.isoformat(),
            page_size=A34_PAGE_SIZE,
            page_token=token,
        )
        calls += 1
        data = data if isinstance(data, dict) else {}
        rows.extend(r for r in data.get("products") or [] if isinstance(r, dict))
        token = data.get("next_page_token") or None
        if not token:
            break
        if sleep_s:
            time.sleep(sleep_s)
    funnels = funnels_from_a34(rows)
    # Gift items never become quick cards: do not spend the diagnosis call on them.
    asked = top_by_gmv([f for f in funnels if not is_gift_product(title=f.title)], top_n)
    evidence: dict[str, list[Evidence]] = {}
    if asked:
        evidence = evidence_from_diagnoses(resources.products.get_diagnoses(asked))
        calls += 1
    return _Fetched(funnels=funnels, asked=asked, evidence=evidence, calls=calls)


def _detail_values(detail: dict) -> dict[str, Any] | None:
    title = str(detail.get("title") or "").strip()
    status = str(detail.get("status") or "").strip()
    if not title or not status:
        return None
    created = detail.get("create_time")
    return {
        "title": title[:500],
        "name": title[:500],
        "status": status[:50],
        "tiktok_created_at": (
            datetime.fromtimestamp(int(created), tz=UTC).replace(tzinfo=None)
            if isinstance(created, int | float) and created > 0
            else None
        ),
        # The epoch: any real product sync is newer and overwrites every column.
        "update_time": PLACEHOLDER_UPDATE_TIME,
    }


def _assert_read_credential(credential: TikTokCredential, shop_id: uuid.UUID) -> None:
    from juli_backend.services.shop_diagnosis_daily import assert_read_credential_for

    assert_read_credential_for(credential, shop_id)


async def _products_by_tiktok_id(
    session: AsyncSession, shop_id: uuid.UUID, ids: Iterable[str]
) -> dict[str, Product]:
    wanted = list(ids)
    if not wanted:
        return {}
    rows = await session.execute(
        select(Product).where(Product.shop_id == shop_id, Product.tiktok_product_id.in_(wanted))
    )
    return {str(p.tiktok_product_id): p for p in rows.scalars()}


async def _full_cards_exist(session: AsyncSession, shop_id: uuid.UUID) -> bool:
    state = await ShopIngestionStateRepo(session).find(shop_id)
    return state is not None and state.first_card_at is not None


async def run_quick_scan(
    *,
    session_factory: SessionFactory,
    shop_id: uuid.UUID,
    app_key: str,
    app_secret: str,
    resolve_credential: ResolveCredentialFn | None = None,
    create_resources: CreateResourcesFn | None = None,
    rate_limiter: Any | None = None,
    rate_limit_sleep: Callable[[float], Any] = time.sleep,
    now: datetime | None = None,
    config: StageDiagnosisConfig | None = None,
    force: bool = False,
) -> QuickScanResult:
    """Read, select and write the shop's quick cards. Never raises; see the module doc.

    ``force`` (operator, P64 D73.3) re-runs the scan for the SANDBOX shop only (its own
    ``sandbox_write`` credential): it ignores an earlier ``done`` / ``skipped`` and the
    existing full cards. For any other shop it is ignored.
    """
    result = QuickScanResult(shop_id=shop_id)
    if not enabled():
        result.skipped_reason = "disabled"
        return result
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    resolve = resolve_credential or resolve_read_credential_for_shop

    async with session_factory() as session:
        async with with_shop_scope(session, shop_id):
            repo = ShopIngestionStateRepo(session)
            state = await repo.ensure(shop_id)
            forced = False
            credential: TikTokCredential | None = None
            if force:
                credential = await resolve(session, shop_id)
                _assert_read_credential(credential, shop_id)
                forced = is_own_shop_sandbox_read(
                    credential.capability, credential_shop_id=credential.shop_id, shop_id=shop_id
                )
            if not forced and state.quick_scan_status in (QUICK_SCAN_DONE, QUICK_SCAN_SKIPPED):
                result.skipped_reason = "already_ran"
                result.status = state.quick_scan_status
                return result
            # Fast track P20 (D28.4): a read-only shop gets no new cards. The
            # scan's state is left as it is, so a renewal can still run it.
            from juli_backend.services.subscriptions import is_read_only

            if await is_read_only(session, shop_id, today=None):
                result.skipped_reason = "read_only"
                logger.info(
                    "shop_quick_scan_skipped",
                    extra={"shop_id": str(shop_id), "reason": result.skipped_reason},
                )
                return result
            if not forced and state.first_card_at is not None:
                await repo.update(shop_id, quick_scan_status=QUICK_SCAN_SKIPPED)
                await session.commit()
                result.status, result.skipped_reason = QUICK_SCAN_SKIPPED, "full_cards_exist"
                logger.info(
                    "shop_quick_scan_skipped",
                    extra={"shop_id": str(shop_id), "reason": result.skipped_reason},
                )
                return result
            if credential is None:
                credential = await resolve(session, shop_id)
                _assert_read_credential(credential, shop_id)
            shop = await session.get(Shop, shop_id)
            if shop is None:
                raise ValueError(f"quick scan: shop {shop_id} not found")
            factory_config = ClientFactoryConfig(
                app_key=app_key,
                app_secret=app_secret,
                access_token=credential.access_token,
                merchant_auth_id=str(credential.merchant_authorization_id),
                shop_cipher=credential.shop_cipher,
                credential_capability=credential.capability,
                own_shop_sandbox_read=is_own_shop_sandbox_read(
                    credential.capability, credential_shop_id=credential.shop_id, shop_id=shop_id
                ),
            )
            shop_key = shop.tiktok_shop_id or str(shop_id)
            sandbox = factory_config.own_shop_sandbox_read
            await repo.stamp_once(
                shop_id, "quick_scan_started_at", quick_scan_status=QUICK_SCAN_RUNNING
            )
            connect_at = state.connect_committed_at
        await session.commit()

    try:
        await _scan_and_write(
            result,
            session_factory=session_factory,
            shop_id=shop_id,
            factory_config=factory_config,
            shop_key=shop_key,
            app_key=app_key,
            create_resources=create_resources,
            rate_limiter=rate_limiter,
            rate_limit_sleep=rate_limit_sleep,
            moment=moment,
            config=config or StageDiagnosisConfig(),
            sandbox=sandbox,
            forced=forced,
        )
    except Exception as exc:
        result.status = QUICK_SCAN_FAILED
        result.error = type(exc).__name__
        logger.error(
            "shop_quick_scan_failed",
            extra={"shop_id": str(shop_id), "error": repr(exc)[:200]},
            exc_info=True,
        )
        await _finish(session_factory, shop_id, status=QUICK_SCAN_FAILED, cards=0)
        return result

    finished = await _finish(
        session_factory, shop_id, status=result.status or QUICK_SCAN_DONE, cards=result.cards
    )
    if connect_at is not None and finished is not None:
        result.seconds_since_connect = round((finished - connect_at).total_seconds(), 3)
    if forced:
        _log_forced_outcome(result)
    logger.info(
        "shop_quick_scan_done",
        extra={
            "shop_id": str(shop_id),
            "status": result.status,
            "cards": result.cards,
            "surfaced": result.surfaced,
            "candidates": result.candidates,
            "tiktok_calls": result.calls,
            "skipped_reason": result.skipped_reason,
            "seconds_since_connect": result.seconds_since_connect,
        },
    )
    return result


def _log_forced_outcome(result: QuickScanResult) -> None:
    """P67 (D75 Q1): the operator's forced scan says on ONE line what it left and why.

    journald keeps the message, not ``extra`` (P64 D12), so the outcome is in the text:
    ``journalctl -u juli-worker* | grep shop_quick_scan_forced_outcome``.
    """
    reasons = ", ".join(f"{key}={value}" for key, value in sorted(result.reasons.items()))
    logger.info(
        "shop_quick_scan_forced_outcome shop_id=%s status=%s shown=%s cards=%s "
        "candidates=%s skipped_reason=%s reasons=[%s]",
        result.shop_id,
        result.status,
        result.shown,
        result.cards,
        result.candidates,
        result.skipped_reason,
        reasons,
    )


async def _finish(
    session_factory: SessionFactory, shop_id: uuid.UUID, *, status: str, cards: int
) -> datetime | None:
    """Stamp the end of the scan. Guarded: it also runs on the failing path."""
    try:
        async with session_factory() as session:
            async with with_shop_scope(session, shop_id):
                repo = ShopIngestionStateRepo(session)
                state, _ = await repo.stamp_once(
                    shop_id, "quick_scan_done_at", quick_scan_status=status, quick_scan_cards=cards
                )
                done_at = state.quick_scan_done_at
            await session.commit()
            return done_at
    except Exception:
        logger.error("shop_quick_scan_state_write_failed", exc_info=True)
        return None


async def _scan_and_write(
    result: QuickScanResult,
    *,
    session_factory: SessionFactory,
    shop_id: uuid.UUID,
    factory_config: ClientFactoryConfig,
    shop_key: str,
    app_key: str,
    create_resources: CreateResourcesFn | None,
    rate_limiter: Any | None,
    rate_limit_sleep: Callable[[float], Any],
    moment: datetime,
    config: StageDiagnosisConfig,
    sandbox: bool = False,
    forced: bool = False,
) -> None:
    from juli_backend.services.shop_diagnosis_daily.pacing import (
        RateLimitedResources,
        SharedWindowGate,
    )

    build = create_resources or ProductionReadClientFactory().create_resources
    resources = build(factory_config)
    if rate_limiter is not None:
        resources = RateLimitedResources(
            resources,
            SharedWindowGate(
                rate_limiter, app_id=app_key, shop_key=shop_key, sleep=rate_limit_sleep
            ),
        )
    start, end_lt = scan_window(moment)
    fetched = await asyncio.to_thread(
        fetch_quick_inputs, resources, start=start, end_lt=end_lt, top_n=top_products()
    )
    result.calls = fetched.calls

    async def by_orders() -> None:
        await _orders_scan_and_write(
            result,
            session_factory=session_factory,
            shop_id=shop_id,
            resources=resources,
            moment=moment,
            end_lt=end_lt,
            config=config,
            forced=forced,
        )

    if sandbox and not fetched.asked:
        # P64 (D73.3): no product with GMV or clicks -- the sandbox's zero analytics.
        await by_orders()
        return
    selection = select_quick_proposals(fetched.funnels, fetched.evidence, fetched.asked, config)
    result.candidates = len(selection.proposals)
    if not selection.proposals:
        if sandbox:
            # P67 (D75 Q1): the sandbox's analytics are no longer all zero but TikTok
            # backs no lever with a code -- its real paid orders still pick the cards.
            result.reasons["analytics"] = "no_candidate"
            await by_orders()
            return
        result.status, result.skipped_reason = QUICK_SCAN_DONE, "no_candidate"
        return

    async with session_factory() as session:
        async with with_shop_scope(session, shop_id):
            known = await _products_by_tiktok_id(
                session, shop_id, (p.product_id for p in selection.proposals)
            )
        await session.commit()

    # Missing catalog rows: Get Product for the next candidates, bounded.
    details: dict[str, dict[str, Any]] = {}
    detail_calls = 0
    chosen: list[CardProposal] = []
    for proposal in selection.proposals:
        if len(chosen) >= max_cards():
            break
        product = known.get(proposal.product_id)
        if product is not None:
            title, status = (product.title or product.name), product.status
        else:
            if detail_calls >= MAX_DETAIL_CALLS:
                continue
            detail_calls += 1
            raw = await asyncio.to_thread(resources.products.get_details, proposal.product_id)
            result.calls += 1
            values = _detail_values(raw if isinstance(raw, dict) else {})
            if values is None or gift_reason_from_raw(raw, config.exclude_title_patterns):
                continue
            details[proposal.product_id] = values
            title, status = values["title"], values["status"]
        if exclusion_reason(CatalogProduct(proposal.product_id, title, status), config):
            continue
        chosen.append(replace(proposal, title=title))

    if not chosen:
        if sandbox:
            result.reasons["analytics"] = "no_candidate"
            await by_orders()
            return
        result.status, result.skipped_reason = QUICK_SCAN_DONE, "no_candidate"
        return
    await _emit_quick_cards(
        result,
        session_factory=session_factory,
        shop_id=shop_id,
        chosen=chosen,
        details=details,
        medians=selection.medians,
        funnels=selection.funnels,
        products_scored=len(selection.funnels),
        as_of=end_lt - timedelta(days=1),
        quick_block=quick_scan_block(moment),
        computed_at=moment,
        forced=forced,
    )
    if sandbox and forced and not result.shown:
        # P67 (D75 Q1): every analytics card's chain is taken -- the orders' cards next.
        await by_orders()


async def _emit_quick_cards(
    result: QuickScanResult,
    *,
    session_factory: SessionFactory,
    shop_id: uuid.UUID,
    chosen: list[CardProposal],
    details: dict[str, dict[str, Any]],
    medians: ShopMedians,
    funnels: dict[str, ProductFunnel],
    products_scored: int,
    as_of: date,
    quick_block: dict[str, Any],
    computed_at: datetime,
    forced: bool = False,
) -> None:
    """Write the chosen quick cards through the full pipeline's ladder and the budget."""
    from juli_backend.core.config import decision_emission_config
    from juli_backend.repositories import ProductsRepo
    from juli_backend.services.action_cards.emission_budget import apply_emission_budget
    from juli_backend.services.action_cards.optimize_product_cards import (
        OptimizeProductPlan,
        emit_optimize_product_cards,
    )

    async with session_factory() as session:
        async with with_shop_scope(session, shop_id):
            if not forced and await _full_cards_exist(session, shop_id):
                # The full diagnosis landed first: it owns the cards.
                result.status, result.skipped_reason = QUICK_SCAN_SKIPPED, "full_cards_exist"
                return
            products_repo = ProductsRepo(session)
            for product_id, values in details.items():
                await products_repo.upsert(shop_id=shop_id, tiktok_product_id=product_id, **values)
            products = await _products_by_tiktok_id(
                session, shop_id, (p.product_id for p in chosen)
            )
            ranked = [replace(p, rank=i) for i, p in enumerate(chosen, start=1)]
            op_plan = OptimizeProductPlan(
                as_of=as_of,
                plan=ShopCardPlan(
                    proposals=ranked,
                    medians=medians,
                    skips=[],
                    excluded={},
                    products_scored=products_scored,
                ),
                products=products,
                days={},
                funnels={p.product_id: funnels[p.product_id] for p in ranked},
                quick_scan=quick_block,
            )
            emission_config = decision_emission_config()
            decisions = await emit_optimize_product_cards(
                session,
                shop_id,
                op_plan,
                computed_at=computed_at,
                emission_config=emission_config,
            )
            # Fast track P60-1a: the quick-scan cards' `proposed` rows (never raises).
            from juli_backend.services import card_events

            await card_events.record_emissions(
                session, decisions, occurred_at=computed_at, config=emission_config
            )
            outcome = await apply_emission_budget(
                session, shop_id, now=computed_at, config=emission_config
            )
            present = [p for p in ranked if p.product_id in products]
            for proposal, decision in zip(present, decisions, strict=False):
                if decision.suppressed_reason is not None:
                    key = f"{proposal.product_id}/{LEVER_CODES[proposal.lever]}"
                    result.reasons[key] = decision.suppressed_reason
            written = [
                d.card for d in decisions if d.suppressed_reason is None and d.card is not None
            ]
            written_ids = {card.id for card in written}
            result.surfaced = sum(1 for c in outcome.newly_surfaced if c.id in written_ids)
            if forced and written and not _any_shown(decisions):
                # P64 (D73.3): the operator's forced re-run on the SANDBOX shop must leave
                # the reviewer one card to act on. Today's / this week's budget (earlier
                # test surfacings count) held every new card as a draft: surface the best.
                best = min(written, key=lambda card: card.priority)
                best.surfaced_at = computed_at
                best.suppressed_reason = None
                await session.flush()
                result.surfaced += 1
                logger.info(
                    "shop_quick_scan_forced_surface",
                    extra={"shop_id": str(shop_id), "card_id": str(best.id)},
                )
            result.cards = len(written_ids)
            result.shown = _any_shown(decisions)
        await session.commit()
    result.status = QUICK_SCAN_DONE


def _any_shown(decisions: list[Any]) -> bool:
    """A card of this emission stands surfaced (new, or kept unchanged) for the seller."""
    return any(
        d.card is not None and d.card.status == "active" and d.card.surfaced_at is not None
        for d in decisions
    )


async def _orders_scan_and_write(
    result: QuickScanResult,
    *,
    session_factory: SessionFactory,
    shop_id: uuid.UUID,
    resources: Any,
    moment: datetime,
    end_lt: date,
    config: StageDiagnosisConfig,
    forced: bool = False,
) -> None:
    """P64 (D73.3): the sandbox's quick cards from its paid orders (``quick_scan_orders``)."""
    from juli_backend.services.onboarding.quick_scan_orders import (
        ORDERS_WINDOW_DAYS,
        ProductSales,
        funnel_from_sales,
        orders_proposal,
        orders_quick_block,
        rank_by_orders,
    )
    from juli_backend.services.shop_diagnosis_daily.orders_source import load_paid_order_lines

    last = end_lt - timedelta(days=1)
    async with session_factory() as session:
        async with with_shop_scope(session, shop_id):
            lines = await load_paid_order_lines(
                session, shop_id, end_lt - timedelta(days=ORDERS_WINDOW_DAYS), last
            )
            ranked_sales = rank_by_orders(lines, top_products())
            known = await _products_by_tiktok_id(
                session, shop_id, (s.product_id for s in ranked_sales)
            )
        await session.commit()
    if not ranked_sales:
        result.status, result.skipped_reason = QUICK_SCAN_DONE, "no_paid_orders"
        return

    asked = [s.product_id for s in ranked_sales]
    evidence: dict[str, list[Evidence]] = {}
    try:
        evidence = evidence_from_diagnoses(
            await asyncio.to_thread(resources.products.get_diagnoses, asked)
        )
    except Exception as exc:
        # The listing itself still gives Juli's own reading (local evidence).
        logger.warning(
            "shop_quick_scan_orders_diagnoses_failed",
            extra={"shop_id": str(shop_id), "error_type": type(exc).__name__},
        )
    result.calls += 1

    details: dict[str, dict[str, Any]] = {}
    funnels: dict[str, ProductFunnel] = {}
    chosen: list[CardProposal] = []
    listings: dict[str, tuple[ProductSales, dict[str, Any], str]] = {}
    for detail_calls, sales in enumerate(ranked_sales):
        if len(chosen) >= max_cards() or detail_calls >= MAX_DETAIL_CALLS:
            break
        raw = await asyncio.to_thread(resources.products.get_details, sales.product_id)
        result.calls += 1
        listing = raw if isinstance(raw, dict) else {}
        values = _detail_values(listing)
        if values is None:
            result.reasons[sales.product_id] = "listing_unreadable"
            continue
        if gift := gift_reason_from_raw(listing, config.exclude_title_patterns):
            result.reasons[sales.product_id] = gift
            continue
        proposal = orders_proposal(sales, listing, evidence.get(sales.product_id, []), config)
        if proposal is None:
            # Neither TikTok nor Juli's reading of the listing flags its title or
            # description, or the listing has nothing to add (``orders_proposal``).
            result.reasons[sales.product_id] = "no_listing_reason"
            continue
        product = known.get(sales.product_id)
        if product is not None:
            title, status = (product.title or product.name), product.status
        else:
            details[sales.product_id] = values
            title, status = values["title"], values["status"]
        if excluded := exclusion_reason(CatalogProduct(sales.product_id, title, status), config):
            result.reasons[sales.product_id] = excluded
            continue
        funnels[sales.product_id] = funnel_from_sales(sales, title, days=ORDERS_WINDOW_DAYS)
        chosen.append(replace(proposal, title=title))
        listings[sales.product_id] = (sales, listing, title)
    result.candidates = len(chosen)
    if not chosen:
        result.status, result.skipped_reason = QUICK_SCAN_DONE, "no_candidate"
        return
    await _emit_quick_cards(
        result,
        session_factory=session_factory,
        shop_id=shop_id,
        chosen=chosen,
        details=details,
        medians=ShopMedians.from_products(list(funnels.values()), config),
        funnels=funnels,
        products_scored=len(ranked_sales),
        as_of=last,
        quick_block=orders_quick_block(moment),
        computed_at=moment,
        forced=forced,
    )
    if not forced or result.shown:
        return
    # P64 (D73.3): every chosen (product, lever) chain is taken -- a card the seller
    # already approved, rejected or saw expire holds it for its 7 days. The forced
    # sandbox re-run offers the other listing lever of the same best sellers.
    alternatives: list[CardProposal] = []
    for proposal in chosen:
        sales, listing, title = listings[proposal.product_id]
        other = ("description",) if proposal.lever is Angle.TIEU_DE else ("title",)
        alternative = orders_proposal(
            sales, listing, evidence.get(sales.product_id, []), config, levers=other
        )
        if alternative is not None:
            alternatives.append(replace(alternative, title=title))
    if not alternatives:
        return
    await _emit_quick_cards(
        result,
        session_factory=session_factory,
        shop_id=shop_id,
        chosen=alternatives,
        details=details,
        medians=ShopMedians.from_products(list(funnels.values()), config),
        funnels=funnels,
        products_scored=len(ranked_sales),
        as_of=last,
        quick_block=orders_quick_block(moment),
        computed_at=moment,
        forced=forced,
    )


__all__ = [
    "MAX_CARDS_ENV",
    "QUICK_LEVERS",
    "QUICK_SCAN_BASIS",
    "QUICK_SCAN_CONFIDENCE",
    "QUICK_SCAN_LABEL",
    "TOP_PRODUCTS_ENV",
    "WINDOW_DAYS",
    "QuickScanResult",
    "QuickSelection",
    "evidence_from_diagnoses",
    "fetch_quick_inputs",
    "funnels_from_a34",
    "max_cards",
    "quick_scan_block",
    "run_quick_scan",
    "scan_window",
    "select_quick_proposals",
    "top_by_gmv",
    "top_products",
]
