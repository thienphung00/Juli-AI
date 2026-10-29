"""Shared settings for the app-juli.com SEO scripts (D43).

Everything here is overridable by environment so the scripts run unchanged on the
owner's Mac or on the VPS cron.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Search Console property. A Domain property covers app-juli.com AND every subdomain
#: (demo., ops.), which is what lets one property both track the main site and prove the
#: subdomains are out of the index.
SITE_URL = os.environ.get("JULI_GSC_SITE", "sc-domain:app-juli.com")

#: The only host Google should index (D43 + owner, 2026-10-15).
MAIN_ORIGIN = os.environ.get("JULI_MAIN_ORIGIN", "https://app-juli.com")
SITEMAP_URL = os.environ.get("JULI_SITEMAP_URL", f"{MAIN_ORIGIN}/sitemap.xml")

#: Hosts that must carry noindex and should disappear from Google.
NOINDEX_HOSTS = tuple(
    h.strip()
    for h in os.environ.get(
        "JULI_NOINDEX_HOSTS", "demo.app-juli.com,app.app-juli.com,ops.app-juli.com"
    ).split(",")
    if h.strip()
)

#: Sample URLs per noindex host for the live check and the URL inspection.
NOINDEX_SAMPLE_PATHS = ("/", "/decisions", "/analytics", "/auth/email")

DATA_DIR = Path(os.environ.get("JULI_SEO_DATA", Path.home() / ".local/share/juli-seo"))
DB_PATH = DATA_DIR / "gsc.sqlite"
REPORT_DIR = DATA_DIR / "reports"

CONFIG_DIR = Path(os.environ.get("JULI_SEO_CONFIG", Path.home() / ".config/juli-seo"))
TOKEN_PATH = CONFIG_DIR / "token.json"
#: OAuth "Desktop app" client downloaded from Google Cloud Console (owner step).
CLIENT_SECRET_PATH = Path(
    os.environ.get("JULI_GSC_CLIENT_SECRET", CONFIG_DIR / "client_secret.json")
)

#: Read-only is enough for everything except submitting a sitemap.
SCOPE_READONLY = "https://www.googleapis.com/auth/webmasters.readonly"
SCOPE_READWRITE = "https://www.googleapis.com/auth/webmasters"

#: Search Analytics data is final after ~2-3 days (Search Console API guide
#: "all-your-data"); the daily pull reads the day this many days ago.
FINAL_DATA_LAG_DAYS = 3

#: D43 on-page budgets the live check enforces.
TITLE_MAX = 60
DESCRIPTION_MAX = 155
