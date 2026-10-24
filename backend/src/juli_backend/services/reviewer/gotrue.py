"""Supabase Auth (GoTrue) admin calls for the reviewer provisioning command (P32-A).

Service-role only: creates / updates the reviewer's auth user with an e-mail +
password, ``email_confirm`` and the ``app_metadata`` mark the API gate reads
(``juli_role`` / ``juli_platform``), and bans / unbans it. Never called by the
API process. The password is passed through, never logged.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import httpx

#: "Banned until revoked": GoTrue takes a duration; ~100 years.
BAN_FOREVER = "876000h"
UNBAN = "none"
_PAGE = 1000
_MAX_PAGES = 50


class GoTrueError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuthUser:
    id: uuid.UUID
    email: str


def reviewer_app_metadata(platform: str) -> dict[str, str]:
    return {"juli_role": "reviewer", "juli_platform": platform}


class GoTrueAdmin:
    def __init__(
        self, supabase_url: str, service_role_key: str, *, client: httpx.Client | None = None
    ):
        if not supabase_url or not service_role_key:
            raise GoTrueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
        self._base = supabase_url.rstrip("/") + "/auth/v1/admin"
        self._headers = {"apikey": service_role_key, "Content-Type": "application/json"}
        # A legacy service_role key is a JWT and also goes in the Bearer header. Supabase's
        # newer secret keys (``sb_secret_…``) are not JWTs: sent as Bearer they get a 401, so
        # they travel in ``apikey`` only.
        if not service_role_key.startswith("sb_"):
            self._headers["Authorization"] = f"Bearer {service_role_key}"
        self._client = client or httpx.Client(timeout=20)

    def _call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = self._client.request(method, self._base + path, headers=self._headers, **kwargs)
        return response

    @staticmethod
    def _user(body: dict[str, Any]) -> AuthUser:
        user = body.get("user", body)
        return AuthUser(id=uuid.UUID(str(user["id"])), email=str(user.get("email", "")).lower())

    def find_by_email(self, email: str) -> AuthUser | None:
        wanted = email.strip().lower()
        for page in range(1, _MAX_PAGES + 1):
            response = self._call("GET", "/users", params={"page": page, "per_page": _PAGE})
            if response.status_code != 200:
                raise GoTrueError(f"list users failed: HTTP {response.status_code}")
            users = response.json().get("users", [])
            for user in users:
                if str(user.get("email", "")).lower() == wanted:
                    return self._user(user)
            if len(users) < _PAGE:
                return None
        return None

    def _post_user(self, email: str, password: str, platform: str) -> httpx.Response:
        body = {
            "email": email,
            "password": password,
            "email_confirm": True,
            "app_metadata": reviewer_app_metadata(platform),
        }
        return self._call("POST", "/users", json=body)

    def create(self, email: str, password: str, platform: str) -> AuthUser:
        """Create a NEW user (confirmed, marked); never takes over an existing one (P67)."""
        response = self._post_user(email, password, platform)
        if response.status_code not in (200, 201):
            raise GoTrueError(f"create user failed: HTTP {response.status_code}")
        return self._user(response.json())

    def create_or_update(self, email: str, password: str, platform: str) -> AuthUser:
        """Create the user (confirmed, marked); if the e-mail exists, take it over."""
        response = self._post_user(email, password, platform)
        if response.status_code in (200, 201):
            return self._user(response.json())
        if response.status_code not in (400, 409, 422):
            raise GoTrueError(f"create user failed: HTTP {response.status_code}")
        existing = self.find_by_email(email)
        if existing is None:
            raise GoTrueError(f"create user failed: HTTP {response.status_code}")
        return self.update(existing.id, password=password, platform=platform, ban=UNBAN)

    def update(
        self,
        user_id: uuid.UUID,
        *,
        password: str | None = None,
        platform: str | None = None,
        ban: str | None = None,
        email: str | None = None,
    ) -> AuthUser:
        body: dict[str, Any] = {}
        if email is not None:
            # P67: a retired reviewer user gives up its address for a fresh account.
            body["email"] = email
            body["email_confirm"] = True
        if password is not None:
            body["password"] = password
            body["email_confirm"] = True
        if platform is not None:
            body["app_metadata"] = reviewer_app_metadata(platform)
        if ban is not None:
            body["ban_duration"] = ban
        response = self._call("PUT", f"/users/{user_id}", json=body)
        if response.status_code != 200:
            raise GoTrueError(f"update user failed: HTTP {response.status_code}")
        return self._user(response.json())


__all__ = [
    "BAN_FOREVER",
    "UNBAN",
    "AuthUser",
    "GoTrueAdmin",
    "GoTrueError",
    "reviewer_app_metadata",
]
