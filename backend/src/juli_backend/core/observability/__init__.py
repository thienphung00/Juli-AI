"""Observability primitives — structured logging and request correlation (#902)."""

from juli_backend.core.observability.logging import (
    CORRELATION_ID_HEADER,
    JsonFormatter,
    coerce_correlation_id,
    configure_logging,
    get_client_address,
    get_correlation_id,
    new_correlation_id,
    reset_client_address,
    reset_correlation_id,
    set_client_address,
    set_correlation_id,
)

__all__ = [
    "CORRELATION_ID_HEADER",
    "JsonFormatter",
    "coerce_correlation_id",
    "configure_logging",
    "get_client_address",
    "get_correlation_id",
    "new_correlation_id",
    "reset_client_address",
    "reset_correlation_id",
    "set_client_address",
    "set_correlation_id",
]
