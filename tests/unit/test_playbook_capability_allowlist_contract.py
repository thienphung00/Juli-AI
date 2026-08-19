"""Every endpoint a playbook's READ steps reach must be permitted by the
capability that playbook runs under (issue #1189).

The defect this pins: `OPTIMIZE_PRODUCT_PLAYBOOK` offered the model
`get_seo_keywords`, but `GET /product/{v}/products/seo_words` was allowlisted
only for the sandbox merchant. A real production-read run therefore died with
`TransportGuardError` *before signing* -- the guard behaving exactly as
written, against a playbook that promised something else. Found by the #1124
live smoke, not by the suite: `ProductToolExecutor` tests use fake resources,
so no guard is ever consulted, and the guard's own tests assert the allowlist
matches itself rather than that it covers what the playbook offers.

The cross-check below closes that gap structurally. It drives the REAL
`ProductsResource` methods the READ tool handlers call, over a client double
that records the vendor path instead of sending, then asserts the real
production-read guard admits each recorded path. Nothing here restates a path
literal: the paths come out of production code, so a tool added to a playbook
without its allowlist entry fails this test rather than the next live run.
"""

from __future__ import annotations

import pytest

from juli_backend.integrations.tiktok.exceptions import TransportGuardError
from juli_backend.integrations.tiktok.guards import ReadOnlyTransportGuard
from juli_backend.integrations.tiktok.resources.products import ProductsResource
from juli_backend.services.agent.playbooks import OPTIMIZE_PRODUCT_PLAYBOOK


class _RecordingClient:
    """Captures `(method, path)` instead of talking to TikTok.

    Deliberately not a `MagicMock`: the point is to observe the exact path
    production code builds, so the recorder must be dumb and faithful.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def get(self, path: str, **_kwargs) -> dict:
        self.calls.append(("GET", path))
        return {}

    def post(self, path: str, **_kwargs) -> dict:
        self.calls.append(("POST", path))
        return {}


#: The `ProductsResource` calls each READ-classified Optimize Product tool
#: makes. Keyed by the playbook tool name so an unmapped READ tool is a
#: failure below rather than a silent omission.
_READ_TOOL_VENDOR_CALLS = {
    "get_product_information": lambda r: r.get_details("123"),
    "get_seo_keywords": lambda r: r.get_seo_words(product_ids=["123"]),
    "check_product_status": lambda r: r.get_details("123"),
    # #1208: inspect_product_image re-reads the product to resolve the hero
    # image URL server-side, so its vendor path is the same product detail GET.
    "inspect_product_image": lambda r: r.get_details("123"),
}


def _read_tool_names() -> list[str]:
    """READ-classified steps: everything the model may call without a fresh
    confirmation. CONFIRM steps are write-path and run under the sandbox
    capability instead, so they are out of scope for this contract."""
    return [
        tool
        for step in OPTIMIZE_PRODUCT_PLAYBOOK.steps
        if step.policy.value == "auto"
        for tool in step.tools
    ]


def test_every_read_tool_is_mapped_to_its_vendor_call():
    """Guards the guard: an Optimize Product READ tool with no entry in
    `_READ_TOOL_VENDOR_CALLS` would otherwise be silently unchecked, which is
    exactly how `get_seo_keywords` reached production unverified."""
    unmapped = [
        name
        for name in _read_tool_names()
        if name not in _READ_TOOL_VENDOR_CALLS and name != "upload_product_image"
    ]
    assert unmapped == [], (
        f"READ tools with no vendor-call mapping: {unmapped}. Add them here so this "
        "contract covers them, rather than discovering the gap in a live run."
    )


@pytest.mark.parametrize("tool_name", sorted(_READ_TOOL_VENDOR_CALLS))
def test_production_read_guard_admits_every_read_tools_endpoint(tool_name):
    """The regression. Each READ tool's real vendor path must pass the real
    production-read guard -- the same call `GuardedTikTokClient` makes before
    signing."""
    client = _RecordingClient()
    _READ_TOOL_VENDOR_CALLS[tool_name](ProductsResource(client))
    assert client.calls, f"{tool_name} recorded no vendor call"

    guard = ReadOnlyTransportGuard()
    for method, path in client.calls:
        try:
            guard.assert_allowed(method, path)
        except TransportGuardError as exc:
            pytest.fail(
                f"Optimize Product offers {tool_name!r}, but the production-read guard "
                f"rejects {method} {path}: {exc}. Either allowlist the endpoint in "
                "capabilities.py or remove the step from the playbook -- an agent run "
                "would die here."
            )


def test_seo_endpoints_are_admitted_for_production_read():
    """The specific #1189 entries, pinned by path so a future allowlist tidy-up
    cannot drop them without a red test."""
    guard = ReadOnlyTransportGuard()
    guard.assert_allowed("GET", "/product/202405/products/seo_words")
    guard.assert_allowed("GET", "/product/202405/products/suggestions")


def test_widening_stayed_narrow():
    """The amendment admits SEO *reads* only. A write to the same surface must
    still be rejected -- ADR-068's production-write prohibition is unchanged by
    #1189."""
    guard = ReadOnlyTransportGuard()
    for method, path in (
        ("POST", "/product/202309/products"),
        ("PUT", "/product/202309/products/123"),
        ("POST", "/product/202309/products/123/prices/update"),
    ):
        with pytest.raises(TransportGuardError):
            guard.assert_allowed(method, path)
