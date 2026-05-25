"""HMAC-SHA256 request signing for TikTok Shop Partner API.

Every API call must include a `sign` query parameter computed from the
request path, query parameters, and body using the app secret.
"""

from __future__ import annotations

import hashlib
import hmac

_EXCLUDED_PARAMS = frozenset({"sign", "access_token"})


def sign_request(
    app_secret: str,
    path: str,
    params: dict[str, str],
    body: str = "",
) -> str:
    """Compute the HMAC-SHA256 signature for a TikTok API request.

    Algorithm (per TikTok docs):
    1. Filter out ``sign`` and ``access_token`` from query params.
    2. Sort remaining params alphabetically by key.
    3. Concatenate as ``key1value1key2value2...`` (no separator).
    4. Build sign string: ``{secret}{path}{canonical}{body}{secret}``.
    5. HMAC-SHA256 using the app secret as key.
    6. Return lowercase hex digest.
    """
    filtered = {k: v for k, v in params.items() if k not in _EXCLUDED_PARAMS}
    canonical = "".join(f"{k}{v}" for k, v in sorted(filtered.items()))

    sign_string = f"{app_secret}{path}{canonical}{body}{app_secret}"

    return hmac.new(
        app_secret.encode(),
        sign_string.encode(),
        hashlib.sha256,
    ).hexdigest()
