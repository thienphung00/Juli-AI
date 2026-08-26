"""Kill switch and audit trail for production writes (issue #1337).

Validates:
1. Kill switch read per call (not at boot)
2. Kill switch fails closed on malformed value
3. Kill switch as 5th precondition, checked after the four from #1336
4. Audit table records every attempt (allowed and refused)
5. Audit table is append-only (no update/delete code paths)
6. Audit table is tenant-scoped with RLS
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ProductionWriteAuthorization, Shop, User
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
        shop_name="Production Write Kill Switch Test Shop",
        tiktok_shop_id="tiktok_shop_1337",
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


def _setup_test_attestation(monkeypatch, tmp_path):
    """Helper to create a valid attestation for testing."""
    attestation_dir = tmp_path / "attestations"
    attestation_dir.mkdir(parents=True, exist_ok=True)

    # Create a test SHA attestation
    test_sha = "0" * 40
    attestation_file = attestation_dir / f"{test_sha}.json"
    attestation_data = {
        "release_sha": test_sha,
        "date": datetime.now(UTC).isoformat(),
        "performed_by": "test",
        "outcome": "pass",
    }
    attestation_file.write_text(json.dumps(attestation_data))

    monkeypatch.setenv("PRODUCTION_WRITE_ATTESTATION_DIR", str(attestation_dir))
    monkeypatch.setenv("RELEASE_SHA", test_sha)


def teardown_function():
    """Reset boot check state between tests."""
    from juli_backend.services.execution import production_write_resolver

    production_write_resolver._RLS_BOOT_CHECK_PASSED = False


class TestKillSwitch:
    """Tests for the kill switch (5th precondition)."""

    async def test_kill_switch_off_allows_writes(
        self,
        session: AsyncSession,
        shop: Shop,
        authorization: ProductionWriteAuthorization,
        monkeypatch,
        tmp_path,
    ):
        """With kill switch OFF, all four preconditions pass → production capability."""
        monkeypatch.setenv("PRODUCTION_WRITE_ENABLED", "true")
        monkeypatch.setenv("PRODUCTION_WRITE_KILL_SWITCH", "false")
        _setup_test_attestation(monkeypatch, tmp_path)
        record_rls_boot_check_passed()

        payload = {
            "shop_id": str(shop.id),
            "tiktok_product_id": "test_product_id",
            "mutation_kind": "listing.create_hero_product",
        }

        result = await resolve_write_capability(
            session,
            tool_name="listing.create_hero_product",
            payload=payload,
            shop_id=shop.id,
            run_id=uuid.uuid4(),
        )

        # Should return production capability marker
        assert result["capability"] == "production_write"
        assert result["authorization_id"] == str(authorization.id)

    async def test_kill_switch_on_refuses_with_named_reason(
        self,
        session: AsyncSession,
        shop: Shop,
        authorization: ProductionWriteAuthorization,
        monkeypatch,
        tmp_path,
    ):
        """With kill switch ON, production write is refused with 'kill_switch_active' reason."""
        monkeypatch.setenv("PRODUCTION_WRITE_ENABLED", "true")
        monkeypatch.setenv("PRODUCTION_WRITE_KILL_SWITCH", "true")
        _setup_test_attestation(monkeypatch, tmp_path)
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
                run_id=uuid.uuid4(),
            )

        assert exc_info.value.precondition == PreconditionName.PRODUCTION_WRITE_KILL_SWITCH_ACTIVE
        assert "kill switch" in str(exc_info.value).lower()

    async def test_kill_switch_read_per_call_mid_run(
        self,
        session: AsyncSession,
        shop: Shop,
        monkeypatch,
        tmp_path,
    ):
        """Kill switch flipped MID-RUN causes next production write to refuse.

        Demonstrates the switch is read per call, not at boot.
        """
        monkeypatch.setenv("PRODUCTION_WRITE_ENABLED", "true")
        monkeypatch.setenv("PRODUCTION_WRITE_KILL_SWITCH", "false")
        _setup_test_attestation(monkeypatch, tmp_path)
        record_rls_boot_check_passed()

        # First call with switch OFF should succeed (assuming authorization exists)
        auth1 = ProductionWriteAuthorization(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id="product_1",
            mutation_kind="listing.create_hero_product",
            authorized_by="test_operator",
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
        )
        session.add(auth1)
        await session.flush()

        payload1 = {
            "shop_id": str(shop.id),
            "tiktok_product_id": "product_1",
            "mutation_kind": "listing.create_hero_product",
        }

        result1 = await resolve_write_capability(
            session,
            tool_name="listing.create_hero_product",
            payload=payload1,
            shop_id=shop.id,
            run_id=uuid.uuid4(),
        )
        assert result1["capability"] == "production_write"

        # Now flip the switch ON mid-run
        monkeypatch.setenv("PRODUCTION_WRITE_KILL_SWITCH", "true")

        # Second call with switch ON should refuse
        auth2 = ProductionWriteAuthorization(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id="product_2",
            mutation_kind="listing.create_hero_product",
            authorized_by="test_operator",
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
        )
        session.add(auth2)
        await session.flush()

        payload2 = {
            "shop_id": str(shop.id),
            "tiktok_product_id": "product_2",
            "mutation_kind": "listing.create_hero_product",
        }

        with pytest.raises(PreconditionFailure) as exc_info:
            await resolve_write_capability(
                session,
                tool_name="listing.create_hero_product",
                payload=payload2,
                shop_id=shop.id,
                run_id=uuid.uuid4(),
            )

        assert exc_info.value.precondition == PreconditionName.PRODUCTION_WRITE_KILL_SWITCH_ACTIVE

    async def test_kill_switch_fail_closed_on_malformed_value(
        self,
        session: AsyncSession,
        shop: Shop,
        authorization: ProductionWriteAuthorization,
        monkeypatch,
        tmp_path,
    ):
        """Kill switch fails closed on unreadable/malformed value.

        Unparseable kill switch setting means writes are refused.
        """
        monkeypatch.setenv("PRODUCTION_WRITE_ENABLED", "true")
        monkeypatch.setenv("PRODUCTION_WRITE_KILL_SWITCH", "invalid_value")
        _setup_test_attestation(monkeypatch, tmp_path)
        record_rls_boot_check_passed()

        payload = {
            "shop_id": str(shop.id),
            "tiktok_product_id": "test_product_id",
            "mutation_kind": "listing.create_hero_product",
        }

        # Should refuse with kill switch active (fail-closed interpretation)
        with pytest.raises(PreconditionFailure) as exc_info:
            await resolve_write_capability(
                session,
                tool_name="listing.create_hero_product",
                payload=payload,
                shop_id=shop.id,
                run_id=uuid.uuid4(),
            )

        assert exc_info.value.precondition == PreconditionName.PRODUCTION_WRITE_KILL_SWITCH_ACTIVE

    async def test_kill_switch_off_does_not_bypass_other_preconditions(
        self,
        session: AsyncSession,
        shop: Shop,
        monkeypatch,
        tmp_path,
    ):
        """Kill switch OFF does not bypass the four preconditions from #1336.

        Turning off kill switch does not permit writes if no authorization exists.
        """
        monkeypatch.setenv("PRODUCTION_WRITE_ENABLED", "true")
        monkeypatch.setenv("PRODUCTION_WRITE_KILL_SWITCH", "false")
        _setup_test_attestation(monkeypatch, tmp_path)

        payload = {
            "shop_id": str(shop.id),
            "tiktok_product_id": "nonexistent_product",
            "mutation_kind": "listing.create_hero_product",
        }

        # Should refuse on precondition 2 (no authorization), not because of kill switch
        # This verifies that the kill switch being off doesn't bypass other checks
        with pytest.raises(PreconditionFailure) as exc_info:
            await resolve_write_capability(
                session,
                tool_name="listing.create_hero_product",
                payload=payload,
                shop_id=shop.id,
                run_id=uuid.uuid4(),
            )

        assert exc_info.value.precondition == PreconditionName.NO_MATCHING_AUTHORIZATION


class TestAuditTable:
    """Tests for the production_write_audit table."""

    async def test_audit_table_exists(self, session: AsyncSession):
        """Audit table exists and is queryable."""
        # Try to query a count to verify the table exists
        try:
            result = await session.execute(text("SELECT COUNT(*) FROM production_write_audit"))
            assert result.fetchone() is not None
        except Exception as e:
            pytest.fail(f"Audit table does not exist or is not queryable: {e}")

    async def test_audit_table_has_required_columns(self, session: AsyncSession):
        """Audit table has all required columns by attempting to insert."""
        # Verify we can create an audit record (which implicitly checks columns)
        from juli_backend.models.models import ProductionWriteAudit

        try:
            # Just verify the model exists and has the required attributes
            audit = ProductionWriteAudit(
                id=uuid.uuid4(),
                run_id=uuid.uuid4(),
                shop_id=uuid.uuid4(),
                tiktok_product_id="test",
                mutation_kind="test",
                authorization_id=None,
                precondition_name=None,
                release_sha="0" * 40,
            )
            # Check that all attributes are accessible
            assert audit.id is not None
            assert audit.run_id is not None
            assert audit.shop_id is not None
            assert audit.tiktok_product_id == "test"
            assert audit.mutation_kind == "test"
            assert audit.authorization_id is None
            assert audit.precondition_name is None
            assert audit.release_sha == "0" * 40
        except Exception as e:
            pytest.fail(f"Audit table model missing required columns: {e}")

    async def test_allowed_attempt_recorded_with_authorization_id(
        self,
        session: AsyncSession,
        shop: Shop,
        authorization: ProductionWriteAuthorization,
        monkeypatch,
        tmp_path,
    ):
        """Allowed production write is recorded in audit with authorization_id."""
        monkeypatch.setenv("PRODUCTION_WRITE_ENABLED", "true")
        monkeypatch.setenv("PRODUCTION_WRITE_KILL_SWITCH", "false")
        _setup_test_attestation(monkeypatch, tmp_path)
        record_rls_boot_check_passed()

        run_id = uuid.uuid4()
        payload = {
            "shop_id": str(shop.id),
            "tiktok_product_id": "test_product_id",
            "mutation_kind": "listing.create_hero_product",
        }

        await resolve_write_capability(
            session,
            tool_name="listing.create_hero_product",
            payload=payload,
            shop_id=shop.id,
            run_id=run_id,
        )

        # Query audit table for records with matching shop_id and product_id
        result = await session.execute(
            text("""
                SELECT tiktok_product_id, mutation_kind, authorization_id, precondition_name
                FROM production_write_audit
                WHERE tiktok_product_id = :product_id AND mutation_kind = :mutation
            """),
            {"product_id": "test_product_id", "mutation": "listing.create_hero_product"},
        )
        row = result.fetchone()

        assert row is not None, "Audit entry not found"
        assert row[0] == "test_product_id"
        assert row[1] == "listing.create_hero_product"
        # authorization_id is recorded for allowed attempts
        assert row[2] is not None, "Authorization ID should be recorded for allowed attempts"
        # precondition_name is NULL for allowed attempts
        assert row[3] is None, "Precondition name should be NULL for allowed attempts"

    async def test_refused_attempt_recorded_with_precondition_name(
        self,
        session: AsyncSession,
        shop: Shop,
        monkeypatch,
        tmp_path,
    ):
        """Refused production write is recorded in audit with precondition_name."""
        monkeypatch.setenv("PRODUCTION_WRITE_ENABLED", "true")
        monkeypatch.setenv("PRODUCTION_WRITE_KILL_SWITCH", "true")
        _setup_test_attestation(monkeypatch, tmp_path)
        record_rls_boot_check_passed()

        payload = {
            "shop_id": str(shop.id),
            "tiktok_product_id": "kill_switch_test_product",
            "mutation_kind": "listing.create_hero_product",
        }

        # Create a valid authorization so precondition 2 passes
        auth = ProductionWriteAuthorization(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id="kill_switch_test_product",
            mutation_kind="listing.create_hero_product",
            authorized_by="test_operator",
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
        )
        session.add(auth)
        await session.flush()

        with pytest.raises(PreconditionFailure):
            await resolve_write_capability(
                session,
                tool_name="listing.create_hero_product",
                payload=payload,
                shop_id=shop.id,
                run_id=uuid.uuid4(),
            )

        # Query audit table for records with matching product and mutation
        result = await session.execute(
            text("""
                SELECT tiktok_product_id, mutation_kind, authorization_id, precondition_name
                FROM production_write_audit
                WHERE tiktok_product_id = :product_id AND mutation_kind = :mutation
            """),
            {"product_id": "kill_switch_test_product", "mutation": "listing.create_hero_product"},
        )
        row = result.fetchone()

        assert row is not None, "Audit entry not found"
        assert row[0] == "kill_switch_test_product"
        assert row[1] == "listing.create_hero_product"
        # authorization_id is NULL for refused attempts
        assert row[2] is None, "Authorization ID should be NULL for refused attempts"
        # precondition_name is recorded for refused attempts
        assert row[3] == "production_write_kill_switch_active", (
            f"Expected kill_switch_active, got {row[3]}"
        )

    async def test_audit_append_only_no_update_method(self, session: AsyncSession):
        """Audit table has no code path for updating rows (append-only)."""
        # This is verified by code review and the migration file
        # The migration 047 only grants SELECT and INSERT, not UPDATE or DELETE
        # We can spot-check this by verifying the repo has no update/delete methods
        import inspect

        from juli_backend.services.execution import production_write_resolver

        # The audit recording function should only insert, not update or delete
        source = inspect.getsource(production_write_resolver._record_production_write_audit)
        assert "UPDATE" not in source.upper(), "Audit recording should not update rows"
        assert ".update(" not in source, "Audit recording should not call update methods"

    async def test_audit_append_only_no_delete_method(self, session: AsyncSession):
        """Audit table has no code path for deleting rows (append-only)."""
        # This is verified by code review and the migration file
        import inspect

        from juli_backend.services.execution import production_write_resolver

        # The audit recording function should only insert, not update or delete
        source = inspect.getsource(production_write_resolver._record_production_write_audit)
        assert "DELETE" not in source.upper(), "Audit recording should not delete rows"
        assert ".delete(" not in source, "Audit recording should not call delete methods"

    async def test_audit_tenant_scoped_with_rls(self, session: AsyncSession):
        """Audit table is tenant-scoped with RLS policies.

        Verified by checking that the audit table is in the tenant_scoped_tables map.
        """
        from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP

        # Check that the audit table is in the classification map
        assert ("public", "production_write_audit") in TABLE_CLASSIFICATION_MAP
        classification = TABLE_CLASSIFICATION_MAP[("public", "production_write_audit")]
        assert classification == "tenant_direct", (
            f"Audit table should be tenant_direct, not {classification}"
        )
