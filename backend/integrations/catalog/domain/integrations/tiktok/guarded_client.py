"""Guarded TikTokClient wrapper — applies transport guards before signing."""

from __future__ import annotations

from typing import Any, Optional, TypeVar, overload

from pydantic import BaseModel

from backend.integrations.catalog.domain.integrations.tiktok.client import TikTokClient
from backend.integrations.catalog.domain.integrations.tiktok.guards import (
    TransportGuard,
    log_outbound_request,
)
from backend.integrations.catalog.domain.integrations.tiktok.capabilities import MerchantCapability

T = TypeVar("T", bound=BaseModel)


class GuardedTikTokClient(TikTokClient):
    """TikTokClient that enforces capability transport guards before signing."""

    def __init__(
        self,
        client: TikTokClient,
        *,
        guard: TransportGuard,
        capability: MerchantCapability,
        merchant_auth_id: str,
    ) -> None:
        super().__init__(
            app_key=client._app_key,
            app_secret=client._app_secret,
            access_token=client._access_token,
            base_url=client._base_url,
            shop_cipher=client._shop_cipher,
            timeout=client._timeout,
        )
        self._session = client._session
        self._guard = guard
        self._capability = capability
        self._merchant_auth_id = merchant_auth_id

    @overload
    def get(
        self,
        path: str,
        params: Optional[dict[str, str]] = None,
        *,
        response_model: type[T],
    ) -> T: ...

    @overload
    def get(
        self,
        path: str,
        params: Optional[dict[str, str]] = None,
        *,
        response_model: None = None,
    ) -> dict[str, Any]: ...

    def get(
        self,
        path: str,
        params: Optional[dict[str, str]] = None,
        *,
        response_model: Optional[type[BaseModel]] = None,
    ) -> dict[str, Any] | BaseModel:
        self._guard.assert_allowed("GET", path)
        log_outbound_request(
            capability=self._capability,
            merchant_auth_id=self._merchant_auth_id,
            method="GET",
            path=path,
            shop_cipher=self._shop_cipher,
        )
        return super().get(path, params=params, response_model=response_model)

    @overload
    def post(
        self,
        path: str,
        body: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, str]] = None,
        *,
        response_model: type[T],
    ) -> T: ...

    @overload
    def post(
        self,
        path: str,
        body: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, str]] = None,
        *,
        response_model: None = None,
    ) -> dict[str, Any]: ...

    def post(
        self,
        path: str,
        body: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, str]] = None,
        *,
        response_model: Optional[type[BaseModel]] = None,
    ) -> dict[str, Any] | BaseModel:
        self._guard.assert_allowed("POST", path)
        log_outbound_request(
            capability=self._capability,
            merchant_auth_id=self._merchant_auth_id,
            method="POST",
            path=path,
            shop_cipher=self._shop_cipher,
        )
        return super().post(path, body=body, params=params, response_model=response_model)
