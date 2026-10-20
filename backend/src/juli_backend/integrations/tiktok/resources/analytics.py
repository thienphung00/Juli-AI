"""TikTok Shop Analytics resource — thin GET wrappers (contract-collection A-28, A-31–A-39).

Date-range queries use Partner API identifier catalog spellings:
``start_date_ge``, ``end_date_lt``, ``sku_id``, ``product_id``, ``date``, ``time_slot``.
LIVE A-26/A-27 remain deferred; A-28 list is wired for poll ETL (#425); A-29
overview is wired for historical backfill (#468).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from typing import Any

import requests

from juli_backend.integrations.tiktok.client import TikTokClient
from juli_backend.integrations.tiktok.constants import (
    ANALYTICS_API_VERSION,
    ANALYTICS_BESTSELLING_API_VERSION,
    ANALYTICS_BESTSELLING_PRODUCTS_PATH,
    ANALYTICS_BESTSELLING_VIDEOS_PATH,
    ANALYTICS_LIVE_OVERVIEW_PERFORMANCE_PATH,
    ANALYTICS_LIVE_PERFORMANCE_LIST_PATH,
    ANALYTICS_LIVE_PRODUCTS_API_VERSION,
    ANALYTICS_SHOP_PERFORMANCE_PATH,
    ANALYTICS_SHOP_PERFORMANCE_PER_HOUR_API_VERSION,
    ANALYTICS_SHOP_PRODUCTS_LIST_API_VERSION,
    ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH,
    ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH,
    ANALYTICS_SHOP_VIDEOS_BATCH_PERFORMANCE_PATH,
    ANALYTICS_SHOP_VIDEOS_LIST_API_VERSION,
    ANALYTICS_SHOP_VIDEOS_PERFORMANCE_PATH,
    ANALYTICS_VIDEO_DETAILS_API_VERSION,
    ANALYTICS_VIDEO_DETAILS_LEGACY_API_VERSION,
    ANALYTICS_VIDEO_DETAILS_LEGACY_RETIREMENT,
    ANALYTICS_VIDEO_DETAILS_MAX_IDS,
    analytics_shop_live_products_performance_path,
    analytics_shop_performance_per_hour_path,
    analytics_shop_product_performance_path,
    analytics_shop_sku_performance_path,
    analytics_shop_video_performance_path,
    analytics_shop_video_products_performance_path,
)
from juli_backend.integrations.tiktok.exceptions import PermissionDeniedError, TikTokAPIError
from juli_backend.integrations.tiktok.resources import strip_nones

logger = logging.getLogger(__name__)

#: TikTok's "Access denied ... do not contain the required access scope" (common
#: error codes page); Juli's exception map only types 100003 as PermissionDeniedError.
SCOPE_DENIED_CODE = 105005
LEGACY_VIDEO_DETAILS_RETIREMENT = date.fromisoformat(ANALYTICS_VIDEO_DETAILS_LEGACY_RETIREMENT)
FALLBACK_EVENT = "tiktok_endpoint_fallback"


class VideoPerformanceError(TikTokAPIError):
    """The batch details call answered, but not for this video (``videos[].error``)."""


def _today() -> date:
    return datetime.now(UTC).date()


class _OnceFlag:
    """Process-wide "already logged" flag for the fallback warning."""

    def __init__(self) -> None:
        self._done = False
        self._lock = threading.Lock()

    def first(self) -> bool:
        with self._lock:
            done, self._done = self._done, True
            return not done

    def reset(self) -> None:
        with self._lock:
            self._done = False


VIDEO_DETAILS_FALLBACK_LOGGED = _OnceFlag()


def is_scope_refusal(exc: BaseException) -> bool:
    """A refusal that means "this app/token may not call that endpoint" (not a bad call)."""
    if isinstance(exc, PermissionDeniedError):
        return True
    if isinstance(exc, TikTokAPIError):
        return exc.code == SCOPE_DENIED_CODE
    if isinstance(exc, requests.HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        return status in (403, 404)
    return False


def _error_code(raw: Any) -> int:
    try:
        return int(str(raw))
    except ValueError:
        return 0


def legacy_video_details(batch: dict[str, Any], video_id: str) -> dict[str, Any]:
    """One video of a batch response, shaped like the 202509 single-video ``data``.

    Field mapping (changelog 2026-09-28): ``data.videos[].performance`` ->
    ``data.performance`` (intervals, sales.overall, traffic, viewer_profile keep
    their names); ``latest_available_date`` stays at the top. The batch API has no
    ``sales.breakdowns`` (product split moved to Get Shop Video Product Performance
    List); Juli never read it. Raises :class:`VideoPerformanceError` for a video the
    batch could not answer.
    """
    for row in batch.get("videos") or []:
        if not isinstance(row, dict) or str(row.get("video_id") or "") != str(video_id):
            continue
        error = row.get("error")
        if isinstance(error, dict) and (error.get("code") or error.get("message")):
            raise VideoPerformanceError(
                code=_error_code(error.get("code")),
                message=str(error.get("message") or "video performance unavailable"),
            )
        out: dict[str, Any] = {"performance": row.get("performance") or {}}
        if "latest_available_date" in batch:
            out["latest_available_date"] = batch["latest_available_date"]
        return out
    raise VideoPerformanceError(code=0, message=f"video {video_id} missing from batch response")


class AnalyticsResource:
    """Fetch shop / product / SKU analytics with date windows and pagination."""

    def __init__(self, client: TikTokClient) -> None:
        self._client = client

    def list_sku_performance(
        self,
        *,
        start_date_ge: str,
        end_date_lt: str,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """A-32 Get Shop SKU Performance List."""
        params = strip_nones(
            {
                "version": ANALYTICS_API_VERSION,
                "start_date_ge": start_date_ge,
                "end_date_lt": end_date_lt,
                "page_size": str(page_size) if page_size is not None else None,
                "page_token": page_token,
            }
        )
        return self._client.get(ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH, params=params)

    def list_sku_performance_all(
        self,
        *,
        start_date_ge: str,
        end_date_lt: str,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        """A-32 paginated SKU performance list."""
        params = {
            "version": ANALYTICS_API_VERSION,
            "start_date_ge": start_date_ge,
            "end_date_lt": end_date_lt,
        }
        return self._client.get_all_pages_get(
            ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH,
            params=params,
            items_key="skus",
            page_size=page_size,
        )

    def get_sku_performance(
        self,
        *,
        sku_id: str,
        start_date_ge: str,
        end_date_lt: str,
    ) -> dict[str, Any]:
        """A-31 Get Shop SKU Performance Detail."""
        params = {
            "version": ANALYTICS_API_VERSION,
            "start_date_ge": start_date_ge,
            "end_date_lt": end_date_lt,
        }
        return self._client.get(
            analytics_shop_sku_performance_path(sku_id),
            params=params,
        )

    def list_product_performance(
        self,
        *,
        start_date_ge: str,
        end_date_lt: str,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """A-34 Get Shop Product Performance List."""
        params = strip_nones(
            {
                "version": ANALYTICS_SHOP_PRODUCTS_LIST_API_VERSION,
                "start_date_ge": start_date_ge,
                "end_date_lt": end_date_lt,
                "page_size": str(page_size) if page_size is not None else None,
                "page_token": page_token,
            }
        )
        return self._client.get(ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH, params=params)

    def list_product_performance_all(
        self,
        *,
        start_date_ge: str,
        end_date_lt: str,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        """A-34 paginated product performance list."""
        params = {
            "version": ANALYTICS_SHOP_PRODUCTS_LIST_API_VERSION,
            "start_date_ge": start_date_ge,
            "end_date_lt": end_date_lt,
        }
        return self._client.get_all_pages_get(
            ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH,
            params=params,
            items_key="products",
            page_size=page_size,
        )

    def get_product_performance(
        self,
        *,
        product_id: str,
        start_date_ge: str,
        end_date_lt: str,
    ) -> dict[str, Any]:
        """A-33 Get Shop Product Performance Detail."""
        params = {
            "version": ANALYTICS_API_VERSION,
            "start_date_ge": start_date_ge,
            "end_date_lt": end_date_lt,
        }
        return self._client.get(
            analytics_shop_product_performance_path(product_id),
            params=params,
        )

    def get_shop_performance(
        self,
        *,
        start_date_ge: str,
        end_date_lt: str,
    ) -> dict[str, Any]:
        """A-36 Get Shop Performance."""
        params = {
            "version": ANALYTICS_API_VERSION,
            "start_date_ge": start_date_ge,
            "end_date_lt": end_date_lt,
        }
        return self._client.get(ANALYTICS_SHOP_PERFORMANCE_PATH, params=params)

    def get_shop_performance_per_hour(self, *, date: str) -> dict[str, Any]:
        """A-37 Get Shop Performance Per Hour (`date` = YYYY-MM-DD)."""
        params = {"version": ANALYTICS_SHOP_PERFORMANCE_PER_HOUR_API_VERSION}
        return self._client.get(
            analytics_shop_performance_per_hour_path(date),
            params=params,
        )

    def get_bestselling_products(
        self,
        *,
        date: str,
        time_slot: str = "1D",
    ) -> dict[str, Any]:
        """A-38 Get Bestselling Products."""
        params = {
            "version": ANALYTICS_BESTSELLING_API_VERSION,
            "date": date,
            "time_slot": time_slot,
        }
        return self._client.get(ANALYTICS_BESTSELLING_PRODUCTS_PATH, params=params)

    def get_bestselling_videos(
        self,
        *,
        date: str,
        time_slot: str = "1D",
    ) -> dict[str, Any]:
        """A-39 Get Bestselling Videos."""
        params = {
            "version": ANALYTICS_BESTSELLING_API_VERSION,
            "date": date,
            "time_slot": time_slot,
        }
        return self._client.get(ANALYTICS_BESTSELLING_VIDEOS_PATH, params=params)

    def get_live_overview_performance(
        self,
        *,
        start_date_ge: str,
        end_date_lt: str,
    ) -> dict[str, Any]:
        """A-29 Get Shop LIVE Performance Overview."""
        params = {
            "version": ANALYTICS_API_VERSION,
            "start_date_ge": start_date_ge,
            "end_date_lt": end_date_lt,
        }
        return self._client.get(ANALYTICS_LIVE_OVERVIEW_PERFORMANCE_PATH, params=params)

    def list_live_performance(
        self,
        *,
        start_date_ge: str,
        end_date_lt: str,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """A-28 Get Shop LIVE Performance List."""
        params = strip_nones(
            {
                "version": ANALYTICS_API_VERSION,
                "start_date_ge": start_date_ge,
                "end_date_lt": end_date_lt,
                "page_size": str(page_size) if page_size is not None else None,
                "page_token": page_token,
            }
        )
        return self._client.get(ANALYTICS_LIVE_PERFORMANCE_LIST_PATH, params=params)

    def list_live_performance_all(
        self,
        *,
        start_date_ge: str,
        end_date_lt: str,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        """A-28 paginated LIVE session list."""
        params = {
            "version": ANALYTICS_API_VERSION,
            "start_date_ge": start_date_ge,
            "end_date_lt": end_date_lt,
        }
        return self._client.get_all_pages_get(
            ANALYTICS_LIVE_PERFORMANCE_LIST_PATH,
            params=params,
            items_key="live_stream_sessions",
            page_size=page_size,
        )

    def list_video_performance_all(
        self,
        *,
        start_date_ge: str,
        end_date_lt: str,
        sort_field: str = "gmv",
        account_type: str | None = None,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """Get Shop Video Performance List, paginated; each video lists its products.

        ``account_type`` narrows to ``OFFICIAL_ACCOUNTS``, ``MARKETING_ACCOUNTS`` or
        ``AFFILIATE_ACCOUNTS``; omitted, TikTok returns every account (``ALL``).
        """
        params = strip_nones(
            {
                "version": ANALYTICS_SHOP_VIDEOS_LIST_API_VERSION,
                "start_date_ge": start_date_ge,
                "end_date_lt": end_date_lt,
                "sort_field": sort_field,
                "sort_order": "DESC",
                "account_type": account_type,
            }
        )
        return self._client.get_all_pages_get(
            ANALYTICS_SHOP_VIDEOS_PERFORMANCE_PATH,
            params=params,
            items_key="videos",
            page_size=page_size,
        )

    def get_video_products_performance(
        self,
        *,
        video_id: str,
        start_date_ge: str,
        end_date_lt: str,
    ) -> dict[str, Any]:
        """Get Shop Video Product Performance List: per-product GMV and units for one video."""
        params = {
            "version": ANALYTICS_API_VERSION,
            "start_date_ge": start_date_ge,
            "end_date_lt": end_date_lt,
            "page_size": "100",
        }
        return self._client.get(
            analytics_shop_video_products_performance_path(video_id), params=params
        )

    def get_videos_performance(
        self,
        *,
        video_ids: Sequence[str],
        start_date_ge: str,
        end_date_lt: str,
        granularity: str = "1D",
    ) -> dict[str, Any]:
        """Get Shop Videos Performance Details 202609: up to 500 videos per call.

        Returns the raw ``data`` (``latest_available_date``, ``videos[]`` with
        ``video_id``, ``performance``, ``video``, ``error``). ``video_ids`` is a
        ``[]int`` query parameter, sent as in the doc's sample request:
        ``video_ids=[7523456789012345678]``.
        """
        ids = [str(v) for v in video_ids]
        if not ids or len(ids) > ANALYTICS_VIDEO_DETAILS_MAX_IDS:
            raise ValueError(f"video_ids must hold 1..{ANALYTICS_VIDEO_DETAILS_MAX_IDS} ids")
        params = {
            "version": ANALYTICS_VIDEO_DETAILS_API_VERSION,
            "video_ids": "[" + ",".join(ids) + "]",
            "start_date_ge": start_date_ge,
            "end_date_lt": end_date_lt,
            "granularity": granularity,
        }
        return self._client.get(ANALYTICS_SHOP_VIDEOS_BATCH_PERFORMANCE_PATH, params=params)

    def get_video_performance_legacy(
        self,
        *,
        video_id: str,
        start_date_ge: str,
        end_date_lt: str,
        granularity: str = "1D",
    ) -> dict[str, Any]:
        """Get Shop Video Performance Details 202509 (retiring no later than 2026-12-28)."""
        params = {
            "version": ANALYTICS_VIDEO_DETAILS_LEGACY_API_VERSION,
            "start_date_ge": start_date_ge,
            "end_date_lt": end_date_lt,
            "granularity": granularity,
        }
        return self._client.get(analytics_shop_video_performance_path(video_id), params=params)

    def get_video_performance(
        self,
        *,
        video_id: str,
        start_date_ge: str,
        end_date_lt: str,
        granularity: str = "1D",
        today: Callable[[], date] = _today,
    ) -> dict[str, Any]:
        """One video's sales and traffic per interval, in the 202509 details shape.

        ``granularity="1D"`` returns one interval per day (``start_date``/``end_date``),
        each with ``sales.overall`` (product impressions, clicks, GMV, items sold) and
        ``traffic`` (views). Reads the batch API (:meth:`get_videos_performance`) and
        reshapes the video's row (:func:`legacy_video_details`). If the batch API is
        refused for scope/permission, falls back to the 202509 single-video API until
        its retirement date, logging ``tiktok_endpoint_fallback`` once per process;
        after that date the refusal propagates.
        """
        try:
            batch = self.get_videos_performance(
                video_ids=[video_id],
                start_date_ge=start_date_ge,
                end_date_lt=end_date_lt,
                granularity=granularity,
            )
        except Exception as exc:
            if not is_scope_refusal(exc) or today() > LEGACY_VIDEO_DETAILS_RETIREMENT:
                raise
            if VIDEO_DETAILS_FALLBACK_LOGGED.first():
                logger.warning(
                    FALLBACK_EVENT,
                    extra={
                        "event": FALLBACK_EVENT,
                        "endpoint": ANALYTICS_SHOP_VIDEOS_BATCH_PERFORMANCE_PATH,
                        "fallback_endpoint": analytics_shop_video_performance_path("{video_id}"),
                        "fallback_until": ANALYTICS_VIDEO_DETAILS_LEGACY_RETIREMENT,
                        "error_class": type(exc).__name__,
                        "error_code": getattr(exc, "code", None),
                        "error_message": str(exc)[:200],
                    },
                )
            return self.get_video_performance_legacy(
                video_id=video_id,
                start_date_ge=start_date_ge,
                end_date_lt=end_date_lt,
                granularity=granularity,
            )
        return legacy_video_details(batch, video_id)

    def get_live_products_performance(self, *, live_id: str) -> dict[str, Any]:
        """Get Shop LIVE Products Performance List: per-product traffic and sales of one session."""
        params = {"version": ANALYTICS_LIVE_PRODUCTS_API_VERSION}
        return self._client.get(
            analytics_shop_live_products_performance_path(live_id), params=params
        )
