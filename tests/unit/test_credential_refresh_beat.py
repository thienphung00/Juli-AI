"""TDD tests for #1232 (AGT-W4A-WIRE, ADR-081 decision 1 row 1) --
`workers/tasks/credential_refresh_beat.py::run_credential_refresh_cycle`:
the fleet-wide beat that scans #1230's `list_expiring_within` window and
calls #1231's `refresh_credential(force=False)` per row.

Wiring (celery_app.py's beat_schedule/task_routes, the systemd -Q flag, and
the static no-direct-call-sites assertion) lives in
`test_credential_refresh_wiring.py`, not here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from juli_backend.core.security.credential_refresh import RefreshOutcome, RefreshStatus
from juli_backend.integrations.tiktok.exceptions import TikTokAPIError
from juli_backend.repositories.repos import ShopsRepo, TikTokCredentialRepo
from juli_backend.workers.tasks.credential_refresh_beat import (
    CredentialRefreshCycleSummary,
    run_credential_refresh_cycle,
)

pytestmark = pytest.mark.asyncio


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


_shop_counter = 0


async def _seed_credential(
    session,
    user_id,
    *,
    token_expires_at: datetime,
    access_token: str = "old-access-token",
    refresh_token: str = "old-refresh-token",
):
    global _shop_counter
    _shop_counter += 1
    shop = await ShopsRepo(session).create(user_id, f"Credential Beat Test Shop {_shop_counter}")
    return await TikTokCredentialRepo(session).create(
        shop_id=shop.id,
        access_token=access_token,
        refresh_token=refresh_token,
        token_expires_at=token_expires_at,
    )


def _auth_returning(
    access_token: str = "new-access-token",
    refresh_token: str = "new-refresh-token",
    access_token_expire_in: int = 604800,
) -> MagicMock:
    auth = MagicMock()
    auth.refresh_access_token = MagicMock(
        return_value={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "access_token_expire_in": access_token_expire_in,
        }
    )
    return auth


class TestScanWindowThroughTheTask:
    async def test_gap_6_shape_1h_and_20h_refresh_48h_skipped(self, session, user_id):
        """Same fixture shape as #1230's gap-6 regression test
        (test_credential_refresh_columns.py), exercised through the beat
        task rather than the repo method directly."""
        now = _utc_now()
        cred_1h = await _seed_credential(
            session, user_id, token_expires_at=now + timedelta(hours=1)
        )
        cred_20h = await _seed_credential(
            session, user_id, token_expires_at=now + timedelta(hours=20)
        )
        cred_48h = await _seed_credential(
            session, user_id, token_expires_at=now + timedelta(hours=48)
        )
        auth = _auth_returning()

        summary = await run_credential_refresh_cycle(session, auth=auth, now=now)

        assert summary.scanned == 2
        assert summary.refreshed == 2
        assert summary.skipped_locked == 0
        assert summary.failed == 0

        refreshed_1h = await session.get(type(cred_1h), cred_1h.id)
        refreshed_20h = await session.get(type(cred_20h), cred_20h.id)
        untouched_48h = await session.get(type(cred_48h), cred_48h.id)
        assert refreshed_1h.refresh_count == 1
        assert refreshed_20h.refresh_count == 1
        assert untouched_48h.refresh_count == 0


class TestIsolation:
    async def test_needs_reauth_outcome_for_one_row_does_not_abort_the_cycle(
        self, session, user_id
    ):
        """One credential's own refresh attempt fails terminal (needs_reauth);
        the beat must still refresh the other two active rows due for
        refresh in the same cycle. This is #1231's return-an-outcome
        contract exercised through the beat's loop, not a scan exclusion --
        all three rows are ACTIVE (not needs_reauth) when the scan runs."""
        now = _utc_now()
        # Ordered ascending by expiry -- list_expiring_within's own order --
        # so the shared auth mock's side_effect list lines up with
        # processing order: refresh, fail(needs_reauth), refresh.
        cred_first = await _seed_credential(
            session, user_id, token_expires_at=now + timedelta(hours=1)
        )
        cred_failing = await _seed_credential(
            session, user_id, token_expires_at=now + timedelta(hours=2)
        )
        cred_last = await _seed_credential(
            session, user_id, token_expires_at=now + timedelta(hours=3)
        )

        auth = MagicMock()
        auth.refresh_access_token = MagicMock(
            side_effect=[
                {
                    "access_token": "first-new",
                    "refresh_token": "first-new-refresh",
                    "access_token_expire_in": 604800,
                },
                TikTokAPIError(code=105002, message="Expired"),
                {
                    "access_token": "last-new",
                    "refresh_token": "last-new-refresh",
                    "access_token_expire_in": 604800,
                },
            ]
        )

        summary = await run_credential_refresh_cycle(session, auth=auth, now=now)

        assert summary.scanned == 3
        assert summary.refreshed == 2
        assert summary.failed == 1
        assert summary.skipped_locked == 0

        refreshed_first = await session.get(type(cred_first), cred_first.id)
        failed_row = await session.get(type(cred_failing), cred_failing.id)
        refreshed_last = await session.get(type(cred_last), cred_last.id)
        assert refreshed_first.refresh_count == 1
        assert refreshed_last.refresh_count == 1
        assert failed_row.status == "needs_reauth"

    async def test_preexisting_needs_reauth_row_is_excluded_from_the_scan_and_others_still_run(
        self, session, user_id
    ):
        """A credential already `needs_reauth` before the cycle starts is
        excluded by #1230's list_expiring_within predicate -- the beat never
        even attempts it -- while the two active rows due for refresh still
        get refreshed."""
        now = _utc_now()
        cred_needs_reauth = await _seed_credential(
            session, user_id, token_expires_at=now + timedelta(hours=1)
        )
        await TikTokCredentialRepo(session).mark_needs_reauth(
            cred_needs_reauth.id, "vendor 105002 expired"
        )
        cred_active_a = await _seed_credential(
            session, user_id, token_expires_at=now + timedelta(hours=2)
        )
        cred_active_b = await _seed_credential(
            session, user_id, token_expires_at=now + timedelta(hours=3)
        )
        auth = _auth_returning()

        summary = await run_credential_refresh_cycle(session, auth=auth, now=now)

        assert summary.scanned == 2
        assert summary.refreshed == 2
        assert summary.failed == 0

        refreshed_a = await session.get(type(cred_active_a), cred_active_a.id)
        refreshed_b = await session.get(type(cred_active_b), cred_active_b.id)
        assert refreshed_a.refresh_count == 1
        assert refreshed_b.refresh_count == 1


class TestSummaryLogging:
    async def test_summary_counts_one_of_each_refresh_outcome_variant(
        self, session, user_id, caplog
    ):
        """Every `RefreshStatus` variant present in one cycle, via the
        injectable `refresh_fn` seam (LOCKED has no real-lock-contention
        path against SQLite, the unit-test matrix's dialect)."""
        import logging

        now = _utc_now()
        cred_fresh = await _seed_credential(
            session, user_id, token_expires_at=now + timedelta(hours=1)
        )
        cred_refreshed = await _seed_credential(
            session, user_id, token_expires_at=now + timedelta(hours=2)
        )
        cred_locked = await _seed_credential(
            session, user_id, token_expires_at=now + timedelta(hours=3)
        )
        cred_transient = await _seed_credential(
            session, user_id, token_expires_at=now + timedelta(hours=4)
        )
        cred_needs_reauth = await _seed_credential(
            session, user_id, token_expires_at=now + timedelta(hours=5)
        )

        outcomes_by_id = {
            cred_fresh.id: RefreshStatus.FRESH,
            cred_refreshed.id: RefreshStatus.REFRESHED,
            cred_locked.id: RefreshStatus.LOCKED,
            cred_transient.id: RefreshStatus.TRANSIENT,
            cred_needs_reauth.id: RefreshStatus.NEEDS_REAUTH,
        }

        async def fake_refresh(sess, credential_id, *, auth, force=False):
            del auth, force
            credential = await sess.get(type(cred_fresh), credential_id)
            return RefreshOutcome(credential=credential, status=outcomes_by_id[credential_id])

        with caplog.at_level(logging.INFO):
            summary = await run_credential_refresh_cycle(
                session, auth=MagicMock(), now=now, refresh_fn=fake_refresh
            )

        assert summary == CredentialRefreshCycleSummary(
            scanned=5, refreshed=2, skipped_locked=1, failed=2
        )

        summary_records = [
            r for r in caplog.records if r.getMessage() == "credential_refresh_beat_cycle_complete"
        ]
        assert len(summary_records) == 1
        record = summary_records[0]
        assert record.scanned == 5
        assert record.refreshed == 2
        assert record.skipped_locked == 1
        assert record.failed == 2


class TestUnexpectedRowFailureIsolation:
    async def test_unexpected_exception_from_one_row_does_not_abort_the_cycle(
        self, session, user_id
    ):
        now = _utc_now()
        cred_boom = await _seed_credential(
            session, user_id, token_expires_at=now + timedelta(hours=1)
        )
        cred_ok = await _seed_credential(
            session, user_id, token_expires_at=now + timedelta(hours=2)
        )

        async def flaky_refresh(sess, credential_id, *, auth, force=False):
            del sess, auth, force
            if credential_id == cred_boom.id:
                raise RuntimeError("simulated DB hiccup")
            return RefreshOutcome(
                credential=await session.get(type(cred_ok), credential_id),
                status=RefreshStatus.REFRESHED,
            )

        summary = await run_credential_refresh_cycle(
            session, auth=MagicMock(), now=now, refresh_fn=flaky_refresh
        )

        assert summary.scanned == 2
        assert summary.refreshed == 1
        assert summary.failed == 1
