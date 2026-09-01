"""Production write resolver precondition tests — issue #1336.

Validates that all four preconditions refuse with distinct named reasons:
1. PRODUCTION_WRITE_ENABLED flag off
2. No matching unconsumed, unexpired, unrevoked authorization
3. RLS boot assertion did not pass for this process
4. No red-team attestation for the deployed release SHA
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ProductionWriteAuthorization, Shop, User
from juli_backend.repositories.repos import ProductionWriteAuthorizationsRepo
from juli_backend.services.execution.production_write_resolver import (
    PreconditionFailure,
    PreconditionName,
    record_rls_boot_check_passed,
    resolve_write_capability,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def app(engine, session):
    from juli_backend.api.app import create_app
    from juli_backend.database import get_session

    application = create_app()

    async def _test_session():
        yield session

    application.dependency_overrides[get_session] = _test_session
    yield application
    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def authenticated_user(session, user_id):
    user = User(id=user_id, phone="+849305000305")
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def shop(session, authenticated_user):
    s = Shop(
        id=uuid.uuid4(),
        user_id=authenticated_user.id,
        shop_name="Production Write Resolver Test Shop",
        tiktok_shop_id="tiktok_shop_1336",
    )
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def authorization(session, shop):
    """Create a valid unconsumed authorization."""
    auth = ProductionWriteAuthorization(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_product_id="test_product_id",
        mutation_kind="listing.create_hero_product",
        authorized_by="test_operator",
        expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
    )
    session.add(auth)
    await session.flush()
    return auth


def teardown_function():
    """Reset boot check state between tests."""
    from juli_backend.services.execution import production_write_resolver

    production_write_resolver._RLS_BOOT_CHECK_PASSED = False


async def test_precondition_1_flag_off_refuses_with_flag_off_reason(
    session: AsyncSession,
    shop: Shop,
    monkeypatch,
):
    """Precondition 1: PRODUCTION_WRITE_ENABLED off → refusal with 'flag_off' reason."""
    monkeypatch.setenv("PRODUCTION_WRITE_ENABLED", "false")

    payload = {
        "shop_id": str(shop.id),
        "tiktok_product_id": "test_product",
        "mutation_kind": "listing.create_hero_product",
    }

    with pytest.raises(PreconditionFailure) as exc_info:
        await resolve_write_capability(
            session,
            tool_name="listing.create_hero_product",
            payload=payload,
            shop_id=shop.id,
        )

    assert exc_info.value.precondition == PreconditionName.PRODUCTION_WRITE_ENABLED_OFF
    assert "flag" in str(exc_info.value).lower() or "disabled" in str(exc_info.value).lower()


async def test_precondition_2_no_authorization_refuses_with_named_reason(
    session: AsyncSession,
    shop: Shop,
    monkeypatch,
    tmp_path,
):
    """Precondition 2: No authorization → distinct 'no_matching_authorization' refusal."""
    monkeypatch.setenv("PRODUCTION_WRITE_ENABLED", "true")
    _setup_test_attestation(monkeypatch, tmp_path)
    record_rls_boot_check_passed()

    payload = {
        "shop_id": str(shop.id),
        "tiktok_product_id": "nonexistent_product",
        "mutation_kind": "listing.create_hero_product",
    }

    with pytest.raises(PreconditionFailure) as exc_info:
        await resolve_write_capability(
            session,
            tool_name="listing.create_hero_product",
            payload=payload,
            shop_id=shop.id,
        )

    assert exc_info.value.precondition == PreconditionName.NO_MATCHING_AUTHORIZATION
    assert "authorization" in str(exc_info.value).lower()


async def test_precondition_3_boot_check_not_run_refuses_with_named_reason(
    session: AsyncSession,
    shop: Shop,
    authorization: ProductionWriteAuthorization,
    monkeypatch,
    tmp_path,
):
    """Precondition 3: RLS boot check not run → refusal with 'rls_boot_check_failed' reason."""
    monkeypatch.setenv("PRODUCTION_WRITE_ENABLED", "true")
    _setup_test_attestation(monkeypatch, tmp_path)
    # Do NOT call record_rls_boot_check_passed() — test absence

    payload = {
        "shop_id": str(shop.id),
        "tiktok_product_id": "test_product_id",
        "mutation_kind": "listing.create_hero_product",
    }

    with pytest.raises(PreconditionFailure) as exc_info:
        await resolve_write_capability(
            session,
            tool_name="listing.create_hero_product",
            payload=payload,
            shop_id=shop.id,
        )

    assert exc_info.value.precondition == PreconditionName.RLS_BOOT_CHECK_FAILED
    assert "boot" in str(exc_info.value).lower() or "rls" in str(exc_info.value).lower()


async def test_precondition_4_no_attestation_refuses_with_named_reason(
    session: AsyncSession,
    shop: Shop,
    authorization: ProductionWriteAuthorization,
    monkeypatch,
    tmp_path,
):
    """Precondition 4: No attestation for current SHA → refusal with 'no_attestation' reason."""
    monkeypatch.setenv("PRODUCTION_WRITE_ENABLED", "true")
    # Set up attestation dir but don't create a valid attestation record
    attestation_dir = tmp_path / "attestations"
    attestation_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PRODUCTION_WRITE_ATTESTATION_DIR", str(attestation_dir))
    record_rls_boot_check_passed()

    payload = {
        "shop_id": str(shop.id),
        "tiktok_product_id": "test_product_id",
        "mutation_kind": "listing.create_hero_product",
    }

    with pytest.raises(PreconditionFailure) as exc_info:
        await resolve_write_capability(
            session,
            tool_name="listing.create_hero_product",
            payload=payload,
            shop_id=shop.id,
        )

    assert exc_info.value.precondition == PreconditionName.NO_ATTESTATION_FOR_RELEASE_SHA
    assert "attestation" in str(exc_info.value).lower() or "sha" in str(exc_info.value).lower()


async def test_authorization_expires_between_approval_and_write_refuses_at_write(
    session: AsyncSession,
    shop: Shop,
    monkeypatch,
    tmp_path,
):
    """A run whose authorization expires between approval and write refuses at the write."""
    monkeypatch.setenv("PRODUCTION_WRITE_ENABLED", "true")
    _setup_test_attestation(monkeypatch, tmp_path)
    record_rls_boot_check_passed()

    # Create an authorization that expires very soon
    auth = ProductionWriteAuthorization(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_product_id="expiring_product",
        mutation_kind="listing.create_hero_product",
        authorized_by="test_operator",
        expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1),  # Already expired
    )
    session.add(auth)
    await session.flush()

    payload = {
        "shop_id": str(shop.id),
        "tiktok_product_id": "expiring_product",
        "mutation_kind": "listing.create_hero_product",
    }

    with pytest.raises(PreconditionFailure) as exc_info:
        await resolve_write_capability(
            session,
            tool_name="listing.create_hero_product",
            payload=payload,
            shop_id=shop.id,
        )

    assert exc_info.value.precondition == PreconditionName.NO_MATCHING_AUTHORIZATION


async def test_all_four_preconditions_met_returns_production_resources(
    session: AsyncSession,
    shop: Shop,
    authorization: ProductionWriteAuthorization,
    monkeypatch,
    tmp_path,
):
    """When all four preconditions are met, resolver returns production resources."""
    monkeypatch.setenv("PRODUCTION_WRITE_ENABLED", "true")
    _setup_test_attestation(monkeypatch, tmp_path)
    record_rls_boot_check_passed()

    payload = {
        "shop_id": str(shop.id),
        "tiktok_product_id": "test_product_id",
        "mutation_kind": "listing.create_hero_product",
    }

    # The resolver should return something that indicates production capability
    # We don't test the actual resources here (that's an integrations concern),
    # just that it doesn't raise a PreconditionFailure
    result = await resolve_write_capability(
        session,
        tool_name="listing.create_hero_product",
        payload=payload,
        shop_id=shop.id,
    )

    # Result should indicate production capability, not raise
    assert result is not None
    # Check authorization was consumed atomically
    repo = ProductionWriteAuthorizationsRepo(session)
    auth_after_consume = await repo.lookup(
        shop.id,
        "test_product_id",
        "listing.create_hero_product",
    )
    assert auth_after_consume is None  # Should be consumed (lookup returns None)


async def test_precondition_3_fail_closed_on_absence(
    session: AsyncSession,
    shop: Shop,
    authorization: ProductionWriteAuthorization,
    monkeypatch,
    tmp_path,
):
    """Precondition 3: A process whose boot check never ran is FAILED, not unknown."""
    monkeypatch.setenv("PRODUCTION_WRITE_ENABLED", "true")
    _setup_test_attestation(monkeypatch, tmp_path)
    # Boot check never ran — do not call record_rls_boot_check_passed()

    payload = {
        "shop_id": str(shop.id),
        "tiktok_product_id": "test_product_id",
        "mutation_kind": "listing.create_hero_product",
    }

    with pytest.raises(PreconditionFailure) as exc_info:
        await resolve_write_capability(
            session,
            tool_name="listing.create_hero_product",
            payload=payload,
            shop_id=shop.id,
        )

    # Absence of boot check state is treated as FAILED, not unknown
    assert exc_info.value.precondition == PreconditionName.RLS_BOOT_CHECK_FAILED


async def test_attestation_for_different_sha_refuses(
    session: AsyncSession,
    shop: Shop,
    authorization: ProductionWriteAuthorization,
    monkeypatch,
    tmp_path,
):
    """Precondition 4: An attestation for a different SHA refuses."""
    monkeypatch.setenv("PRODUCTION_WRITE_ENABLED", "true")

    attestation_dir = tmp_path / "attestations"
    attestation_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PRODUCTION_WRITE_ATTESTATION_DIR", str(attestation_dir))
    record_rls_boot_check_passed()

    # Create an attestation for a DIFFERENT sha
    wrong_sha = "0000000000000000000000000000000000000000"
    attestation_file = attestation_dir / f"{wrong_sha}.json"
    attestation_data = {
        "release_sha": wrong_sha,
        "date": datetime.now(UTC).isoformat(),
        "performed_by": "test_operator",
        "outcome": "pass",
    }
    attestation_file.write_text(json.dumps(attestation_data))

    payload = {
        "shop_id": str(shop.id),
        "tiktok_product_id": "test_product_id",
        "mutation_kind": "listing.create_hero_product",
    }

    with pytest.raises(PreconditionFailure) as exc_info:
        await resolve_write_capability(
            session,
            tool_name="listing.create_hero_product",
            payload=payload,
            shop_id=shop.id,
        )

    assert exc_info.value.precondition == PreconditionName.NO_ATTESTATION_FOR_RELEASE_SHA


def _setup_test_attestation(monkeypatch, tmp_path):
    """Helper to set up a valid attestation for the current release SHA."""
    import subprocess

    attestation_dir = tmp_path / "attestations"
    attestation_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PRODUCTION_WRITE_ATTESTATION_DIR", str(attestation_dir))

    # Get the current git SHA
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(Path(__file__).resolve().parent.parent.parent),
            text=True,
        ).strip()
    except Exception:
        # Fallback for test runs outside git
        sha = "0000000000000000000000000000000000000001"

    # Create an attestation for the current SHA
    attestation_file = attestation_dir / f"{sha}.json"
    attestation_data = {
        "release_sha": sha,
        "date": datetime.now(UTC).isoformat(),
        "performed_by": "test_operator",
        "outcome": "pass",
    }
    attestation_file.write_text(json.dumps(attestation_data))
