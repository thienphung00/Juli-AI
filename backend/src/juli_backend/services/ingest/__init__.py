"""The ingest gateway and Juli Connector pairing (fast track P24, D31.3 / D31.4).

- ``schemas`` -- the request body and one strict row model per dataset.
- ``mapping`` -- pure: platform rows → Juli streams / KPIs (Shopee L1 sources).
- ``gateway`` -- validate, store raw (dedup), upsert ``platform_daily_metrics``.
- ``pairing`` -- pairing codes, scoped ingest tokens (hashed, rotating, revocable).
- ``status`` -- last ingest per dataset and the extension's drift reports.
- ``rate_limit`` -- per-shop / per-client fixed windows.
- ``shops`` -- a Shopee shop for a Juli user (no Shopee OAuth yet).
"""

from juli_backend.services.ingest.gateway import IngestRejected, IngestResult, ingest
from juli_backend.services.ingest.mapping import (
    DATASETS,
    OVERLAY_STREAMS,
    SHOPEE_L1_TO_STREAM,
    STREAM_LABELS,
    dataset_spec,
)
from juli_backend.services.ingest.pairing import (
    PAIRING_CODE_TTL,
    ROTATION_GRACE,
    TOKEN_TTL,
    IngestPrincipal,
    IssuedCode,
    IssuedToken,
    PairingError,
    create_pairing_code,
    list_tokens,
    redeem_pairing_code,
    resolve_token,
    revoke_token,
    rotate_token,
)
from juli_backend.services.ingest.rate_limit import (
    InMemoryRateGate,
    RateDecision,
    get_ingest_rate_gate,
    pair_limit,
    set_ingest_rate_gate,
    shop_limit,
)
from juli_backend.services.ingest.schemas import (
    MAX_BODY_BYTES,
    DriftReport,
    IngestBody,
    PairRequest,
)
from juli_backend.services.ingest.shops import connect_shopee_shop
from juli_backend.services.ingest.status import dataset_status, report_drift

__all__ = [
    "DATASETS",
    "MAX_BODY_BYTES",
    "OVERLAY_STREAMS",
    "PAIRING_CODE_TTL",
    "ROTATION_GRACE",
    "SHOPEE_L1_TO_STREAM",
    "STREAM_LABELS",
    "TOKEN_TTL",
    "DriftReport",
    "InMemoryRateGate",
    "IngestBody",
    "IngestPrincipal",
    "IngestRejected",
    "IngestResult",
    "IssuedCode",
    "IssuedToken",
    "PairRequest",
    "PairingError",
    "RateDecision",
    "connect_shopee_shop",
    "create_pairing_code",
    "dataset_spec",
    "dataset_status",
    "get_ingest_rate_gate",
    "ingest",
    "list_tokens",
    "pair_limit",
    "redeem_pairing_code",
    "report_drift",
    "resolve_token",
    "revoke_token",
    "rotate_token",
    "set_ingest_rate_gate",
    "shop_limit",
]
