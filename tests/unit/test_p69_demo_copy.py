"""P69: short product names, no internal SKU, no raw English KPI key on a decision card."""

from __future__ import annotations

import pytest

from juli_backend.services.demo_decisions import card_view
from juli_backend.services.product_name import (
    is_seller_visible_sku,
    short_product_name,
)
from juli_backend.services.reviewer import create_product_card, create_promotion_card


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (
            "Nồi lẩu điện mini 1.5L có nắp kính, tay cầm tiện dụng (dùng nấu lẩu, mì, súp)",
            "Nồi lẩu điện mini 1.5L có nắp kính…",
        ),
        ("Bình Nước Thép Không Gỉ Chính Hãng 750ml", "Bình Nước Thép Không Gỉ Chính Hãng 750ml"),
        (
            "Áo thun nam cổ tròn cotton thoáng mát co giãn 4 chiều form rộng",
            "Áo thun nam cổ tròn cotton thoáng mát co…",
        ),
        ("  Bình   giữ nhiệt (cao cấp) ", "Bình giữ nhiệt"),
        (None, ""),
    ],
)
def test_short_product_name(name: str | None, expected: str) -> None:
    assert short_product_name(name) == expected
    assert len(short_product_name(name)) <= 41


@pytest.mark.parametrize(
    ("sku", "visible"),
    [("JULI-F7B54199", False), ("juli-1234", False), ("", False), (None, False), ("SM-012", True)],
)
def test_internal_juli_sku_is_never_shown(sku: str | None, visible: bool) -> None:
    assert is_seller_visible_sku(sku) is visible


def test_headings_of_generated_cards_use_the_short_name_without_guillemets() -> None:
    title = "Nồi lẩu điện mini 1.5L có nắp kính, tay cầm tiện dụng (dùng nấu lẩu, mì, súp)"
    assert create_promotion_card.card_title(title) == (
        "Tạo khuyến mãi giảm giá cho Nồi lẩu điện mini 1.5L có nắp kính…"
    )
    assert "«" not in create_promotion_card.card_title(title)


def test_no_raw_kpi_key_reaches_the_card() -> None:
    # every KPI key a card payload can carry has a Vietnamese label ...
    for payload in (
        create_product_card.card_payload(_product()),
        create_promotion_card.card_payload(_product()),
    ):
        diagnosis = payload["diagnosis"]
        key = diagnosis["main_kpi"]["key"]
        label = card_view._main_kpi(diagnosis)["label"]
        assert key in card_view._KPI_LABELS_VI, key
        assert label == card_view._KPI_LABELS_VI[key] == diagnosis["main_kpi"]["label"]
        assert label != key.upper()
    # ... and an unmapped key degrades to a neutral label, never "PRODUCTS"
    unknown = card_view._main_kpi({"main_kpi": {"key": "brand_new_metric"}})
    assert unknown["label"] == card_view.UNKNOWN_KPI_LABEL_VI
    assert unknown["label"] == "Chỉ số khác"


def test_reason_lines_do_not_repeat_the_heading_or_say_tiktok() -> None:
    for text in card_view._REASON_SHORT_VI.values():
        assert "TikTok" not in text
    for text in card_view._KPI_LABELS_VI.values():
        assert "trên TikTok" not in text


class _Product:
    title = "Bình giữ nhiệt inox 750ml"
    name = "Bình giữ nhiệt inox 750ml"
    tiktok_product_id = "1729"


def _product() -> _Product:
    return _Product()
