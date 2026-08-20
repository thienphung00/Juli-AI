"""Parse TikTok ``access_token_expire_in`` values into naive UTC datetimes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

# Values above this threshold are Unix epoch seconds (live API), not TTL seconds.
_EPOCH_SECONDS_THRESHOLD = 1_000_000_000


def access_token_expires_at(raw: int | None, *, now: datetime | None = None) -> datetime:
    """Convert TikTok token expiry to a naive UTC ``datetime``.

    TikTok returns an absolute Unix timestamp in production responses; tests and
    older fixtures may use a TTL in seconds (e.g. 604800).

    Raises ``ValueError`` when ``raw`` is missing or zero (ADR-081 decision 3):
    ``token_expires_at`` may only be written from a vendor token response, never
    synthesized. A wrong expiry is worse than a missing one, because a wrong one
    *suppresses* the refresh that would have corrected it -- exactly what
    happened to the sandbox credential, seeded ``now + 7d`` while the live API
    answered ``105002 Expired``. Existing rows are not backfilled; they acquire
    a true value on their next real refresh.
    """
    if not raw:
        raise ValueError(
            "TikTok response omitted access_token_expire_in; refusing to "
            "synthesize an expiry (ADR-081 decision 3)"
        )

    if raw >= _EPOCH_SECONDS_THRESHOLD:
        return datetime.fromtimestamp(raw, tz=UTC).replace(tzinfo=None)

    return (now or _utc_now()) + timedelta(seconds=raw)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
