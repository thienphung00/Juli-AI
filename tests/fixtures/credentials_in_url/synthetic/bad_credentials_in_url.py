"""Synthetic fixture: credential-shaped keys sent via a request URL/params
mapping instead of a JSON body — every function below must be flagged by
`agent-runtime/scripts/ci/check_credentials_in_url.py`.

Deliberately violates the rule that checker enforces (#904, ADR-061). Not
imported by the app or by production code, and not collected by pytest (the
file name does not match `test_*.py`/`*_test.py`). It also sits under
`tests/fixtures/`, which that checker's own default directory sweep always
skips — so this file never gates CI on its own account; it exists purely so
`tests/unit/test_credentials_in_url_guard.py` can prove the checker fires
when pointed at it directly.

Every "secret" value below is an obviously fake placeholder — this file
introduces no real credential and does not trip gitleaks.
"""

from __future__ import annotations

from urllib.parse import urlencode

import requests

FAKE_APP_SECRET = "FAKE_NOT_A_REAL_SECRET"
FAKE_ACCESS_TOKEN = "FAKE_NOT_A_REAL_TOKEN"
FAKE_REFRESH_TOKEN = "FAKE_NOT_A_REAL_REFRESH_TOKEN"
FAKE_API_KEY = "FAKE_NOT_A_REAL_API_KEY"


def bad_dict_literal_in_params() -> requests.Response:
    """Violation: a credential key sits directly in a `params=` dict literal —
    the exact shape #896 shipped: `requests.get(url, params=payload)` where
    `payload` carried `app_secret`."""
    return requests.get(
        "https://auth.example.com/api/v2/token/get",
        params={
            "app_secret": FAKE_APP_SECRET,
            "grant_type": "authorized_code",
        },
        timeout=10,
    )


def bad_subscript_assignment_into_params() -> requests.Response:
    """Violation: a credential key is assigned into a params dict via
    subscript, then that dict (not a literal) is passed as `params=`."""
    params: dict[str, str] = {"app_key": "FAKE_NOT_SECRET_CLIENT_ID"}
    params["access_token"] = FAKE_ACCESS_TOKEN
    return requests.get("https://api.example.com/v1/orders", params=params, timeout=10)


def bad_urlencode_credential() -> str:
    """Violation: `urlencode()` — the exact query-string-building primitive
    the original bug used — builds a query string carrying a refresh token."""
    query = urlencode({"refresh_token": FAKE_REFRESH_TOKEN, "grant_type": "refresh_token"})
    return f"https://auth.example.com/api/v2/token/refresh?{query}"


def bad_fstring_url_literal() -> str:
    """Violation: a credential embedded directly in an f-string query
    fragment, with no dict/mapping involved at all."""
    return f"https://api.example.com/v1/report?api_key={FAKE_API_KEY}&format=json"
