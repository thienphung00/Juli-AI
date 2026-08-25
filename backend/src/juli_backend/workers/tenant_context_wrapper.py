"""Celery task wrapper that sets tenant context from workflow run.

Issue #1327, ADR-085 decision 2: for Celery tasks, resolves the run's shop
and sets tenant context so that database operations automatically apply
SET LOCAL GUCs.

Fail-closed: if the run cannot be resolved, raises a named error BEFORE
any SQL execution, with no fallback to default/reference shops.
"""

import logging
import uuid
from collections.abc import Callable
from typing import Any

from juli_backend.database import set_tenant_context
from juli_backend.database.database import ensure_worker_session_factory, get_async_database_url
from juli_backend.models.models import WorkflowRun

logger = logging.getLogger(__name__)


class TenantContextTaskError(RuntimeError):
    """Raised when a Celery task cannot resolve its tenant context."""

    pass


async def resolve_task_tenant_context(run_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """Resolve shop_id and user_id from a workflow run.

    Used by Celery tasks to set tenant context before executing, failing
    closed if the run cannot be resolved.

    Args:
        run_id: The workflow run ID

    Returns:
        (shop_id, user_id) tuple

    Raises:
        TenantContextTaskError: If the run or its product cannot be resolved
    """
    factory = ensure_worker_session_factory(get_async_database_url())

    async with factory() as session:
        run = await session.get(WorkflowRun, run_id)
        if run is None:
            raise TenantContextTaskError(
                f"Cannot resolve tenant context: workflow_runs row not found for "
                f"run_id={run_id}. Task fails closed (no fallback to default shop)."
            )

        # The run should have a shop_id set (from the approval path or enqueue)
        if not run.shop_id:
            raise TenantContextTaskError(
                f"Cannot resolve tenant context: workflow_runs row missing shop_id "
                f"for run_id={run_id}. Task fails closed."
            )

        return run.shop_id, run.user_id or uuid.uuid4()  # User ID might be None for anonymous


def task_with_tenant_context(run_id_param: str = "run_id") -> Callable:
    """Decorator that sets tenant context for a Celery task from its run_id param.

    Usage:
        @app.task
        @task_with_tenant_context()
        async def my_task(run_id, other_param):
            # Tenant context is automatically set; database operations use SET LOCAL
            await session.execute(...)

    Args:
        run_id_param: Name of the parameter containing the run_id (default: "run_id")
    """

    def decorator(func: Callable) -> Callable:
        async def wrapper(*args, **kwargs) -> Any:
            # Extract run_id from kwargs or positional args
            if run_id_param in kwargs:
                run_id = kwargs[run_id_param]
            elif args:
                # Try to use first argument as run_id if not in kwargs
                run_id = args[0]
            else:
                raise TenantContextTaskError(f"Cannot find {run_id_param} in task args or kwargs")

            # Resolve tenant context from the run
            try:
                if isinstance(run_id, str):
                    run_id = uuid.UUID(run_id)
                shop_id, user_id = await resolve_task_tenant_context(run_id)
                set_tenant_context(shop_id, user_id)
            except TenantContextTaskError:
                raise  # Re-raise fail-closed errors
            except Exception as e:
                logger.error(
                    "task_tenant_context_error", extra={"run_id": str(run_id), "error": str(e)}
                )
                raise TenantContextTaskError(
                    f"Error resolving tenant context for run_id={run_id}: {e}"
                )

            # Execute the actual task
            return await func(*args, **kwargs)

        return wrapper

    return decorator
