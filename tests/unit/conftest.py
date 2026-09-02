import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.database.database import Base


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def token_encryption_key(monkeypatch):
    monkeypatch.setenv("TIKTOK_TOKEN_ENCRYPTION_KEY", "unit-test-token-encryption-key")


@pytest_asyncio.fixture(autouse=True)
async def reset_shared_redis_clients_for_unit_tests():
    """Close process-lifetime Redis singletons between tests (#631).

    In CI, REDIS_URL points at a real redis:7 service container, so
    get_shared_redis_client() creates a real asyncio client bound to
    whatever event loop is active during the test that first calls it.
    pytest-asyncio's default event loop is function-scoped, so without
    this cleanup a later test reusing the module-level singleton hits
    "Future attached to a different loop" / "Event loop is closed" —
    only reproduces where REDIS_URL is set (CI), never locally without
    a Redis service running.
    """
    yield
    from juli_backend.services.analytics_kpi_cache import (
        close_shared_redis_client as close_analytics_kpi_redis,
    )
    from juli_backend.services.gold_kpi_cache import (
        close_shared_redis_client as close_gold_kpi_redis,
    )

    await close_gold_kpi_redis()
    await close_analytics_kpi_redis()


@pytest.fixture(autouse=True)
def bind_celery_dispatchers_for_unit_tests():
    """Wire MMU-6/7 worker bindings so unit tests can run the execution worker."""
    from juli_backend.services.action_cards.dispatch import set_refresh_dispatcher
    from juli_backend.services.execution.dispatch import set_task_dispatcher
    from juli_backend.services.execution.outcome_port import (
        set_workflow_outcome_recorder,
    )
    from juli_backend.workers.dispatch_binding import bind_celery_dispatchers

    bind_celery_dispatchers()
    yield
    set_refresh_dispatcher(None)
    set_task_dispatcher(None)
    set_workflow_outcome_recorder(None)


@pytest.fixture(autouse=True)
def bind_agent_abuse_limit_gate_for_unit_tests():
    """Default to a generous in-memory gate (ADR-075 decision 4, #1223) so
    every OTHER agent-run route test (approve, confirmations, SSE events)
    keeps passing without opting in explicitly -- unlike the refresh
    cooldown gate below (exercised by exactly one dedicated test file), the
    approve/confirmations/events routes are exercised pervasively across
    many other test files (#1222, #1224, #1128/AGT-W3B and their
    descendants), so this mirrors `bind_celery_dispatchers_for_unit_tests`'
    "safe permissive default" shape rather than
    `reset_action_card_refresh_cooldown_gate_for_unit_tests`'
    "leave unbound" shape. Tests that specifically exercise abuse-limit
    exhaustion (`test_agent_abuse_limits_routes.py`,
    `test_agent_abuse_limits_gate.py`) bind their own tight gate mid-test,
    which simply overwrites this default for the rest of that test.
    """
    from juli_backend.services.agent.abuse_limits import (
        InMemoryAbuseLimitGate,
        set_agent_abuse_limit_gate,
    )

    set_agent_abuse_limit_gate(
        InMemoryAbuseLimitGate(
            approve_max_requests=100_000,
            approve_burst_max_requests=100_000,
            confirmation_max_requests=100_000,
            sse_max_concurrent=100_000,
        )
    )
    yield
    set_agent_abuse_limit_gate(None)


@pytest.fixture(autouse=True)
def reset_action_card_refresh_cooldown_gate_for_unit_tests():
    """Leave the #899 per-shop refresh cooldown gate unbound by default.

    Deliberately does NOT auto-bind a gate: production fails closed when
    nothing is bound (see refresh_cooldown.get_refresh_cooldown_gate), and
    tests that exercise POST /v1/action-cards/refresh must opt in to a gate
    explicitly, the same way they opt in to a mock Celery dispatcher.
    """
    yield
    from juli_backend.services.action_cards.refresh_cooldown import (
        set_refresh_cooldown_gate,
    )

    set_refresh_cooldown_gate(None)


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        execution_options={
            "schema_translate_map": {
                "ops": None,
                "bronze": None,
                "gold": None,
                "silver": None,
            }
        },
    )

    def _create_tables(sync_conn):
        Base.metadata.create_all(sync_conn)

    async with eng.begin() as conn:
        await conn.run_sync(_create_tables)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as sess:
        yield sess
        await sess.rollback()


@pytest.fixture
def user_id():
    return uuid.uuid4()


@pytest.fixture
def other_user_id():
    return uuid.uuid4()


@pytest.fixture(autouse=True)
def _no_live_vendor_identity_lookup(monkeypatch):
    """A unit test must never call TikTok's authorization endpoint (#1200).

    Provisioning verifies a credential's real merchant against
    `GET /authorization/{v}/shops` before storing it. Left unstubbed, every test
    that exercises the OAuth callback issues a REAL HTTPS request to the live
    Partner API -- observed returning `36009004 Invalid app_key` for
    `app_key=test_app_key`. That makes the suite depend on an external service
    being reachable, and would leak test traffic to the vendor.

    Autouse so the guarantee cannot be forgotten by a new test. A test that
    genuinely wants to exercise the lookup overrides `resolve_authorized_shop`
    itself (see `test_credential_binding.py`), which takes precedence.

    Distinct cipher per call: a fixed value would make two capabilities collide
    and trip the distinctness invariant in tests that provision more than one.
    """
    import itertools

    counter = itertools.count()

    def _fake_resolve(*, app_key: str, app_secret: str, access_token: str) -> dict:
        n = next(counter)
        return {"id": f"stub-shop-{n}", "cipher": f"ROW_stub_cipher_{n}", "name": "Stub Shop"}

    monkeypatch.setattr(
        "juli_backend.services.tiktok.credential_binding.resolve_authorized_shop",
        _fake_resolve,
        raising=False,
    )


# ---------------------------------------------------------------------------
# Tenant + API fixtures (tests/support). A module that needs a different shape
# defines its own fixture of the same name; pytest's nearest definition wins.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def tenant(session):
    """``(user, shop)`` -- one seller and the shop they own."""
    from tests.support.builders import make_tenant

    return await make_tenant(session)


@pytest_asyncio.fixture
async def shop(tenant):
    return tenant[1]


@pytest_asyncio.fixture
async def app(session):
    """The real app with every route's session dependency yielding ``session``."""
    from tests.support.api import build_app

    application = build_app(session)
    yield application
    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_client(app, tenant):
    """An ``httpx.AsyncClient`` acting as the tenant's user on the tenant's shop."""
    from tests.support.api import authenticate, client_for

    user, shop = tenant
    authenticate(app, user=user, shop=shop)
    async with client_for(app) as client:
        yield client
