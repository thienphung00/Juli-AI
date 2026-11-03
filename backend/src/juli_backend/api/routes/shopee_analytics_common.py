"""What the Demo (seller) and Ops (viewer) Shopee analytics routes share: the query model, the
error mapping and the ``Shopee only`` check. The two route modules are thin skins over
``services/shopee_analytics/queries.py``; neither builds a number.

Responses never carry buyer data: the service reads ``shopee_order_lines``, which has no buyer
column, and the payloads aggregate (``order_ref`` never leaves the service). Ads figures carry
their placed-order label; every profit figure carries its assumed-cost share.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import HTTPException, Query, status

from juli_backend.services.shopee_analytics import InvalidWindow, NoShopeeData, ProductNotFound

PeriodQ = Annotated[
    str, Query(pattern="^(7d|30d|90d|month|custom)$", description="7d | 30d | 90d | month | custom")
]
MonthQ = Annotated[
    str | None, Query(pattern=r"^\d{4}-\d{2}$", description="YYYY-MM with period=month")
]
DateQ = Annotated[date | None, Query()]


def refusal(exc: Exception) -> HTTPException:
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


REFUSALS = (NoShopeeData, ProductNotFound, InvalidWindow, ValueError)


def window_args(
    period: str, month: str | None, start: date | None, end: date | None, as_of: date | None
) -> dict[str, Any]:
    return {"period": period, "month": month, "start": start, "end": end, "as_of": as_of}
