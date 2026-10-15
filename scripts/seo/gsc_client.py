"""Thin Search Console API client (OAuth 2.0 desktop flow + REST calls with retry).

Endpoints used (Search Console API reference, read 2026-10-15):
- POST webmasters/v3/sites/{siteUrl}/searchAnalytics/query   rowLimit <= 25,000, page with startRow
- POST searchconsole/v1/urlInspection/index:inspect          2,000 / day and 600 / min per site
- GET  webmasters/v3/sites/{siteUrl}/sitemaps                list (errors, warnings, contents)
- PUT  webmasters/v3/sites/{siteUrl}/sitemaps/{feedpath}     submit (needs the read/write scope)
- GET  webmasters/v3/sites                                   which properties this user can read

Only OAuth 2.0 is accepted (no API keys, no service account unless it is added as a user
of the property). First run opens a browser for consent and caches a refresh token.
"""

from __future__ import annotations

import json
import random
import time
from typing import Any
from urllib.parse import quote

from scripts.seo import config

WEBMASTERS = "https://www.googleapis.com/webmasters/v3"
INSPECT = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
RETRYABLE = {429, 500, 502, 503, 504}
IDENTITY_SCOPES = ("openid", "https://www.googleapis.com/auth/userinfo.email")
USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"


def _credentials(write: bool):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    # openid + email only so the scripts can say WHICH Google account the token belongs to —
    # an account without the property silently gets an empty site list.
    scopes = [config.SCOPE_READWRITE if write else config.SCOPE_READONLY, *IDENTITY_SCOPES]
    creds = None
    if config.TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(config.TOKEN_PATH))
        granted = set(creds.scopes or [])
        # read/write covers read-only; a read-only token cannot submit a sitemap.
        gsc_ok = config.SCOPE_READWRITE in granted or (
            not write and config.SCOPE_READONLY in granted
        )
        if not (gsc_ok and set(IDENTITY_SCOPES) <= granted):
            creds = None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not config.CLIENT_SECRET_PATH.exists():
            raise SystemExit(
                f"OAuth client not found at {config.CLIENT_SECRET_PATH}. Create a 'Desktop app' "
                "OAuth client in Google Cloud Console (Search Console API enabled) and save its "
                "JSON there, or set JULI_GSC_CLIENT_SECRET. See scripts/seo/README.md."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(config.CLIENT_SECRET_PATH), scopes)
        creds = flow.run_local_server(port=0, prompt="consent")
    config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config.TOKEN_PATH.write_text(creds.to_json())
    config.TOKEN_PATH.chmod(0o600)
    return creds


class GSC:
    def __init__(self, site: str = config.SITE_URL, write: bool = False) -> None:
        from google.auth.transport.requests import AuthorizedSession

        self.site = site
        self.session = AuthorizedSession(_credentials(write))
        # Performance guide: gzip + a UA containing "gzip".
        self.session.headers.update(
            {"Accept-Encoding": "gzip", "User-Agent": "juli-seo-scripts (gzip)"}
        )

    def _call(self, method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        for attempt in range(6):
            resp = self.session.request(method, url, json=body, timeout=60)
            if resp.status_code not in RETRYABLE:
                break
            # Limits guide: on "quota exceeded" wait (short-term quota is per 10 minutes).
            wait = min(60 * 15, (2**attempt) * 5) + random.uniform(0, 2)
            time.sleep(wait)
        if resp.status_code >= 400:
            try:
                err = resp.json().get("error", {})
            except json.JSONDecodeError:
                err = {"message": resp.text[:300]}
            raise RuntimeError(f"{method} {url} -> {resp.status_code}: {err.get('message')}")
        return resp.json() if resp.content else {}

    def _site_path(self) -> str:
        return f"{WEBMASTERS}/sites/{quote(self.site, safe='')}"

    def account(self) -> str:
        """E-mail of the Google account behind the token."""
        return self._call("GET", USERINFO).get("email", "?")

    # ---- sites / sitemaps -------------------------------------------------------------
    def sites(self) -> list[dict[str, Any]]:
        return self._call("GET", f"{WEBMASTERS}/sites").get("siteEntry", [])

    def sitemaps(self) -> list[dict[str, Any]]:
        return self._call("GET", f"{self._site_path()}/sitemaps").get("sitemap", [])

    def submit_sitemap(self, feed: str) -> None:
        self._call("PUT", f"{self._site_path()}/sitemaps/{quote(feed, safe='')}")

    # ---- search analytics -------------------------------------------------------------
    def query(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        """All rows of a query, paging by startRow in 25,000s until an empty page."""
        rows: list[dict[str, Any]] = []
        start = 0
        while True:
            page = self._call(
                "POST",
                f"{self._site_path()}/searchAnalytics/query",
                {**body, "rowLimit": 25000, "startRow": start},
            ).get("rows", [])
            rows.extend(page)
            if len(page) < 25000:
                return rows
            start += 25000

    # ---- URL inspection ----------------------------------------------------------------
    def inspect(self, url: str) -> dict[str, Any]:
        res = self._call(
            "POST", INSPECT, {"inspectionUrl": url, "siteUrl": self.site, "languageCode": "vi"}
        )
        return res.get("inspectionResult", {})
