"""Is a failed partition worth attempting again? (#1669, #1670)

A partition marked `retryable` is re-attempted on every run. That is right for a
timeout or a 500, and wrong for a 401: the credential does not hold the scope
this endpoint needs, and it will not start holding it because we asked a fifth
time.

Observed on the demo shop: 28 catalog partitions stuck on
`401 Client Error: Unauthorized` with `attempt_count = 4`, retried on every run
forever. Together with 47 `live` partitions they consumed the whole 300s budget
before any new work could start, so the beat could never complete a cycle —
which is what blocks #1339 Observation 1 bullet 4.
"""

from __future__ import annotations

import re

#: HTTP statuses that will not change by retrying with the same credential.
#: 401/403 are authorisation, 404 is a route or resource that does not exist.
#: 429 is deliberately ABSENT — rate limiting is exactly what retry is for.
_PERMANENT_STATUSES = (401, 403, 404)

_STATUS_RE = re.compile(r"\b(\d{3})\b")


def is_retryable_partition_error(error: BaseException | str) -> bool:
    """False when re-attempting cannot plausibly change the outcome.

    Conservative by design: anything unrecognised stays retryable. Wrongly
    marking a transient failure permanent silently drops a day of analytics,
    which is worse than the wasted calls this exists to stop.
    """
    text = str(error)
    for match in _STATUS_RE.finditer(text):
        if int(match.group(1)) in _PERMANENT_STATUSES:
            return False
    return True
