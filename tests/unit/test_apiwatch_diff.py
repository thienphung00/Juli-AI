"""apiwatch (infra/apiwatch, D31.10): snapshot diff, Juli tagging, report."""

from __future__ import annotations

import copy
import importlib
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "infra" / "apiwatch"))

_diff = importlib.import_module("apiwatch.diff")
_report = importlib.import_module("apiwatch.report")
diff_snapshots, field_changes = _diff.diff_snapshots, _diff.field_changes
juli_titles, render, tag_juli = _report.juli_titles, _report.render, _report.tag_juli

OLD = {
    "endpoints": {
        "GET /product/202309/products/{product_id}": {
            "title": "Get Product",
            "path": "/product/202309/products/{product_id}",
            "deprecated": False,
            "scopes": ["Product Basic"],
            "request": {"path.product_id": {"type": "string", "required": True}},
            "response": {
                "data.id": {"type": "string"},
                "data.title": {"type": "string"},
                "data.skus[].price.sale_price": {"type": "string"},
            },
        },
        "GET /product/202309/brands": {
            "title": "Get Brands",
            "path": "/product/202309/brands",
            "request": {},
            "response": {},
        },
        "GET /finance/202309/statements": {
            "title": "Get Statements",
            "path": "/finance/202309/statements",
            "request": {},
            "response": {},
        },
    },
    "webhooks": {"4": {"name": "Package update", "fields": {"data.sc_type": {"type": "string"}}}},
    "changelog": {"a": {"title": "Old note", "date": "2026-01-01", "sha": "1"}},
    "sdk": {"x/sdk": {"latest": "v1.0.0", "recent": ["v1.0.0"]}},
}


def _new() -> dict:
    new = copy.deepcopy(OLD)
    product = new["endpoints"]["GET /product/202309/products/{product_id}"]
    product["response"].pop("data.title")
    product["response"]["data.skus[].price.sale_price"] = {"type": "int"}
    product["response"]["data.video"] = {"type": "object"}
    product["request"]["path.product_id"]["required"] = False
    del new["endpoints"]["GET /finance/202309/statements"]
    new["endpoints"]["POST /product/202502/products/search"] = {
        "title": "Search Products",
        "path": "/product/202502/products/search",
        "request": {},
        "response": {},
    }
    new["endpoints"]["GET /product/202309/brands"]["deprecated"] = True
    new["webhooks"]["4"]["fields"]["data.role_type"] = {"type": "string"}
    new["webhooks"]["99"] = {"name": "Brand new", "fields": {}}
    new["changelog"]["b"] = {
        "title": "Analytics changes",
        "date": "2026-10-01",
        "sha": "2",
        "deprecation": True,
        "mentions_apis": ["Get Product"],
        "mentions_paths": [],
    }
    new["changelog"]["a"]["sha"] = "9"
    new["sdk"]["x/sdk"] = {"latest": "v1.2.0", "recent": ["v1.2.0", "v1.1.0", "v1.0.0"]}
    return new


USAGE = {
    "endpoints": {"/product/202309/products/{}", "/product/202309/products/search"},
    "webhooks": {"4"},
    "planned_endpoints": set(),
    "planned_webhook_names": set(),
}


def test_field_changes_reports_added_removed_type_and_required():
    lines = field_changes(
        "response",
        {"a": {"type": "string"}, "b": {"type": "int", "required": True}},
        {"b": {"type": "string", "required": False}, "c": {"type": "bool"}},
    )
    assert lines == [
        "response + `c` (bool)",
        "response − `a`",
        "response ~ `b`: kiểu int → string, thành không bắt buộc",
    ]


def test_field_changes_accepts_compact_snapshots():
    assert field_changes("response", ["a", "b"], {"b": {"type": "int"}}) == ["response − `a`"]


def test_no_old_snapshot_means_baseline_without_changes():
    assert diff_snapshots(None, _new()) == []


def test_identical_snapshots_have_no_changes():
    assert diff_snapshots(OLD, copy.deepcopy(OLD)) == []


def test_diff_and_juli_tagging():
    new = _new()
    changes = diff_snapshots(OLD, new)
    tag_juli(changes, USAGE, titles=juli_titles(USAGE, OLD, new))
    by = {(c["section"], c["kind"], c["key"]): c for c in changes}

    product = by[("endpoints", "changed", "GET /product/202309/products/{product_id}")]
    assert product["juli"] == "used"
    assert "response − `data.title`" in product["details"]
    assert "response + `data.video` (object)" in product["details"]
    assert "response ~ `data.skus[].price.sale_price`: kiểu string → int" in product["details"]
    assert "request ~ `path.product_id`: thành không bắt buộc" in product["details"]

    search = by[("endpoints", "added", "POST /product/202502/products/search")]
    assert search["juli"] == "related"  # Juli pins /product/202309/products/search

    brands = by[("endpoints", "changed", "GET /product/202309/brands")]
    assert brands["deprecation"] is True and brands["juli"] is None

    assert by[("endpoints", "removed", "GET /finance/202309/statements")]["juli"] is None
    assert by[("webhooks", "changed", "4")]["juli"] == "used"
    assert by[("webhooks", "added", "99")]["juli"] is None
    note = by[("changelog", "added", "b")]
    assert note["juli"] == "used" and "Get Product" in note["juli_reason"]
    assert by[("changelog", "updated", "a")]["juli"] is None
    sdk = by[("sdk", "release", "x/sdk")]
    assert sdk["details"][0].startswith("v1.0.0 → v1.2.0")
    assert "v1.1.0" in sdk["details"][1]


def test_diff_order_is_deterministic():
    first = diff_snapshots(OLD, _new())
    second = diff_snapshots(copy.deepcopy(OLD), _new())
    assert [(c["section"], c["kind"], c["key"]) for c in first] == [
        (c["section"], c["kind"], c["key"]) for c in second
    ]


def test_report_lists_juli_items_first():
    new = _new()
    changes = diff_snapshots(OLD, new)
    tag_juli(changes, USAGE, titles=juli_titles(USAGE, OLD, new))
    text = render(
        "tiktok",
        changes,
        date="2026-10-12",
        errors={"sdk:y/z": "HTTP 500"},
        failed_count=2,
        kept_count=1,
        stats={"endpoints": 3},
    )
    assert text.startswith("# apiwatch · TikTok Shop · 2026-10-12")
    juli_at = text.index("## Juli dùng")
    assert juli_at < text.index("## Deprecation")
    assert juli_at < text.index("## Endpoint bị gỡ")
    assert "`sdk:y/z`: HTTP 500" in text
    assert text.index("GET /product/202309/products/{product_id}") > juli_at


def test_report_is_capped():
    changes = [
        {
            "section": "endpoints",
            "kind": "added",
            "key": f"GET /x/{i}",
            "record": {"title": "T" * 200},
            "details": [],
            "juli": None,
        }
        for i in range(2000)
    ]
    text = render("shopee", changes, date="d", errors={}, failed_count=0, kept_count=0, stats={})
    assert len(text) < 61_000
    assert "báo cáo bị cắt" in text
