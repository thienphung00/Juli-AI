"""Fleet-wide credential refresh beat -- the beat layer of ADR-081's
three-layer refresh design (decision 1, row 1; #1232, AGT-W4A-WIRE).

Before this slice, nothing refreshed TikTok tokens on a schedule at all:
`workers/services/polling/orchestrate.py::run_fujiwa_poll_cycle` was never
in `celery_app.py`'s `beat_schedule`, reachable only through
`services/action_cards/refresh.py`'s manual hook. This is the fleet's
*first* refresh schedule, not a tightening of an existing one.

Every 30 minutes (`celery_app.py`'s `beat_schedule`), this task scans
credentials via #1230's `TikTokCredentialRepo.list_expiring_within` --
`token_expires_at` inside the 24h `REFRESH_BUFFER` window, `needs_reauth`
rows already excluded by that repo method -- and calls #1231's
`core.security.credential_refresh.refresh_credential(force=False)` per row.

**Isolation is the entire point.** `refresh_credential` never raises on a
vendor failure (ADR-081 decision 4): a `needs_reauth`-classifying failure or
a transient vendor error both come back as a `RefreshOutcome`, not an
exception, so one bad credential does not stop the loop from reaching the
rest of the fleet. `run_credential_refresh_cycle` additionally treats any
*unexpected* exception from a single row (e.g. a DB hiccup) as a per-row
failure rather than letting it propagate, for the same reason.

**Imports stay at the `core.security` public root.** `workers -> core` is
an allowed edge (`.importlinter.toml`), but `workers ->
core.security.credential_refresh` / `core.security.credential_resolver` are
both depth-3 deep imports (`max_cross_package_depth = 2`) with no baseline
entry for this new file. `from juli_backend.core.security import
credential_refresh, credential_resolver` reaches the depth-2 package root
instead -- the same seam `workers/tasks/reaper.py` already uses for
`services.agent`'s `runner`/`events`/`playbooks` facades.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security import credential_refresh, credential_resolver
from juli_backend.repositories.repos import TikTokCredentialRepo
from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url

logger = logging.getLogger(__name__)

RefreshCredentialFn = Callable[..., Awaitable["credential_refresh.RefreshOutcome"]]


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class CredentialRefreshCycleSummary:
    """Per-cycle counts, logged by `credential_refresh_beat` (ADR-081
    decision 9's wiring gate: "per-cycle summary
    (scanned/refreshed/skipped-locked/failed)").

    `RefreshStatus` has five variants; this collapses them into the four
    buckets the gate names: `refreshed` covers both `refreshed` (a vendor
    call rotated the token) and `fresh` (no vendor call was needed -- rare
    for a row the scan predicate selected, since the scan and
    `refresh_credential`'s own guard share the same `REFRESH_BUFFER`
    window, but not impossible under clock drift across a long cycle), and
    `failed` covers both `transient` (network/5xx/rate-limit) and
    `needs_reauth` (terminal) -- both are "the vendor call did not leave
    this credential refreshed" from the beat's point of view, whatever the
    cause.
    """

    scanned: int
    refreshed: int
    skipped_locked: int
    failed: int


async def run_credential_refresh_cycle(
    session: AsyncSession,
    *,
    auth: credential_refresh.RefreshAuth,
    now: datetime | None = None,
    refresh_fn: RefreshCredentialFn | None = None,
) -> CredentialRefreshCycleSummary:
    """The beat's core logic -- the seam every test in
    `test_credential_refresh_beat.py` drives directly.

    Enumerates expiring credentials via the SECURITY DEFINER function
    `enumerate_expiring_credentials`, then loops entering per-shop context
    (via `with_shop_scope`) per credential before refresh (ADR-089 decisions 2-4).

    `now` is injectable so window-boundary tests are deterministic (no real
    wall-clock flakiness, mirrors `workers/tasks/reaper.py`'s
    `reap_workflow_runs(now=...)`). `refresh_fn` is injectable so a test can
    prove the summary's four-bucket counting is correct against a fixture
    carrying one of each `RefreshStatus` variant without needing a real
    Postgres advisory-lock contest to produce a genuine `locked` outcome
    (SQLite, the unit-test matrix, has no such primitive) -- defaults to
    the real `credential_refresh.refresh_credential`.
    """
    from sqlalchemy import text

    from juli_backend.database.tenant_context import with_shop_scope

    refresh = refresh_fn if refresh_fn is not None else credential_refresh.refresh_credential
    reference = now if now is not None else _utc_now()

    # Enumerate credentials via SECURITY DEFINER function. Branch on dialect:
    # on PostgreSQL, call the function for the work list; on SQLite (unit tests),
    # fall back to a direct query since the function does not exist.
    # Per ADR-089 decision 3, enumeration is the *only* cross-tenant read.
    if session.get_bind().dialect.name == "postgresql":
        result = await session.execute(
            text(
                "SELECT out_credential_id, out_shop_id, out_expires_at "
                "FROM public.enumerate_expiring_credentials(:cutoff)"
            ).bindparams(cutoff=reference + credential_refresh.REFRESH_BUFFER)
        )
        enumerations = [(row[0], row[1]) for row in result.all()]
    else:
        # SQLite (unit tests) has neither the function nor RLS.
        repo = TikTokCredentialRepo(session)
        credentials = await repo.list_expiring_within(
            credential_refresh.REFRESH_BUFFER, now=reference
        )
        enumerations = [(cred.id, cred.shop_id) for cred in credentials]

    refreshed = 0
    skipped_locked = 0
    failed = 0

    # Loop over enumerated credentials, entering per-shop context per credential
    # before the refresh. The enumeration returns (credential_id, shop_id) tuples.
    for credential_id, shop_id in enumerations:
        async with with_shop_scope(session, shop_id):
            try:
                outcome = await refresh(session, credential_id, auth=auth, force=False)
            except Exception:
                failed += 1
                logger.exception(
                    "credential_refresh_beat_row_failed",
                    extra={"credential_id": str(credential_id)},
                )
                continue

            if outcome.status is credential_refresh.RefreshStatus.LOCKED:
                skipped_locked += 1
            elif outcome.status in (
                credential_refresh.RefreshStatus.TRANSIENT,
                credential_refresh.RefreshStatus.NEEDS_REAUTH,
            ):
                failed += 1
            else:
                # REFRESHED or FRESH -- see CredentialRefreshCycleSummary's docstring.
                refreshed += 1

    summary = CredentialRefreshCycleSummary(
        scanned=len(enumerations),
        refreshed=refreshed,
        skipped_locked=skipped_locked,
        failed=failed,
    )
    logger.info(
        "credential_refresh_beat_cycle_complete",
        extra={
            "scanned": summary.scanned,
            "refreshed": summary.refreshed,
            "skipped_locked": summary.skipped_locked,
            "failed": summary.failed,
        },
    )
    return summary


def _database_url() -> str:
    return get_async_database_url()


def _ensure_session_factory():
    from juli_backend.database.database import ensure_worker_session_factory

    return ensure_worker_session_factory(_database_url())


async def _run_credential_refresh_beat_async() -> None:
    from juli_backend.database.tenant_context import system_scope

    auth = credential_resolver.build_refresh_auth_from_env()
    if auth is None:
        logger.info(
            "credential_refresh_beat_skipped",
            extra={"reason": "missing_tiktok_app_env"},
        )
        return

    factory = _ensure_session_factory()
    async with factory() as session:
        async with system_scope(session, caller="credential_refresh_beat"):
            await run_credential_refresh_cycle(session, auth=auth)
            await session.commit()


@celery_app.task(name="juli_backend.credential_refresh_beat")
def credential_refresh_beat() -> None:
    """Celery Beat periodic task, every 30 minutes (ADR-081 decisions 1/2).

    Thin wrapper only, mirroring `workers/tasks/reaper.py`'s
    `reap_abandoned_workflow_runs`: builds the vendor auth from env, opens a
    session, delegates to `run_credential_refresh_cycle` with production
    defaults (real clock, the real `refresh_credential`). No-op when TikTok
    app credentials are not configured in env -- same as every environment
    before this slice existed.
    """
    asyncio.run(_run_credential_refresh_beat_async())
