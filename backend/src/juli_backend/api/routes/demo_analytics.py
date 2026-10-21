"""``GET /v1/demo/analytics`` -- RETIRED (fast track P61-D, owner decision D72.5, 2026-10-21).

This was the public, unauthenticated masked KPI envelope of one server-bound
reference shop (#531, ADR-094 display binding). apps/demo stopped reading it
(pages use ``/v1/demo/analysis``), and keeping it fed cost an hourly recompute
plus a daily top-up of that one shop -- Supabase egress the free tier no longer
covers (D72). The route, its beats (``mock-analytics-hourly-reconcile``,
``analytics-backfill-topup``) and its ``DEMO_REFERENCE_SHOP_ID`` read are gone.

It answers **410 Gone** rather than 404 because cached copies of the old demo
bundle, the disabled uptime probe and anyone's bookmark may still call it: 410
says "deliberately removed" and costs no database or Redis access. Delete this
module once its access log shows no callers.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/demo", tags=["demo"])

RETIRED_DETAIL = "GET /v1/demo/analytics was retired on 2026-10-21; use /v1/demo/analysis."


@router.get("/analytics", status_code=status.HTTP_410_GONE, response_model=None)
async def get_demo_analytics() -> JSONResponse:
    """Retired: always 410 Gone, no database or cache access."""
    return JSONResponse(status_code=status.HTTP_410_GONE, content={"detail": RETIRED_DETAIL})
