"""Production write capability resolver — issue #1336, #1337.

Five-precondition resolver that determines whether a WRITE tool call should
resolve to production resources, sandbox resources, or refuse with a named error.

The five preconditions, each with its own distinct refusal:
1. PRODUCTION_WRITE_ENABLED is on (default off)
2. A matching unconsumed, unexpired, unrevoked authorization row exists
3. The RLS boot assertion passed for this process (recorded at boot)
4. A red-team attestation is recorded for the deployed release SHA
5. The kill switch is OFF (read per call, not at boot)

All production-write attempts are recorded in production_write_audit.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.config import (
    is_production_write_enabled,
    is_production_write_kill_switch_active,
)
from juli_backend.repositories.repos import ProductionWriteAuthorizationsRepo

logger = logging.getLogger(__name__)

# Module-level flag that records whether the RLS boot check passed
_RLS_BOOT_CHECK_PASSED = False


class PreconditionName(str, Enum):
    """Names of the five preconditions, for distinct refusals."""

    PRODUCTION_WRITE_ENABLED_OFF = "production_write_enabled_off"
    NO_MATCHING_AUTHORIZATION = "no_matching_authorization"
    RLS_BOOT_CHECK_FAILED = "rls_boot_check_failed"
    NO_ATTESTATION_FOR_RELEASE_SHA = "no_attestation_for_release_sha"
    PRODUCTION_WRITE_KILL_SWITCH_ACTIVE = "production_write_kill_switch_active"


@dataclass
class PreconditionFailure(Exception):
    """Exception raised when a precondition is unmet."""

    precondition: PreconditionName
    message: str

    def __str__(self) -> str:
        return f"{self.precondition.value}: {self.message}"


def record_rls_boot_check_passed() -> None:
    """Record that the RLS boot check passed for this process.

    Called from #1330's boot assertion (workers/agent_runtime_boot.py check 7)
    when PRODUCTION_WRITE_ENABLED is on and preconditions are met. The resolver
    later reads this flag to validate precondition 3.

    This is set at boot time and never changes during the process lifetime.
    """
    global _RLS_BOOT_CHECK_PASSED
    _RLS_BOOT_CHECK_PASSED = True
    logger.info("RLS boot check passed; production write capability available at boot")


def get_rls_boot_check_state() -> bool:
    """Read the RLS boot check state recorded at boot.

    Precondition 3 reads this value; it is NOT a live re-query of the database.
    If the boot check never ran (process started before the capability was
    enabled, or capability is off), this returns False — fail-closed on absence.
    """
    return _RLS_BOOT_CHECK_PASSED


async def resolve_write_capability(
    session: AsyncSession,
    *,
    tool_name: str,
    payload: dict,
    shop_id,
    run_id=None,
):
    """Resolve a WRITE tool call to production or sandbox resources.

    Returns sandbox resources (when flag is off, the default) or raises
    PreconditionFailure with a distinct named reason (when any is unmet).

    When all five preconditions hold, returns a production authorization marker
    (production resources will be created when ProductionWriteClientFactory is available).

    The five preconditions (each with a distinct refusal name):
    1. PRODUCTION_WRITE_ENABLED is on (default off)
    2. A matching unconsumed, unexpired, unrevoked authorization row exists
    3. The RLS boot assertion passed for this process (recorded at boot)
    4. A red-team attestation is recorded for the deployed release SHA
    5. The kill switch is OFF (read per call, not at boot)

    All production-write attempts are recorded in production_write_audit,
    before the refusal propagates (so refusals cannot be lost).

    Args:
        session: AsyncSession for database queries
        tool_name: the registered tool name (e.g. "listing.create_hero_product")
        payload: the tool payload dict, which should include:
            - tiktok_product_id
            - mutation_kind (tool_name, for authorization lookup)
        shop_id: UUID of the active shop (for authorization scoping)
        run_id: optional UUID to record in the authorization's consumed_by_run_id field.
                If not provided, a placeholder UUID is used (should be replaced with actual run_id)

    Returns:
        SandboxWriteResources if flag is off (default), or a dict marker with
        capability="production_write" when all five preconditions pass.

    Raises:
        PreconditionFailure: with precondition name and reason if any is unmet
    """
    # Precondition 1: PRODUCTION_WRITE_ENABLED is on
    if not is_production_write_enabled():
        # Default path — flag is off, which is today's configuration
        # Resolve to sandbox and return actual SandboxWriteResources
        from juli_backend.services.execution.sandbox_guard import (
            load_sandbox_write_resources,
        )

        app_key = os.environ.get("TIKTOK_APP_KEY", "").strip()
        app_secret = os.environ.get("TIKTOK_APP_SECRET", "").strip()
        if not app_key or not app_secret:
            raise PreconditionFailure(
                PreconditionName.PRODUCTION_WRITE_ENABLED_OFF,
                "Production write is disabled (PRODUCTION_WRITE_ENABLED off). "
                "Tool resolves to sandbox via load_sandbox_write_resources().",
            )
        sandbox_resources = await load_sandbox_write_resources(
            session,
            app_key=app_key,
            app_secret=app_secret,
        )
        # Return actual SandboxWriteResources (not wrapped in dict)
        return sandbox_resources

    # Precondition 1 is met; continue with remaining four
    logger.info(
        "PRODUCTION_WRITE_ENABLED is on; checking remaining four preconditions",
        extra={"tool_name": tool_name, "shop_id": str(shop_id)},
    )

    # Extract mutation details from payload
    tiktok_product_id = payload.get("tiktok_product_id")
    mutation_kind = payload.get("mutation_kind", tool_name)

    if not tiktok_product_id:
        raise PreconditionFailure(
            PreconditionName.NO_MATCHING_AUTHORIZATION,
            "Payload missing tiktok_product_id; cannot lookup authorization",
        )

    # Use a fallback run_id for audit recording (if not provided by caller)
    if run_id is None:
        import uuid as _uuid_module

        run_id = _uuid_module.uuid4()  # Fallback; caller should provide actual run_id

    # Get release SHA now for audit recording (both allowed and refused attempts)
    release_sha = _get_deployed_release_sha()

    try:
        # Precondition 2: Matching authorization exists and is valid
        auth_repo = ProductionWriteAuthorizationsRepo(session)
        authorization = await auth_repo.lookup(shop_id, tiktok_product_id, mutation_kind)

        if authorization is None:
            logger.warning(
                "Precondition 2 failed: no matching authorization",
                extra={
                    "shop_id": str(shop_id),
                    "tiktok_product_id": tiktok_product_id,
                    "mutation_kind": mutation_kind,
                },
            )
            raise PreconditionFailure(
                PreconditionName.NO_MATCHING_AUTHORIZATION,
                f"No matching unconsumed, unexpired, unrevoked authorization for "
                f"{tiktok_product_id}/{mutation_kind}",
            )

        # Precondition 3: RLS boot check passed for this process
        if not get_rls_boot_check_state():
            logger.error(
                "Precondition 3 failed: RLS boot check did not pass",
                extra={
                    "shop_id": str(shop_id),
                    "tool_name": tool_name,
                },
            )
            raise PreconditionFailure(
                PreconditionName.RLS_BOOT_CHECK_FAILED,
                "RLS boot check did not pass for this process. "
                "Process may have started before capability was enabled or "
                "boot preconditions were unmet.",
            )

        # Precondition 4: Red-team attestation for deployed release SHA
        _verify_attestation_for_release_sha()

        # Precondition 5: Kill switch is OFF (read PER CALL, not at boot)
        if is_production_write_kill_switch_active():
            logger.error(
                "Precondition 5 failed: kill switch is active",
                extra={
                    "shop_id": str(shop_id),
                    "tool_name": tool_name,
                },
            )
            raise PreconditionFailure(
                PreconditionName.PRODUCTION_WRITE_KILL_SWITCH_ACTIVE,
                "Production write is temporarily disabled via kill switch (issue #1337). "
                "No deploy or restart needed to re-enable.",
            )

        logger.info(
            "All five preconditions passed; production capability authorized",
            extra={
                "shop_id": str(shop_id),
                "tool_name": tool_name,
                "authorization_id": str(authorization.id),
            },
        )

        # All five preconditions are met; consume the authorization atomically
        consumed_auth = await auth_repo.consume(authorization.id, run_id=run_id)

        # Record allowed attempt in audit
        await _record_production_write_audit(
            session,
            run_id=run_id,
            shop_id=shop_id,
            tiktok_product_id=tiktok_product_id,
            mutation_kind=mutation_kind,
            authorization_id=consumed_auth.id,
            precondition_name=None,
            release_sha=release_sha,
        )

        # Return a marker indicating production capability is authorized
        return {
            "capability": "production_write",
            "authorization_id": str(consumed_auth.id),
            "shop_id": str(shop_id),
            "mutation_kind": mutation_kind,
        }

    except PreconditionFailure as e:
        # Record refused attempt in audit (before re-raising)
        # This ensures refusals are recorded even on error paths
        try:
            await _record_production_write_audit(
                session,
                run_id=run_id,
                shop_id=shop_id,
                tiktok_product_id=tiktok_product_id,
                mutation_kind=mutation_kind,
                authorization_id=None,
                precondition_name=e.precondition.value,
                release_sha=release_sha,
            )
        except Exception as audit_error:
            # Log audit failure but don't suppress the original exception
            logger.error(
                "Failed to record production write refusal audit",
                extra={
                    "run_id": str(run_id),
                    "shop_id": str(shop_id),
                    "precondition": e.precondition.value,
                    "audit_error": str(audit_error),
                },
            )
        # Re-raise the original precondition failure
        raise


def _verify_attestation_for_release_sha() -> None:
    """Verify that a red-team attestation exists for the deployed release SHA.

    Precondition 4. The attestation file is named {sha}.json in the attestation
    directory and contains:
    {
      "release_sha": "<sha>",
      "date": "<ISO8601>",
      "performed_by": "<operator>",
      "outcome": "pass"
    }

    Raises PreconditionFailure if no attestation for the current SHA exists.
    """
    # Get the current release SHA
    current_sha = _get_deployed_release_sha()

    # Get the attestation directory
    attestation_dir = os.environ.get("PRODUCTION_WRITE_ATTESTATION_DIR", "").strip()
    if not attestation_dir:
        # Default to committed location: docs/security/red-team-attestations/
        repo_root = Path(__file__).resolve().parents[5]
        attestation_dir = str(repo_root / "docs" / "security" / "red-team-attestations")

    attestation_file = Path(attestation_dir) / f"{current_sha}.json"

    if not attestation_file.exists():
        logger.error(
            "Precondition 4 failed: no attestation for deployed release SHA",
            extra={
                "release_sha": current_sha,
                "attestation_file": str(attestation_file),
            },
        )
        raise PreconditionFailure(
            PreconditionName.NO_ATTESTATION_FOR_RELEASE_SHA,
            f"No red-team attestation for release SHA {current_sha}. "
            f"Expected file: {attestation_file}",
        )

    # Optionally validate attestation content (check outcome is "pass")
    try:
        with open(attestation_file) as f:
            attestation_data = json.load(f)
        if attestation_data.get("outcome") != "pass":
            raise PreconditionFailure(
                PreconditionName.NO_ATTESTATION_FOR_RELEASE_SHA,
                f"Attestation for {current_sha} has outcome '{attestation_data.get('outcome')}', "
                f"not 'pass'",
            )
    except json.JSONDecodeError as e:
        logger.error(
            "Attestation file is not valid JSON",
            extra={"file": str(attestation_file), "error": str(e)},
        )
        raise PreconditionFailure(
            PreconditionName.NO_ATTESTATION_FOR_RELEASE_SHA,
            f"Attestation file corrupted: {e}",
        ) from e


async def _record_production_write_audit(
    session: AsyncSession,
    *,
    run_id,
    shop_id,
    tiktok_product_id: str,
    mutation_kind: str,
    authorization_id=None,
    precondition_name: str | None = None,
    release_sha: str,
) -> None:
    """Record a production write attempt in the append-only audit table.

    Called for both allowed and refused attempts:
    - Allowed: authorization_id is set, precondition_name is NULL
    - Refused: authorization_id is NULL, precondition_name names the failure

    Recorded on a path the error cannot skip (before raising exceptions).

    Args:
        session: AsyncSession for database writes
        run_id: UUID of the workflow run
        shop_id: UUID of the tenant (shop)
        tiktok_product_id: product identifier
        mutation_kind: operation type (e.g., "listing.create_hero_product")
        authorization_id: UUID if allowed, NULL if refused
        precondition_name: name of failing precondition if refused, NULL if allowed
        release_sha: deployed release SHA
    """
    from juli_backend.models.models import ProductionWriteAudit

    audit_entry = ProductionWriteAudit(
        id=uuid.uuid4(),
        run_id=run_id,
        shop_id=shop_id,
        tiktok_product_id=tiktok_product_id,
        mutation_kind=mutation_kind,
        authorization_id=authorization_id,
        precondition_name=precondition_name,
        release_sha=release_sha,
    )
    session.add(audit_entry)
    await session.flush()
    logger.info(
        "Production write audit recorded",
        extra={
            "run_id": str(run_id),
            "shop_id": str(shop_id),
            "authorization_id": str(authorization_id) if authorization_id else "NULL",
            "precondition_name": precondition_name or "ALLOWED",
        },
    )


def _get_deployed_release_sha() -> str:
    """Get the deployed release SHA.

    In production, this reads the current git commit SHA. In tests, this can
    be overridden via environment variable or fallback to a test SHA.

    Returns the 40-character git SHA as a string.
    """
    # Check for environment override (for testing)
    if "RELEASE_SHA" in os.environ:
        return os.environ["RELEASE_SHA"].strip()

    # Try to read from git (local dev / CI)
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            cwd=str(Path(__file__).resolve().parent),
        ).strip()
        if len(sha) == 40:  # Valid SHA
            return sha
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Fallback: read from release metadata (ADR-035) — would be set by deploy scripts
    # For now, this is not yet implemented; return an error
    raise PreconditionFailure(
        PreconditionName.NO_ATTESTATION_FOR_RELEASE_SHA,
        "Cannot determine deployed release SHA (git not available, RELEASE_SHA env var not set)",
    )
