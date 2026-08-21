import os

import pytest

# #1217 / ADR-075 decision 3: `workers/celery_app.py` now runs
# `assert_agent_runtime_config()` at *module import* time, whose check 5
# (SUPABASE_JWT_SECRET) is unconditional -- independent of
# AGENT_WORKFLOWS_ENABLED, which stays unset (and therefore skips every
# other check) for the whole unit-test suite by default. `celery_app` is
# imported transitively by many test modules that have nothing to do with
# auth (any test importing `workers.tasks`, which imports
# `workers.tasks.agent_workflow`, which imports `celery_app`) -- pytest
# imports every test module during collection, before any per-test
# `monkeypatch` fixture ever runs, so those modules need this set at import
# time, not test time. `setdefault` only fills the gap: any test that
# `monkeypatch.delenv("SUPABASE_JWT_SECRET", ...)` to exercise the
# missing-secret path (e.g. `test_api_main.py`,
# `test_get_current_user.py`) still removes it for that test's duration and
# `monkeypatch` restores it afterward, unaffected by this default.
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret-collection-default")


@pytest.fixture
def app_key():
    return "test_app_key_12345"


@pytest.fixture
def app_secret():
    return "test_app_secret_67890"


@pytest.fixture
def access_token():
    return "ROW_test_access_token"


@pytest.fixture
def refresh_token():
    return "ROW_test_refresh_token"


@pytest.fixture
def shop_id():
    return "shop_001"


@pytest.fixture
def tiktok_config(app_key, app_secret):
    return {
        "app_key": app_key,
        "app_secret": app_secret,
        "base_url": "https://open-api.tiktokglobalshop.com",
    }
