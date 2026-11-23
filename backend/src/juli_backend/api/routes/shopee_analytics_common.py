"""What the Demo (seller) and Ops (viewer) Shopee analytics routes share: the query model, the
error mapping and the ``Shopee only`` check. The two route modules are thin skins over
``services/shopee_analytics/queries.py``; neither builds a number.

Responses never carry buyer data: the service reads ``shopee_order_lines``, which has no buyer
column, and the payloads aggregate (``order_ref`` never leaves the service). Ads figures carry
their placed-order label; every profit figure carries its assumed-cost share.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, Response

from juli_backend.services.shopee_analytics import (
    InvalidWindow,
    NoShopeeData,
    ProductNotFound,
    RowsNotMaterialized,
)

PeriodQ = Annotated[
    str, Query(pattern="^(7d|30d|90d|month|custom)$", description="7d | 30d | 90d | month | custom")
]
#: Tổng quan's "Cả kế hoạch" adds ``plan``: the running cards' span (channel-split only)
PlanPeriodQ = Annotated[
    str,
    Query(
        pattern="^(7d|30d|90d|month|custom|plan)$",
        description="7d | 30d | 90d | month | custom | plan",
    ),
]
MonthQ = Annotated[
    str | None, Query(pattern=r"^\d{4}-\d{2}$", description="YYYY-MM with period=month")
]
DateQ = Annotated[date | None, Query()]


NO_DATA_BY_PLATFORM: dict[str, dict[str, str]] = {
    "shopee": {"code": "no_shopee_data", "message": "Shop chưa có dữ liệu Shopee."},
    "tiktok": {"code": "no_tiktok_data", "message": "Shop chưa có dữ liệu TikTok Shop."},
}


_ADS_FIGURES = (
    "spend",
    "gmv_placed",
    "direct_gmv_placed",
    "orders_placed",
    "roas",
    "roas_broad",
    "roas_direct",
    "spend_per_day",
)


#: W3-Q5: without ads spend there is no profit or margin (never a before-ads figure, never 0)
_PROFIT_FIGURES = frozenset(
    {
        "profit",
        "margin",
        "margin_pct",
        "product_profit",
        "ads_charged",
        "ads_total",
        "ads_unattributed",
        "ads_no_order_days",
        "ad_spend",
        "ads_spend",
        "ads_roas_placed",
        "cost_total",
        "cost_ads",
        "roi",
    }
)
_METRIC_CELLS = ("now", "prev", "change", "impact")


def _null_profit(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: None if k in _PROFIT_FIGURES and not isinstance(v, (dict, list)) else _null_profit(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_null_profit(v) for v in value]
    return value


def _null_margin_view(body: dict[str, Any]) -> None:
    """A metric-view of ``margin``: every cell is None."""
    for block in [body.get("total"), *body.get("channels", []), *body.get("products", [])]:
        if isinstance(block, dict):
            for key in _METRIC_CELLS:
                if key in block:
                    block[key] = None


def stamped(body: dict[str, Any], platform: str) -> dict[str, Any]:
    """The page builders write the platform's name where they build text (``platform`` argument);
    this sets the ``platform`` key and, for a platform without ads figures, the ads reason
    (null, never 0). A Shopee payload is returned as it is."""
    from juli_backend.services.metrics.registry import Platform, source_reason

    if platform == "shopee":
        return body
    if "platform" in body:
        body["platform"] = platform
    reason = source_reason(Platform(platform), "ads")
    if reason is not None:
        gaps = {"ads": reason, "profit": reason, "margin": reason}
        body["unavailable"] = {**body.get("unavailable", {}), **gaps}
        body.update(_null_profit({k: v for k, v in body.items() if k != "unavailable"}))
        if body.get("metric") == "margin":
            _null_margin_view(body)
        blocks = [
            body.get("ads"),
            *(p.get("ads") for p in body.get("products", []) if isinstance(p, dict)),
        ]
        for ads in blocks:
            if isinstance(ads, dict):
                for key in _ADS_FIGURES:
                    if key in ads:
                        ads[key] = None
    return body


def refusal(exc: Exception, platform: str = "shopee") -> HTTPException:
    if isinstance(exc, RowsNotMaterialized):
        # P99b: a window without stored daily rows shows this state, never numbers
        return HTTPException(status.HTTP_409_CONFLICT, detail=exc.json())
    if isinstance(exc, NoShopeeData):
        return HTTPException(
            status.HTTP_409_CONFLICT,
            detail=dict(NO_DATA_BY_PLATFORM.get(platform, NO_DATA_BY_PLATFORM["shopee"])),
        )
    if isinstance(exc, ProductNotFound):
        return HTTPException(
            status.HTTP_404_NOT_FOUND, detail={"code": "product_not_found", "message": str(exc)}
        )
    if isinstance(exc, InvalidWindow):
        return HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_period", "message": str(exc)},
        )
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": "invalid_request", "message": str(exc)},
    )


async def rows_missing_response(request: Request, exc: Exception) -> JSONResponse:
    """P99b: any Shopee screen (Tổng quan, Sản phẩm, xếp hạng, Luồng, Tự tạo, Kế hoạch) whose
    window has data days without stored daily rows answers 409 ``rows_not_materialized`` with the
    Vietnamese message -- never figures from the raw tables."""
    body = exc.json() if isinstance(exc, RowsNotMaterialized) else {"code": "rows_not_materialized"}
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": body})


def install_rows_missing_handler(app: FastAPI) -> None:
    app.add_exception_handler(RowsNotMaterialized, rows_missing_response)


REFUSALS = (RowsNotMaterialized, NoShopeeData, ProductNotFound, InvalidWindow, ValueError)


def window_args(
    period: str, month: str | None, start: date | None, end: date | None, as_of: date | None
) -> dict[str, Any]:
    return {"period": period, "month": month, "start": start, "end": end, "as_of": as_of}


XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def xlsx_response(name: str, data: bytes) -> Response:
    """A workbook as a download (the file name is URL-encoded, RFC 5987)."""
    return Response(
        data,
        media_type=XLSX_TYPE,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )


async def export_tong_quan(session: Any, shop_id: Any, shop_name: str, **args: Any) -> Response:
    """The Tổng quan workbook of the period / level the screen shows (a pure read)."""
    from juli_backend.services.exports import collect, tong_quan_xlsx

    data = await collect.collect_tong_quan(
        session, shop_id, shop_name=shop_name, now=datetime.now(UTC), **args
    )
    return xlsx_response(tong_quan_xlsx.file_name(data), tong_quan_xlsx.build_bytes(data))


async def export_ke_hoach(
    session: Any,
    shop_id: Any,
    shop_name: str,
    start: date | None = None,
    end: date | None = None,
) -> Response:
    """The Kế hoạch workbook of ``start..end`` (default: the newest data month to date; a pure
    read)."""
    from juli_backend.services.exports import collect, ke_hoach_xlsx

    data = await collect.collect_ke_hoach(
        session, shop_id, shop_name=shop_name, now=datetime.now(UTC), start=start, end=end
    )
    return xlsx_response(ke_hoach_xlsx.file_name(data), ke_hoach_xlsx.build_bytes(data))


async def shop_refs(session: Any, user_id: Any) -> list[Any]:
    """The shops of the "Tất cả shop" gate: every shop the user can access (the membership-aware
    read ``GET /v1/shops`` and ``get_active_shop`` use), oldest first."""
    from juli_backend.database import ShopsRepo
    from juli_backend.services.exports import collect

    shops = await ShopsRepo(session).list_for_authorization(user_id)
    shops.sort(key=lambda s: (s.created_at, str(s.id)))
    return [collect.ShopRef(s.id, s.shop_name, s.platform) for s in shops]


async def export_tong_quan_all(session: Any, user_id: Any, **args: Any) -> Response:
    """The Tổng quan workbook of every shop the user can access: a column per shop and a Tổng."""
    from juli_backend.services.exports import collect, tong_quan_xlsx

    datas = await collect.collect_tong_quan_shops(
        session, await shop_refs(session, user_id), user_id=user_id, now=datetime.now(UTC), **args
    )
    return xlsx_response(
        tong_quan_xlsx.file_name_multi(datas), tong_quan_xlsx.build_multi_bytes(datas)
    )


async def export_ke_hoach_all(
    session: Any, user_id: Any, start: date | None, end: date | None
) -> Response:
    """The Kế hoạch workbook of every shop the user can access (one date range)."""
    from juli_backend.services.exports import collect, ke_hoach_xlsx
    from juli_backend.services.shopee_analytics import service

    shops = await shop_refs(session, user_id)
    if start is None or end is None:
        first = next((s for s in shops if s.platform == "shopee"), None)
        window = None if first is None else await service.resolve(session, first.id)
        if window is None:
            raise ValueError("no data")
        end = end or window.end
        start = start or end.replace(day=1)
    data = await collect.collect_ke_hoach_shops(
        session, shops, user_id=user_id, now=datetime.now(UTC), start=start, end=end
    )
    return xlsx_response(ke_hoach_xlsx.file_name(data), ke_hoach_xlsx.build_bytes(data))
