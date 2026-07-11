"""Hidden evaluator contract tests for issue #301 (Layer 2 sandbox write validation).

Evaluator-owned (`experiment/301-evaluator`). Not merged into, and not visible to,
either treatment branch (`experiment/301-a-no-cache`, `experiment/301-b-cache-hit`)
during their runs.

Scope is drawn from:
- GitHub issue #301 acceptance criteria (write resources unreachable from production
  factory; matches Layer 0 contracts #287/#289/#291; technical validation documented).
- Layer 0 contracts: #287 (inventory + product, `contract-collection.md` #14-18),
  #289 (promotion lifecycle, #20-23 -- paths TBD), #291 (fulfillment ship/package,
  #29-41).
- `docs/handoffs/phase-2-tiktok-implementation.md`: "Sandbox write success | Technical
  validation (signing, parse, auth) -- business failures OK".

Design principle -- externally observable contracts, not internal structure:
- Isolation and signing/parsing tests operate purely at the `SandboxWriteClientFactory`
  / `ProductionReadClientFactory` + guarded-client boundary, using the exact write-path
  allowlist already committed in `capabilities.py` (`SANDBOX_ALLOWED_REQUESTS`). No path
  is invented here.
- The one new integration point these tests require is `SandboxWriteClientFactory
  .create_resources(config)`, mirroring the sibling `ProductionReadClientFactory
  .create_resources()` convention already present in `factories.py`. The four resource
  group names asserted (`inventory`, `products`, `fulfillment`) are the operation
  categories issue #301 names verbatim ("inventory update, product publish/edit,
  ... fulfillment ship/package"), not guessed internal class names.
- `promotions` (Layer 0 #289) is treated as optional: contract-collection.md #20-23
  paths are still "TBD from Promotion API Testing Tool". Tests skip gracefully rather
  than assert a specific path, per "preserve legitimate flexibility where Layer 0 paths
  remain TBD; do not invent vendor contracts."

Technical-success classification used throughout:
- A response with HTTP 200, valid JSON, and a *typed* TikTok error (any non-zero
  `code` mapped by `error_from_response`) is a **business failure on sparse sandbox
  data** and counts as **technical success** -- signing, transport, and parsing all
  worked.
- A raised `requests.HTTPError` (bad HTTP status) or a JSON-decode failure is a
  **malformed transport/parsing failure** and must never be swallowed or reinterpreted
  as success.

No live network access: every test replaces `client._session` with a `MagicMock`
before any request is issued. No real TikTok credentials are used anywhere in this
file -- `app_key`/`app_secret`/`access_token` are fixed placeholder strings.
"""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from unittest.mock import MagicMock

import pytest

from juli_backend.integrations.tiktok.capabilities import (
    PRODUCTION_AUTH_ID,
    SANDBOX_ALLOWED_REQUESTS,
    SANDBOX_AUTH_ID,
    MerchantCapability,
)
from juli_backend.integrations.tiktok.constants import product_inventory_update_path
from juli_backend.integrations.tiktok.exceptions import (
    ResourceNotFoundError,
    TransportGuardError,
)
from juli_backend.integrations.tiktok.factories import (
    ClientFactoryConfig,
    ProductionReadClientFactory,
    ProductionReadResources,
    SandboxWriteClientFactory,
)
from juli_backend.integrations.tiktok.signing import sign_request

PRODUCT_ID = "1736363193934775939"
SKU_ID = "1736404513645233795"
PACKAGE_ID = "1153486604836964618"

# Concrete request instances for the write-path guard allowlist. Each entry supplies
# a real path (derived by substituting a dummy numeric id into the allowlisted regex
# pattern) plus a representative body. These are the exact patterns already committed
# in `capabilities.py::SANDBOX_ALLOWED_REQUESTS` -- nothing here is an invented path.
_WRITE_PATH_SAMPLES: list[tuple[str, str, dict]] = [
    ("POST", product_inventory_update_path(PRODUCT_ID), {"skus": []}),
    ("POST", "/product/202309/products", {"title": "x"}),
    ("PUT", f"/product/202309/products/{PRODUCT_ID}", {"title": "x"}),
    ("POST", "/product/202309/images/upload", {}),
    ("POST", "/fulfillment/202309/packages/combine", {"combinable_packages": []}),
    ("POST", f"/fulfillment/202309/packages/{PACKAGE_ID}/ship", {}),
    ("POST", "/fulfillment/202309/packages/ship", {"package_id": [PACKAGE_ID]}),
    ("POST", "/fulfillment/202309/orders/9999/split", {}),
    ("POST", f"/fulfillment/202309/packages/{PACKAGE_ID}/uncombine", {}),
    ("POST", "/return_refund/202602/cancellations/9999/approve", {}),
    ("POST", "/return_refund/202602/cancellations/9999/reject", {}),
    ("POST", "/return_refund/202602/returns/9999/approve", {}),
    ("POST", "/return_refund/202602/returns/9999/reject", {}),
    ("POST", "/supply_chain/202309/packages/sync", {}),
]


def _assert_matches_some_allowlist_pattern(method: str, path: str) -> None:
    """Guard the guard: every sample path used below must be a real allowlist entry."""
    assert any(
        allowed_method == method and pattern.match(path)
        for allowed_method, pattern in SANDBOX_ALLOWED_REQUESTS
    ), f"{method} {path} is not in capabilities.SANDBOX_ALLOWED_REQUESTS"


@pytest.fixture(autouse=True)
def _block_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if any test path reaches real HTTP transport."""

    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Hidden contract tests must never perform a real HTTP call")

    monkeypatch.setattr("requests.Session.request", _forbidden)


@pytest.fixture
def production_config() -> ClientFactoryConfig:
    return ClientFactoryConfig(
        app_key="app-key",
        app_secret="app-secret",
        access_token="access-token",
        merchant_auth_id=PRODUCTION_AUTH_ID,
        shop_cipher="ROW_fujiwacipher1234",
    )


@pytest.fixture
def sandbox_config() -> ClientFactoryConfig:
    return ClientFactoryConfig(
        app_key="app-key",
        app_secret="app-secret",
        access_token="access-token",
        merchant_auth_id=SANDBOX_AUTH_ID,
        shop_cipher="ROW_sandboxcipher123",
    )


def _mock_success(session_attr: MagicMock, data: dict) -> None:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"code": 0, "data": data, "message": "Success"}
    session_attr.return_value = resp


def _mock_business_failure(session_attr: MagicMock, code: int, message: str) -> None:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"code": code, "message": message, "request_id": "req-1"}
    session_attr.return_value = resp


def _mock_malformed_json(session_attr: MagicMock) -> None:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.side_effect = json.JSONDecodeError("Expecting value", "", 0)
    session_attr.return_value = resp


# ---------------------------------------------------------------------------
# 1. Production factory cannot construct, expose, sign, or send sandbox writes
# ---------------------------------------------------------------------------


class TestProductionFactoryCannotReachSandboxWrites:
    @pytest.mark.parametrize("method,path,body", _WRITE_PATH_SAMPLES)
    def test_production_client_rejects_every_sandbox_write_path_before_signing(
        self,
        production_config: ClientFactoryConfig,
        method: str,
        path: str,
        body: dict,
    ) -> None:
        _assert_matches_some_allowlist_pattern(method, path)
        client = ProductionReadClientFactory().create(production_config)
        client._session = MagicMock()

        call = client.post if method == "POST" else getattr(client, method.lower(), None)
        if call is None:
            # TikTokClient has no verb method for this yet (e.g. PUT) -- that is
            # itself proof production transport cannot reach it: there is no code
            # path on the production-read client capable of emitting this request.
            assert not hasattr(client, method.lower())
            return

        with pytest.raises(TransportGuardError):
            call(path, body=body) if method == "POST" else call(path)

        client._session.post.assert_not_called()
        client._session.get.assert_not_called()

    def test_production_resources_bundle_has_no_write_capable_fields(self) -> None:
        assert is_dataclass(ProductionReadResources)
        field_names = {f.name for f in fields(ProductionReadResources)}
        forbidden = {"inventory", "fulfillment", "promotions"}
        assert not (field_names & forbidden), (
            "ProductionReadResources must never expose sandbox write-only resource "
            f"groups; found {field_names & forbidden}"
        )

    def test_production_factory_capability_is_always_production_read(
        self, production_config: ClientFactoryConfig
    ) -> None:
        client = ProductionReadClientFactory().create(production_config)
        assert client._capability == MerchantCapability.PRODUCTION_READ


# ---------------------------------------------------------------------------
# 2. Sandbox resources reachable only through SandboxWriteClientFactory
# ---------------------------------------------------------------------------


class TestSandboxReachableOnlyViaFactory:
    def test_create_resources_rejects_fujiwa_auth_id_before_any_network_activity(
        self, sandbox_config: ClientFactoryConfig
    ) -> None:
        wrong_config = ClientFactoryConfig(
            app_key=sandbox_config.app_key,
            app_secret=sandbox_config.app_secret,
            access_token=sandbox_config.access_token,
            merchant_auth_id=PRODUCTION_AUTH_ID,
            shop_cipher=sandbox_config.shop_cipher,
        )
        with pytest.raises(ValueError, match="SANDBOX_VN"):
            SandboxWriteClientFactory().create_resources(wrong_config)

    def test_create_resources_exposes_required_operation_groups(
        self, sandbox_config: ClientFactoryConfig
    ) -> None:
        resources = SandboxWriteClientFactory().create_resources(sandbox_config)
        for group in ("inventory", "products", "fulfillment"):
            assert hasattr(resources, group), (
                f"SandboxWriteClientFactory.create_resources() must expose `{group}` "
                "per issue #301's named operation categories"
            )

    @pytest.mark.parametrize("group", ["inventory", "products", "fulfillment"])
    def test_each_resource_group_is_wired_to_the_sandbox_guarded_client(
        self, sandbox_config: ClientFactoryConfig, group: str
    ) -> None:
        resources = SandboxWriteClientFactory().create_resources(sandbox_config)
        resource = getattr(resources, group)
        underlying_client = getattr(resource, "_client", None)
        assert underlying_client is not None
        assert underlying_client._capability == MerchantCapability.SANDBOX_WRITE
        assert underlying_client._merchant_auth_id == SANDBOX_AUTH_ID


# ---------------------------------------------------------------------------
# 3. Inventory update contract (Layer 0 #287, contract-collection.md #14 -- verified)
# ---------------------------------------------------------------------------


class TestInventoryUpdateContract:
    def test_update_sends_verified_method_path_and_correctly_signed_request(
        self, sandbox_config: ClientFactoryConfig
    ) -> None:
        resources = SandboxWriteClientFactory().create_resources(sandbox_config)
        client = resources.inventory._client
        client._session = MagicMock()
        _mock_success(client._session.post, {})

        resources.inventory.update(
            product_id=PRODUCT_ID,
            sku_id=SKU_ID,
            warehouse_id="7657265511696664340",
            quantity=15,
        )

        assert client._session.post.called
        _call = client._session.post.call_args
        sent_url = _call.args[0] if _call.args else _call.kwargs["url"]
        assert sent_url.endswith(product_inventory_update_path(PRODUCT_ID))
        sent_params = _call.kwargs["params"]
        expected_sign = sign_request(
            app_secret=sandbox_config.app_secret,
            path=product_inventory_update_path(PRODUCT_ID),
            params={k: v for k, v in sent_params.items() if k != "sign"},
            body=json.dumps(_call.kwargs["json"], separators=(",", ":"), sort_keys=True),
        )
        assert sent_params["sign"] == expected_sign

    def test_sparse_sandbox_business_failure_is_technical_success(
        self, sandbox_config: ClientFactoryConfig
    ) -> None:
        """A well-formed 100004 (not-found) response on sparse sandbox data proves
        signing/transport/parsing all worked -- this must raise the typed exception,
        not swallow it or masquerade as success."""
        resources = SandboxWriteClientFactory().create_resources(sandbox_config)
        client = resources.inventory._client
        client._session = MagicMock()
        _mock_business_failure(client._session.post, 100004, "product not found")

        with pytest.raises(ResourceNotFoundError) as exc_info:
            resources.inventory.update(
                product_id=PRODUCT_ID,
                sku_id=SKU_ID,
                warehouse_id="7657265511696664340",
                quantity=15,
            )
        assert exc_info.value.code == 100004
        assert exc_info.value.request_id == "req-1"

    def test_malformed_json_response_is_not_technical_success(
        self, sandbox_config: ClientFactoryConfig
    ) -> None:
        resources = SandboxWriteClientFactory().create_resources(sandbox_config)
        client = resources.inventory._client
        client._session = MagicMock()
        _mock_malformed_json(client._session.post)

        with pytest.raises(json.JSONDecodeError):
            resources.inventory.update(
                product_id=PRODUCT_ID,
                sku_id=SKU_ID,
                warehouse_id="7657265511696664340",
                quantity=15,
            )


# ---------------------------------------------------------------------------
# 4. Product publish/edit contract (Layer 0 #287, #17 verified / #18 path stated)
# ---------------------------------------------------------------------------


class TestProductPublishEditContract:
    def test_create_uses_verified_path_and_parses_verified_response_shape(
        self, sandbox_config: ClientFactoryConfig
    ) -> None:
        resources = SandboxWriteClientFactory().create_resources(sandbox_config)
        client = resources.products._client
        client._session = MagicMock()
        _mock_success(
            client._session.post,
            {
                "product_id": "1736405947247986307",
                "skus": [{"id": "1736405690908575363", "seller_sku": "water-bottle-100ml"}],
                "warnings": [],
            },
        )

        result = resources.products.create(
            title="Premium Stainless Steel Water Bottle 750ml",
            description="Durable Stainless Water Bottle for everyday use",
            category_id="605254",
            skus=[{"seller_sku": "water-bottle-100ml"}],
        )

        _call = client._session.post.call_args
        sent_url = _call.args[0] if _call.args else _call.kwargs["url"]
        assert sent_url.endswith("/product/202309/products")
        assert result.get("product_id") == "1736405947247986307"

    def test_edit_uses_put_method_and_verified_path(
        self, sandbox_config: ClientFactoryConfig
    ) -> None:
        """Layer 0 #287 states `PUT /product/202309/products/{product_id}` for edit
        (contract-collection.md #18) but has no captured cURL/response demo. Only the
        method + path are asserted here; body shape is intentionally left flexible."""
        resources = SandboxWriteClientFactory().create_resources(sandbox_config)
        client = resources.products._client
        client._session = MagicMock()
        _mock_success(client._session.put, {"product_id": PRODUCT_ID})

        resources.products.edit(product_id=PRODUCT_ID, title="Updated title")

        assert client._session.put.called
        _call = client._session.put.call_args
        sent_url = _call.args[0] if _call.args else _call.kwargs["url"]
        assert sent_url.endswith(f"/product/202309/products/{PRODUCT_ID}")

    def test_edit_sparse_business_failure_is_technical_success(
        self, sandbox_config: ClientFactoryConfig
    ) -> None:
        resources = SandboxWriteClientFactory().create_resources(sandbox_config)
        client = resources.products._client
        client._session = MagicMock()
        _mock_business_failure(client._session.put, 100004, "product not found")

        with pytest.raises(ResourceNotFoundError):
            resources.products.edit(product_id=PRODUCT_ID, title="Updated title")


# ---------------------------------------------------------------------------
# 5. Promotion lifecycle -- Layer 0 #289 paths remain TBD; preserve flexibility
# ---------------------------------------------------------------------------


class TestPromotionLifecycleDeferredUntilVerified:
    def test_no_promotion_path_is_allowlisted_yet(self) -> None:
        """contract-collection.md #20-23 (createActivity, updateActivityProduct,
        searchActivity, deactivateActivity) are all `**TBD from Promotion API Testing
        Tool**`. No promotion path should appear in the sandbox write allowlist until
        a Layer 0 contract verifies it -- this is not a #301 regression, it is the
        expected state either before or after #301 as long as #289 stays TBD."""
        for _method, pattern in SANDBOX_ALLOWED_REQUESTS:
            assert "promotion" not in pattern.pattern, (
                f"Unverified promotion path {pattern.pattern} must not be allowlisted "
                "until Layer 0 (#289) confirms it"
            )

    def test_promotion_resource_group_is_optional_until_layer0_verified(
        self, sandbox_config: ClientFactoryConfig
    ) -> None:
        resources = SandboxWriteClientFactory().create_resources(sandbox_config)
        if not hasattr(resources, "promotions"):
            pytest.skip(
                "Promotion lifecycle (#289) paths are still TBD in "
                "contract-collection.md #20-23 -- deferring is legitimate flexibility, "
                "not a failure."
            )
        # If a treatment chooses to implement it anyway, it must only ever use paths
        # that are actually in the allowlist -- never an invented one.
        client = resources.promotions._client
        client._session = MagicMock()
        _mock_success(client._session.post, {})
        resources.promotions.create_activity(title="x", begin_time=0, end_time=0)
        _call = client._session.post.call_args
        sent_url = _call.args[0] if _call.args else _call.kwargs["url"]
        used_path = sent_url.split("?", 1)[0]
        for base_url_prefix in ("https://open-api.tiktokglobalshop.com",):
            used_path = used_path.removeprefix(base_url_prefix)
        _assert_matches_some_allowlist_pattern("POST", used_path)


# ---------------------------------------------------------------------------
# 6. Fulfillment package/ship contract (Layer 0 #291, paths stated / body TBD)
# ---------------------------------------------------------------------------


class TestFulfillmentPackageShipContract:
    def test_ship_package_uses_verified_path(self, sandbox_config: ClientFactoryConfig) -> None:
        resources = SandboxWriteClientFactory().create_resources(sandbox_config)
        client = resources.fulfillment._client
        client._session = MagicMock()
        _mock_success(client._session.post, {})

        resources.fulfillment.ship_package(package_id=PACKAGE_ID)

        sent_url_call = client._session.post.call_args
        sent_url = sent_url_call.args[0] if sent_url_call.args else sent_url_call.kwargs["url"]
        assert sent_url.endswith(f"/fulfillment/202309/packages/{PACKAGE_ID}/ship")

    def test_combine_packages_uses_verified_path(
        self, sandbox_config: ClientFactoryConfig
    ) -> None:
        resources = SandboxWriteClientFactory().create_resources(sandbox_config)
        client = resources.fulfillment._client
        client._session = MagicMock()
        _mock_success(client._session.post, {})

        resources.fulfillment.combine_packages(package_ids=[PACKAGE_ID, "other-id"])

        sent_url_call = client._session.post.call_args
        sent_url = sent_url_call.args[0] if sent_url_call.args else sent_url_call.kwargs["url"]
        assert sent_url.endswith("/fulfillment/202309/packages/combine")

    def test_confirm_shipment_uses_supply_chain_path(
        self, sandbox_config: ClientFactoryConfig
    ) -> None:
        """contract-collection.md #39: Confirm Package Shipment moved from the
        Fulfillment API to the Supply Chain API -- `POST /supply_chain/202309/
        packages/sync`. This is a deliberately unusual path to catch an
        implementation that assumes every fulfillment operation stays under
        `/fulfillment/`."""
        resources = SandboxWriteClientFactory().create_resources(sandbox_config)
        client = resources.fulfillment._client
        client._session = MagicMock()
        _mock_success(client._session.post, {})

        resources.fulfillment.confirm_shipment(package_id=PACKAGE_ID)

        sent_url_call = client._session.post.call_args
        sent_url = sent_url_call.args[0] if sent_url_call.args else sent_url_call.kwargs["url"]
        assert sent_url.endswith("/supply_chain/202309/packages/sync")

    def test_sparse_business_failure_on_ship_is_technical_success(
        self, sandbox_config: ClientFactoryConfig
    ) -> None:
        resources = SandboxWriteClientFactory().create_resources(sandbox_config)
        client = resources.fulfillment._client
        client._session = MagicMock()
        _mock_business_failure(client._session.post, 100004, "package not found")

        with pytest.raises(ResourceNotFoundError):
            resources.fulfillment.ship_package(package_id=PACKAGE_ID)

    def test_malformed_response_on_ship_is_not_technical_success(
        self, sandbox_config: ClientFactoryConfig
    ) -> None:
        resources = SandboxWriteClientFactory().create_resources(sandbox_config)
        client = resources.fulfillment._client
        client._session = MagicMock()
        _mock_malformed_json(client._session.post)

        with pytest.raises(json.JSONDecodeError):
            resources.fulfillment.ship_package(package_id=PACKAGE_ID)


# ---------------------------------------------------------------------------
# 7. No Fujiwa credential or production capability can enter write validation
# ---------------------------------------------------------------------------


class TestNoProductionCredentialEntersSandboxWriteValidation:
    def test_sandbox_factory_never_accepts_production_credentials_by_shape(
        self, production_config: ClientFactoryConfig
    ) -> None:
        """Even if every other field looks like a valid sandbox config, the Fujiwa
        merchant_auth_id alone must be sufficient to reject construction."""
        with pytest.raises(ValueError, match="SANDBOX_VN"):
            SandboxWriteClientFactory().create(production_config)

    def test_guarded_client_capability_never_silently_downgrades(
        self, sandbox_config: ClientFactoryConfig
    ) -> None:
        resources = SandboxWriteClientFactory().create_resources(sandbox_config)
        for group in ("inventory", "products", "fulfillment"):
            client = getattr(resources, group)._client
            assert client._capability is MerchantCapability.SANDBOX_WRITE
            assert client._capability is not MerchantCapability.PRODUCTION_READ
