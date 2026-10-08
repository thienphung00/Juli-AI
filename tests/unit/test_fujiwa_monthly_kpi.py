"""Pure KPI analysis in scripts/fujiwa_monthly_kpi_and_diagnosis.py."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "fujiwa_monthly_kpi_and_diagnosis.py"
_spec = importlib.util.spec_from_file_location("fujiwa_monthly_kpi_and_diagnosis", _SCRIPT)
assert _spec is not None and _spec.loader is not None
kpi = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = kpi
_spec.loader.exec_module(kpi)


def _row(orders: int, gmv: object, clicks: int, impressions: int) -> dict:
    return {
        "id": "p1",
        "total_performance": {
            "sku_orders": orders,
            "items_sold": orders * 2,
            "gmv": gmv,
            "product_clicks": clicks,
            "product_impressions": impressions,
            "add_cart_count": clicks // 10,
            "refunds": {"amount": "50", "currency": "VND"},
        },
        "seller_product_card_performance": {
            "product_impressions": 800,
            "product_clicks": 40,
            "attributed_sku_orders": 4,
            "attributed_gmv": {"amount": "400", "currency": "VND"},
        },
        "shop_tab_performance": {
            "shop_tab_product_impressions": 200,
            "shop_tab_product_clicks": 10,
            "shop_tab_ctor_sku": "0.2",
            "shop_tab_gmv": "100",
        },
    }


def test_window_metrics_handles_dict_and_string_money():
    m = kpi.window_metrics(_row(30, {"amount": "3000", "currency": "VND"}, 300, 10000))
    assert m["orders_per_day"] == Decimal(1)
    assert m["aov"] == Decimal(100)
    assert m["items_per_order"] == Decimal(2)
    assert m["ctr"] == Decimal("0.03")
    assert m["ctor"] == Decimal("0.1")
    assert m["add_to_cart_rate"] == Decimal("0.1")
    # card block: clicks 40 + 10, orders 4 + 10*0.2, impressions 800 + 200
    assert m["card_ctr"] == Decimal("0.05")
    assert m["card_ctor"] == Decimal("6") / Decimal("50")
    assert kpi.window_metrics(_row(30, "3000", 300, 10000))["aov"] == Decimal(100)


def test_compare_reports_abs_and_pct_change():
    cur = _row(60, {"amount": "7200", "currency": "VND"}, 400, 10000)
    prev = _row(30, "3000", 300, 10000)
    entry = kpi.build_report(["p1"], {"products": [cur]}, [prev])[0]
    assert entry["current"]["aov"] == Decimal(120)
    assert entry["change"]["aov"]["abs"] == Decimal(20)
    assert entry["change"]["aov"]["pct"] == Decimal(20)
    assert entry["change"]["ctor"]["abs"] == Decimal("0.15") - Decimal("0.1")
    assert entry["change"]["orders_per_day"]["pct"] == Decimal(100)


def test_missing_window_gives_none_not_crash():
    entry = kpi.build_report(["p9"], {"products": []}, {"products": []})[0]
    assert entry["current"]["aov"] is None
    assert entry["change"]["aov"] == {"abs": None, "pct": None}


def test_diagnosis_rows_truncate_how_to_solve():
    payload = {
        "data": {
            "products": [
                {
                    "id": "p1",
                    "diagnoses": [
                        {
                            "field": "TITLE",
                            "diagnosis_results": [
                                {"code": "T1", "how_to_solve": "x" * 300, "quality_tier": "POOR"}
                            ],
                        }
                    ],
                }
            ]
        }
    }
    rows = kpi.diagnosis_rows(payload)
    assert rows[0]["field"] == "TITLE" and len(rows[0]["how_to_solve"]) == 120


def test_analyse_replay_writes_outputs(tmp_path: Path):
    import json

    (tmp_path / "a34_30d_current.json").write_text(
        json.dumps({"products": [_row(30, "3000", 300, 10000)]})
    )
    (tmp_path / "diagnoses_error.json").write_text(
        json.dumps({"error_class": "TikTokAPIError", "message": "scope"})
    )
    kpi.analyse(tmp_path, date(2026, 10, 6), ["p1"])
    assert "Diagnoses unavailable" in (tmp_path / "monthly_kpi.md").read_text()
    assert (
        json.loads((tmp_path / "monthly_kpi.json").read_text())["products"][0]["product_id"] == "p1"
    )
