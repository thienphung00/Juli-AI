import pytest


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
