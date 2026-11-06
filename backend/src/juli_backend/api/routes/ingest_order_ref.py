"""``GET /v1/ingest/order-ref-key`` -- the shop's ``order_ref`` key for the Juli Connector.

The Connector's affiliate reader (conversion report, Connector 0.3.6) replaces each Shopee order
id by ``order_ref`` (``services/ingest/order_ref.py``) before anything leaves the browser, with
the SAME per-shop key the Ops order upload uses -- otherwise its lines could not mark the order
export's. Ingest-token auth like the Connector's other calls: the token names exactly one shop, so
it only ever gets that shop's key. Same answer shape and ``Cache-Control: no-store`` as the Ops
endpoint; 503 ``order_ref_key_not_configured`` when the master key is missing. The key is never
logged.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response

from juli_backend.api.routes.ingest import get_ingest_principal
from juli_backend.repositories import utc_now_naive
from juli_backend.services import ingest as ingest_service
from juli_backend.services.ingest import order_ref

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.get("/order-ref-key")
async def get_order_ref_key(
    response: Response,
    principal: ingest_service.IngestPrincipal = Depends(get_ingest_principal),
) -> dict[str, Any]:
    if principal.platform != "shopee":
        raise HTTPException(status_code=403, detail={"code": "platform_not_allowed"})
    try:
        issued = order_ref.issue(principal.shop_id, utc_now_naive())
    except order_ref.OrderRefKeyUnavailable:
        raise HTTPException(
            status_code=503, detail={"code": "order_ref_key_not_configured"}
        ) from None
    logger.info(
        "ingest_order_ref_key_issued",
        extra={
            "shop_id": str(principal.shop_id),
            "token_id": str(principal.token_id),
            "key_version": issued.key_version,
        },
    )
    response.headers["Cache-Control"] = "no-store"
    return {
        "order_ref_key": issued.key_hex,
        "algorithm": issued.algorithm,
        "key_version": issued.key_version,
        "expires_at": issued.expires_at.isoformat() + "Z",
    }
