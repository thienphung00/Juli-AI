"""Runtime transport guards for TikTok Shop capability-separated clients."""

from __future__ import annotations

import logging
from typing import Protocol

from juli_backend.integrations.tiktok.capabilities import (
    MerchantCapability,
    is_production_read_allowed,
    is_sandbox_write_allowed,
)
from juli_backend.integrations.tiktok.exceptions import TransportGuardError

logger = logging.getLogger(__name__)


class TransportGuard(Protocol):
    """Protocol for pre-sign transport allowlist checks."""

    capability: MerchantCapability

    def assert_allowed(self, method: str, path: str) -> None:
        """Raise TransportGuardError when method/path is not allowlisted."""


def redact_shop_identifier(shop_cipher: str | None) -> str:
    """Redact shop cipher for outbound audit logs."""
    if not shop_cipher:
        return "none"
    if len(shop_cipher) <= 8:
        return "REDACTED"
    return f"{shop_cipher[:4]}...{shop_cipher[-4:]}"


def log_outbound_request(
    *,
    capability: MerchantCapability,
    merchant_auth_id: str,
    method: str,
    path: str,
    shop_cipher: str | None,
) -> None:
    """Emit structured outbound metadata without secrets."""
    logger.info(
        "tiktok_outbound_request",
        extra={
            "capability": capability.value,
            "merchant_auth_id": merchant_auth_id,
            "method": method.upper(),
            "path": path,
            "shop_id_redacted": redact_shop_identifier(shop_cipher),
        },
    )


class ReadOnlyTransportGuard:
    """Allow GET and read-only POST search endpoints on production-read transport."""

    capability = MerchantCapability.PRODUCTION_READ

    def assert_allowed(self, method: str, path: str) -> None:
        if is_production_read_allowed(method, path):
            return
        raise TransportGuardError(
            capability=self.capability.value,
            method=method.upper(),
            path=path,
            message=(
                "Production-read transport rejected request before signing: "
                f"{method.upper()} {path}"
            ),
        )


class SandboxOnlyWriteGuard:
    """Restrict transport to sandbox write-validation allowlist."""

    capability = MerchantCapability.SANDBOX_WRITE

    def assert_allowed(self, method: str, path: str) -> None:
        if is_sandbox_write_allowed(method, path):
            return
        raise TransportGuardError(
            capability=self.capability.value,
            method=method.upper(),
            path=path,
            message=(
                "Sandbox write-validation transport rejected request before signing: "
                f"{method.upper()} {path}"
            ),
        )
