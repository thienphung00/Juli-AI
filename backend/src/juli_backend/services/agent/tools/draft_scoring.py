"""TikTok's own check of a confirmed listing draft, right before the write (P76-5).

The sandbox shop's live diagnosis (``GET /product/202405/products/diagnoses``) lags on
TikTok's side: a day after an edit that met the criteria it still read "4 lỗi → 4 lỗi"
(edge case D31). So Đo lường alone cannot tell "the edit did not help" from "TikTok has
not re-diagnosed yet". This module asks TikTok to diagnose the *draft* the seller just
confirmed, once, immediately before ``update_product_listing`` writes it, and the result
is stored on that write's ledger outcome (``tool_executions.outcome_json``, the same JSON
``agent_runs.listing`` reads confirmed writes from) -- no migration.

Endpoint: ``POST /product/202411/products/diagnose_optimize`` (Diagnose and Optimize
Product; bundled OAS ``tts-openapi-guide/references/oas/paths/product.json``). Read-only:
"Writes nothing to the product" -- on the sandbox capability allowlist, not on the
production-write one, so scoring runs only with a ``SandboxWriteResources`` bundle. With a
``product_id`` plus a new ``title`` / ``description`` / ``main_images`` TikTok diagnoses the
existing product with those values substituted. Response ``data``::

    {"diagnoses": [{"field": "TITLE" | "DESCRIPTION" | "IMAGE" | "ATTRIBUTE" | "SIZE_CHART",
                    "diagnosis_results": [{"code": "...", "how_to_solve": "...",
                                           "quality_tier": "FAIR" | "GOOD"}],
                    "suggestion": {"smart_texts": [...], "seo_words": [...], "images": [...]}}],
     "listing_quality": {"current_tier": "POOR" | "FAIR" | "GOOD",
                         "remaining_recommendations": 3}}   # tier: US only

``optimization_fields`` is ``["NONE"]``: suggestions are not requested (the OAS warns a
DESCRIPTION suggestion "may take more than 10 seconds"), only the diagnosis codes, which
come back regardless. Only codes are kept -- never TikTok's free text.

Never a guess and never a blocker: scoring starts first, the write is performed while it
runs, and only afterwards does the handler collect the score (P83). Any TikTok error,
unexpected payload or a read slower than :data:`DRAFT_SCORE_BUDGET_SECONDS` (from the start
of scoring) gives ``status="not_read"``; the write is unaffected either way.
"""

from __future__ import annotations

import concurrent.futures
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from juli_backend.integrations.tiktok import SandboxWriteResources
from juli_backend.services.agent.tools.diagnosis_labels import is_diagnosis_code

logger = logging.getLogger(__name__)

#: TikTok's check gets this long in total, measured from when scoring starts (P83: it runs
#: while the write goes out, so the write never waits on it; the old 3 s wait before the
#: write timed out on the live sandbox, run d7b5d16c). The TikTok client's own socket
#: timeout (15 s) is per request and not adjustable per call, so the wait is bounded here;
#: a late answer is discarded.
DRAFT_SCORE_BUDGET_SECONDS = 12.0
#: Suggestions are not requested (see module docstring); codes return regardless.
OPTIMIZATION_FIELDS: tuple[str, ...] = ("NONE",)

STATUS_SCORED: Final = "scored"
STATUS_NOT_READ: Final = "not_read"


class DraftScore(BaseModel):
    """TikTok's diagnosis of the confirmed draft: its codes, or ``not_read``."""

    model_config = ConfigDict(frozen=True)

    status: Literal["scored", "not_read"]
    #: The diagnosis codes TikTok raised for the draft (deduplicated). Empty when
    #: ``not_read`` -- read ``status``, never infer "0 lỗi" from an empty list.
    codes_after: list[str] = Field(default_factory=list)
    #: ISO-8601 UTC time of TikTok's answer; ``None`` when ``not_read``.
    scored_at: str | None = None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def parse_draft_codes(raw: object) -> list[str] | None:
    """The diagnosis codes in a ``diagnose_optimize`` ``data`` payload, or ``None`` when
    the payload is not one (so the caller records ``not_read``, not "no issues")."""
    if not isinstance(raw, Mapping):
        return None
    diagnoses = raw.get("diagnoses")
    if diagnoses is None:
        # TikTok returned no diagnosis block at all: an answer we cannot read as "clean".
        return None
    if not isinstance(diagnoses, list):
        return None
    codes: list[str] = []
    for entry in diagnoses:
        if not isinstance(entry, Mapping):
            continue
        for result in entry.get("diagnosis_results") or []:
            code = result.get("code") if isinstance(result, Mapping) else None
            if is_diagnosis_code(code) and code not in codes:
                codes.append(code)
    return codes


class PendingDraftScore:
    """A scoring call already in flight on its own thread; :meth:`wait` collects it.

    The deadline is fixed when scoring *starts*, so a write that runs meanwhile spends
    from the same budget. A late answer, or one that arrives after the write failed and
    nobody waits, is discarded; the thread closes its own client either way.
    """

    def __init__(
        self,
        future: concurrent.futures.Future[object] | None,
        deadline: float,
        budget_seconds: float,
        monotonic: Callable[[], float],
        clock: Callable[[], str],
    ) -> None:
        self._future = future
        self._deadline = deadline
        self._budget_seconds = budget_seconds
        self._monotonic = monotonic
        self._clock = clock

    def wait(self) -> DraftScore:
        """The score once the call is done, or ``not_read`` when the budget runs out."""
        if self._future is None:
            return DraftScore(status=STATUS_NOT_READ)
        remaining = max(0.0, self._deadline - self._monotonic())
        try:
            raw = self._future.result(timeout=remaining)
        except concurrent.futures.TimeoutError:
            logger.warning("draft_score_timeout", extra={"timeout_seconds": self._budget_seconds})
            return DraftScore(status=STATUS_NOT_READ)
        except Exception:  # TikTok / credential / network: unknown, never a guess
            logger.warning("draft_score_unread", exc_info=True)
            return DraftScore(status=STATUS_NOT_READ)
        codes = parse_draft_codes(raw)
        if codes is None:
            logger.warning("draft_score_unparsed")
            return DraftScore(status=STATUS_NOT_READ)
        return DraftScore(status=STATUS_SCORED, codes_after=codes, scored_at=self._clock())


def start_listing_draft_score(
    resources: Any,
    product_id: str,
    category_id: str,
    title: str | None,
    description_html: str | None,
    main_images: Sequence[Mapping[str, Any]] | None,
    *,
    budget_seconds: float | None = None,
    clock: Callable[[], str] = _now_iso,
    monotonic: Callable[[], float] = time.monotonic,
) -> PendingDraftScore:
    """Start asking TikTok to diagnose the draft and return at once (P83).

    Never raises: with no own-session client the pending score is ``not_read``."""
    budget = DRAFT_SCORE_BUDGET_SECONDS if budget_seconds is None else budget_seconds
    started = monotonic()

    # The call outlives this function and runs while the write goes out on the bundle's
    # client: it runs on a copy of the guarded client with its own HTTP session, never the
    # write's (``requests.Session`` is not guaranteed thread-safe), closed when it ends.
    isolate = getattr(resources.products, "with_own_session", None)
    try:
        products = isolate() if callable(isolate) else None
    except Exception:
        products = None
    if products is None:
        logger.warning("draft_score_no_own_session")
        return PendingDraftScore(None, started, budget, monotonic, clock)

    def call() -> object:
        try:
            return products.diagnose_optimize(
                product_id=product_id,
                category_id=category_id,
                optimization_fields=list(OPTIMIZATION_FIELDS),
                title=title,
                description=description_html,
                main_images=[dict(image) for image in main_images] if main_images else None,
            )
        finally:
            products.close()

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="draft-score")
    try:
        future = pool.submit(call)
    finally:
        # The worker finishes its one call and exits; nothing waits on the pool.
        pool.shutdown(wait=False)
    return PendingDraftScore(future, started + budget, budget, monotonic, clock)


def score_listing_draft(
    resources: Any,
    product_id: str,
    category_id: str,
    title: str | None,
    description_html: str | None,
    main_images: Sequence[Mapping[str, Any]] | None,
    *,
    timeout_seconds: float | None = None,
    clock: Callable[[], str] = _now_iso,
) -> DraftScore:
    """Ask TikTok to diagnose the draft and wait; ``not_read`` on any failure or timeout."""
    return start_listing_draft_score(
        resources,
        product_id,
        category_id,
        title,
        description_html,
        main_images,
        budget_seconds=timeout_seconds,
        clock=clock,
    ).wait()


def start_confirmed_listing_score(
    resources: object, product_id: str, body: Mapping[str, Any]
) -> PendingDraftScore | None:
    """The write path's one call: start scoring the edit body about to be sent, or ``None``
    (skipped) when the bundle is not the writable sandbox's -- a production write bundle
    is not allowed this endpoint, and a read bundle (the reviewer's masked pin) never
    reaches a write. Collect with ``.wait()`` after the write."""
    if not isinstance(resources, SandboxWriteResources):
        return None
    category_id = body.get("category_id")
    if not isinstance(category_id, str) or not category_id:
        return PendingDraftScore(None, 0.0, 0.0, time.monotonic, _now_iso)
    images = body.get("main_images")
    return start_listing_draft_score(
        resources,
        product_id,
        category_id,
        body.get("title"),
        body.get("description"),
        images if isinstance(images, list) else None,
    )


def stored_draft_score(outcome: Mapping[str, Any]) -> DraftScore | None:
    """The :class:`DraftScore` stored on a listing edit's ledger outcome, if any."""
    raw = outcome.get("draft_score")
    if not isinstance(raw, Mapping):
        return None
    try:
        return DraftScore.model_validate(dict(raw))
    except ValueError:
        return None


__all__ = [
    "DRAFT_SCORE_BUDGET_SECONDS",
    "OPTIMIZATION_FIELDS",
    "STATUS_NOT_READ",
    "STATUS_SCORED",
    "DraftScore",
    "PendingDraftScore",
    "parse_draft_codes",
    "score_listing_draft",
    "start_confirmed_listing_score",
    "start_listing_draft_score",
    "stored_draft_score",
]
