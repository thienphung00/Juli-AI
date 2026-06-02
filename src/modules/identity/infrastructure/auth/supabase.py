import logging

import httpx

from src.modules.identity.infrastructure.auth.exceptions import Unauthorized

logger = logging.getLogger(__name__)


class SupabaseAuth:
    """Thin wrapper around Supabase Auth REST API for phone-OTP login."""

    def __init__(
        self,
        supabase_url: str,
        anon_key: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = f"{supabase_url.rstrip('/')}/auth/v1"
        self._anon_key = anon_key
        self._client = client or httpx.AsyncClient()

    async def send_otp(self, phone: str) -> None:
        resp = await self._client.post(
            f"{self._base_url}/otp",
            json={"phone": phone},
            headers={"apikey": self._anon_key, "Content-Type": "application/json"},
        )
        if resp.status_code >= 400:
            logger.warning("otp_send_failed", extra={"phone": phone[:6] + "***"})
            raise Unauthorized(f"Failed to send OTP: {resp.text}")

    async def verify_otp(self, phone: str, token: str) -> dict:
        resp = await self._client.post(
            f"{self._base_url}/token",
            params={"grant_type": "otp"},
            json={"phone": phone, "token": token},
            headers={"apikey": self._anon_key, "Content-Type": "application/json"},
        )
        if resp.status_code >= 400:
            logger.warning("otp_verify_failed", extra={"phone": phone[:6] + "***"})
            raise Unauthorized(f"OTP verification failed: {resp.text}")

        data = resp.json()
        if "access_token" not in data:
            raise Unauthorized("No access token in response")
        return data

    async def close(self) -> None:
        await self._client.aclose()
