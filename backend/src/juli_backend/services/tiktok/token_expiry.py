"""Parse TikTok ``access_token_expire_in`` values into naive UTC datetimes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# Values above this threshold are Unix epoch seconds (live API), not TTL seconds.
_EPOCH_SECONDS_THRESHOLD = 1_000_000_000


def access_token_expires_at(raw: int | None, *, now: datetime | None = None) -> datetime:
    """Convert TikTok token expiry to a naive UTC ``datetime``.

    TikTok returns an absolute Unix timestamp in production responses; tests and
    older fixtures may use a TTL in seconds (e.g. 604800).
    """
    if not raw:
        return (now or _utc_now()) + timedelta(hours=1)

    if raw >= _EPOCH_SECONDS_THRESHOLD:
        return datetime.fromtimestamp(raw, tz=timezone.utc).replace(tzinfo=None)

    return (now or _utc_now()) + timedelta(seconds=raw)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
