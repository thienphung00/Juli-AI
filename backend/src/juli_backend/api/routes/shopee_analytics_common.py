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


def refusal(exc: Exception) -> HTTPException:
    if isinstance(exc, RowsNotMaterialized):
        # P99b: a window without stored daily rows shows this state, never numbers
        return HTTPException(status.HTTP_409_CONFLICT, detail=exc.json())
    if isinstance(exc, NoShopeeData):
        return HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "no_shopee_data", "message": "Shop chưa có dữ liệu Shopee."},
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
    session: Any, shop_id: Any, shop_name: str, month: str | None
) -> Response:
    """The Kế hoạch workbook of ``month`` (a pure read)."""
    from juli_backend.services.exports import collect, ke_hoach_xlsx

    data = await collect.collect_ke_hoach(
        session, shop_id, shop_name=shop_name, now=datetime.now(UTC), month=month
    )
    return xlsx_response(ke_hoach_xlsx.file_name(data), ke_hoach_xlsx.build_bytes(data))
