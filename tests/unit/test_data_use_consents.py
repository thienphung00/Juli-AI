"""``data_use_consents`` and the consent check on the SQLite schema (ADR-116 §2, D76).

The Postgres-only claims (RLS, the column-scoped revoke grant, the migration
round trip) are in ``tests/integration/test_data_use_consents_db.py``; this
module proves the vocabulary, the one-open-grant rule and that the check fails
closed.
"""

from __future__ import annotations

import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from juli_backend.models.consent import METHODS, SCOPES, DataUseConsent
from juli_backend.repositories.consent import DataUseConsentsRepo
from juli_backend.services.consent import (
    ConsentRequired,
    InvalidConsent,
    grant_consent,
    has_consent,
    require_consent,
    revoke_consent,
)
from tests.support.builders import make_tenant

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "backend/src/juli_backend/database/migrations"
MIGRATION = MIGRATIONS / "versions/103_data_use_consents.py"
BACKFILL = MIGRATIONS / "deferred/101_write_mode_backfill.py"

NOW = datetime(2026, 10, 26, 3, 0)
SHA = "ab" * 32


def _migration_module():
    spec = importlib.util.spec_from_file_location("mig103", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _grant(session, shop_id, scope="service", **overrides):
    values = {
        "scope": scope,
        "method": "contract_paper",
        "terms_version": "ory-hd-01-2026+pl02",
        "evidence_ref": "contract/2026.10.26-ORY- JULI AI - HDDV.docx",
        "granted_by": "ORY director",
        "granted_at": NOW,
    }
    values.update(overrides)
    return await grant_consent(session, shop_id, **values)


# -- migration <-> model (no database) ------------------------------------------------


def test_migration_vocabulary_matches_the_model():
    mig = _migration_module()
    assert (
        mig.SCOPES
        == SCOPES
        == (
            "service",
            "llm_processing",
            "llm_images",
            "llm_media",
            "pooled_training",
        )
    )
    assert mig.METHODS == METHODS == ("contract_paper", "in_app_click", "email")


def test_revision_fits_alembic_and_keeps_the_deferred_chain_the_tail():
    mig = _migration_module()
    assert mig.revision == "103_data_use_consents" and len(mig.revision) <= 32
    assert mig.down_revision == "102_shops_tiktok_numeric_id"
    # PR 3 (migration 104) is now the parent of the deferred tail.
    assert 'down_revision: str | None = "104_shop_pseudonym_keys"' in BACKFILL.read_text("utf-8")


def test_the_app_role_may_only_select_insert_and_revoke():
    text = MIGRATION.read_text("utf-8")
    assert "GRANT SELECT, INSERT ON public.{TABLE} TO {APP_ROLE}" in text
    assert "GRANT UPDATE (revoked_at) ON public.{TABLE} TO {APP_ROLE}" in text
    assert "FOR DELETE" not in text and "DELETE ON" not in text
    # The revoke policy only touches a row that is still open.
    assert "FOR UPDATE USING (shop_id = app_current_shop_id() AND revoked_at IS NULL)" in text


def test_data_use_consents_is_classified_tenant_direct():
    from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP

    assert TABLE_CLASSIFICATION_MAP[("public", "data_use_consents")] == "tenant_direct"


# -- the check fails closed -----------------------------------------------------------


async def test_no_grant_means_no(session):
    _, shop = await make_tenant(session)
    for scope in SCOPES:
        with pytest.raises(ConsentRequired) as info:
            await require_consent(session, shop.id, scope)
        assert info.value.scope == scope and info.value.shop_id == shop.id
        assert await has_consent(session, shop.id, scope) is False


async def test_a_grant_answers_only_its_own_scope_and_shop(session):
    _, shop = await make_tenant(session)
    _, other = await make_tenant(session)
    grant = await _grant(session, shop.id, "llm_processing")

    assert (await require_consent(session, shop.id, "llm_processing")).id == grant.id
    assert await has_consent(session, shop.id, "pooled_training") is False
    assert await has_consent(session, shop.id, "service") is False
    assert await has_consent(session, other.id, "llm_processing") is False


async def test_an_unknown_scope_is_a_no_even_with_grants(session):
    _, shop = await make_tenant(session)
    await _grant(session, shop.id, "service")
    with pytest.raises(ConsentRequired):
        await require_consent(session, shop.id, "everything")


async def test_a_failed_lookup_is_a_no(session, monkeypatch, caplog):
    _, shop = await make_tenant(session)
    await _grant(session, shop.id, "service")

    async def boom(self, shop_id, scope):
        raise RuntimeError("connection lost")

    monkeypatch.setattr(DataUseConsentsRepo, "find_open", boom)
    with pytest.raises(ConsentRequired):
        await require_consent(session, shop.id, "service")
    assert await has_consent(session, shop.id, "service") is False
    assert "consent_lookup_failed" in caplog.text


async def test_a_revoked_grant_is_a_no(session):
    _, shop = await make_tenant(session)
    await _grant(session, shop.id, "pooled_training", method="email")
    revoked = await revoke_consent(
        session, shop.id, "pooled_training", revoked_at=NOW + timedelta(days=3)
    )
    assert revoked.revoked_at == NOW + timedelta(days=3)
    assert await has_consent(session, shop.id, "pooled_training") is False


# -- grants and withdrawals -------------------------------------------------------------


async def test_withdraw_then_grant_again_keeps_both_rows(session):
    _, shop = await make_tenant(session)
    first = await _grant(session, shop.id, "pooled_training", method="in_app_click")
    await revoke_consent(session, shop.id, "pooled_training", revoked_at=NOW + timedelta(days=1))
    second = await _grant(
        session, shop.id, "pooled_training", method="in_app_click", granted_at=NOW + timedelta(2)
    )

    rows = await DataUseConsentsRepo(session).list(shop.id)
    assert {row.id for row in rows} >= {first.id, second.id}
    assert (await require_consent(session, shop.id, "pooled_training")).id == second.id


async def test_a_second_open_grant_is_refused(session):
    _, shop = await make_tenant(session)
    await _grant(session, shop.id, "service")
    with pytest.raises(InvalidConsent, match="already exists"):
        await _grant(session, shop.id, "service", method="email")


async def test_the_database_also_refuses_two_open_grants(session):
    _, shop = await make_tenant(session)
    repo = DataUseConsentsRepo(session)
    common = {
        "method": "email",
        "terms_version": "v1",
        "evidence_ref": "mail-1",
        "evidence_sha256": None,
        "granted_by": "x",
        "granted_at": NOW,
    }
    await repo.record_grant(shop.id, scope="service", **common)
    with pytest.raises(IntegrityError):
        await repo.record_grant(shop.id, scope="service", **common)


async def test_revoking_without_an_open_grant_is_refused(session):
    _, shop = await make_tenant(session)
    with pytest.raises(InvalidConsent, match="no open"):
        await revoke_consent(session, shop.id, "llm_processing")


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"scope": "all"}, "unknown scope"),
        ({"method": "zalo"}, "unknown method"),
        ({"terms_version": "  "}, "terms_version is required"),
        ({"evidence_ref": ""}, "evidence_ref is required"),
        ({"granted_by": " "}, "granted_by is required"),
        ({"evidence_sha256": "ABC"}, "evidence_sha256"),
        ({"evidence_sha256": "AB" * 32}, "evidence_sha256"),
    ],
)
async def test_malformed_grants_are_refused(session, override, message):
    _, shop = await make_tenant(session)
    with pytest.raises(InvalidConsent, match=message):
        await _grant(session, shop.id, **override)


async def test_evidence_hash_and_aware_times_are_stored_as_naive_utc(session):
    _, shop = await make_tenant(session)
    aware = datetime(2026, 10, 26, 10, 0, tzinfo=UTC) + timedelta(hours=0)
    grant = await _grant(session, shop.id, evidence_sha256=SHA, granted_at=aware)
    assert grant.evidence_sha256 == SHA
    assert grant.granted_at == datetime(2026, 10, 26, 10, 0)
    assert grant.granted_at.tzinfo is None


async def test_the_model_writes_the_table_the_migration_creates(session):
    _, shop = await make_tenant(session)
    grant = await _grant(session, shop.id)
    assert isinstance(grant, DataUseConsent)
    assert grant.id is not None and isinstance(grant.id, uuid.UUID)
    assert grant.revoked_at is None


# -- fleet calibration counts only pooled_training shops (ADR-116 §3, D76) ------------


async def _calibrate(session, shop_id, lever="cover_image", coefficient="1.0", readings=4):
    from decimal import Decimal

    from juli_backend.models.lever_flows import LeverCalibration

    session.add(
        LeverCalibration(
            shop_id=shop_id,
            lever=lever,
            coefficient=Decimal(coefficient),
            readings=readings,
            updated_at=NOW,
        )
    )
    await session.flush()


async def test_fleet_calibration_counts_only_shops_with_pooled_training(session):
    from decimal import Decimal

    from juli_backend.services.lever_flows.measurement import fleet_calibration_stats

    _, pooled = await make_tenant(session)
    _, private = await make_tenant(session)
    await _calibrate(session, pooled.id, coefficient="0.6", readings=4)
    await _calibrate(session, private.id, coefficient="1.8", readings=10)
    await _grant(session, pooled.id, "pooled_training")
    await _grant(session, private.id, "service")  # another scope is not enough

    assert await fleet_calibration_stats(session) == {"cover_image": (Decimal("0.6"), 4)}


async def test_a_revoked_pooled_training_grant_leaves_the_fleet_level(session):
    from juli_backend.services.lever_flows.measurement import fleet_calibration_stats

    _, shop = await make_tenant(session)
    await _calibrate(session, shop.id)
    await _grant(session, shop.id, "pooled_training")
    assert set(await fleet_calibration_stats(session)) == {"cover_image"}

    await revoke_consent(session, shop.id, "pooled_training", revoked_at=NOW + timedelta(days=1))
    assert await fleet_calibration_stats(session) == {}


async def test_no_consents_means_an_empty_fleet_and_prediction_uses_the_prior(session):
    from juli_backend.services.lever_flows.measurement import fleet_calibration_stats
    from juli_backend.services.optimize_product.prediction import CalibrationStats, predict

    _, shop = await make_tenant(session)
    await _calibrate(session, shop.id, coefficient="0.3", readings=2)

    fleet = await fleet_calibration_stats(session)
    assert fleet == {}
    prediction = predict(
        "cover_image", 80, shop=CalibrationStats(0.3, 2), fleet=fleet.get("cover_image")
    )
    assert prediction.source == "prior"
