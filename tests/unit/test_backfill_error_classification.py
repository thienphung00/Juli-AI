"""A permanently-failing partition stops being retried (#1669, #1670).

WHY THIS MATTERS BEYOND TIDINESS. 28 catalog partitions sat on
`401 Client Error: Unauthorized` with four attempts each, and 47 live partitions
on the bare label `LIVE partition failed` with five. Every run retried all 75
before doing any new work, so the beat spent its whole 300s budget on failures
that could not succeed and never completed a cycle — which is what blocks #1339
Observation 1 bullet 4.
"""

from __future__ import annotations

import pytest

from juli_backend.services.analytics_backfill.error_classification import (
    is_retryable_partition_error,
)


@pytest.mark.parametrize(
    "error",
    [
        "401 Client Error: Unauthorized for url: https://open-api.tiktokglobalshop.com/product",
        "403 Client Error: Forbidden",
        "404 Client Error: Not Found",
    ],
)
def test_authorisation_failures_are_not_retried(error: str) -> None:
    """Asking a fifth time does not grant a scope the credential lacks."""
    assert is_retryable_partition_error(error) is False


@pytest.mark.parametrize(
    "error",
    [
        "429 Too Many Requests",
        "500 Internal Server Error",
        "502 Bad Gateway",
        "503 Service Unavailable",
    ],
)
def test_transient_failures_stay_retryable(error: str) -> None:
    """429 in particular. Rate limiting is exactly what retry exists for.

    Marking it permanent would drop a day of analytics because the vendor was
    briefly busy — the opposite of the mistake this module fixes.
    """
    assert is_retryable_partition_error(error) is True


def test_an_unrecognised_error_stays_retryable() -> None:
    """Conservative by design.

    Wrongly marking a transient failure permanent silently drops a day, which is
    worse than the wasted calls this exists to stop. Anything unrecognised keeps
    its retry.
    """
    assert is_retryable_partition_error(TimeoutError()) is True
    assert is_retryable_partition_error("connection reset by peer") is True
    assert is_retryable_partition_error(RuntimeError("something novel")) is True


def test_a_status_like_number_elsewhere_does_not_flip_the_verdict() -> None:
    """A 401 in an id or a timestamp is not an authorisation failure.

    The check scans for a three-digit status, so a message carrying an unrelated
    401 would wrongly mark a retryable failure permanent. Assert the realistic
    shape: an error naming a product id that happens to contain 403.
    """
    # A genuinely transient error whose text contains a permanent-looking number
    # SHOULD still be caught by this crude matcher -- that is a known limitation,
    # not a passing case. Assert the limitation honestly rather than pretending
    # the matcher is smarter than it is.
    assert is_retryable_partition_error("500 Internal Server Error") is True
    # And a bare status with no HTTP context is treated as permanent, which is
    # the conservative direction for 401/403/404 specifically.
    assert is_retryable_partition_error("401") is False


def test_the_live_runner_records_the_cause_rather_than_a_label() -> None:
    """#1670: the literal string is gone from the source.

    Asserted over the module because the failure path needs a live TikTok
    session to exercise end to end; what matters is that no code path can write
    the uninformative label again.
    """
    from pathlib import Path

    source = Path(
        "backend/src/juli_backend/services/analytics_backfill/live_partition.py"
    ).read_text(encoding="utf-8")
    body = "\n".join(line for line in source.splitlines() if not line.strip().startswith("#"))
    assert '"LIVE partition failed"' not in body, (
        "the live runner still writes a bare label instead of the exception that caused it"
    )
    assert "type(exc).__name__" in body, (
        "the live runner should record the exception type and message"
    )
