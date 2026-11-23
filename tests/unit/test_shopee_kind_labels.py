"""S7: the card types carry Shopee's own names; stored keys are unchanged."""

from __future__ import annotations

import pytest

from juli_backend.services.shopee_recommendations.kinds import KINDS, voucher_scope_label


@pytest.mark.parametrize(
    ("key", "label"),
    [
        ("title", "Tên sản phẩm"),
        ("description_first_line", "Mô tả sản phẩm"),
        ("cover_image", "Ảnh bìa"),
        ("variation_set", "Phân loại hàng"),
        ("price", "Giá"),
        ("min_spend_voucher", "Mã Giảm Giá"),
        ("review_voucher", "Mã Giảm Giá"),
        ("bundle_deal", "Combo Khuyến Mãi"),
        ("combo_multi", "Combo Khuyến Mãi"),
        ("add_on", "Mua Kèm Deal Sốc"),
        ("gift", "Mua Để Nhận Quà"),
        ("product_discount", "Chương Trình Của Shop"),
        ("flash_sale", "Flash Sale Của Shop"),
    ],
)
def test_the_label_is_shopees_name(key, label):
    assert KINDS[key].key == key and KINDS[key].label == label


def test_price_display_keeps_its_label():
    assert KINDS["price_display"].label == "Ghi đơn giá trên ảnh bìa"


def test_a_voucher_is_named_by_its_scope():
    assert voucher_scope_label("shop") == "Voucher toàn Shop"
    assert voucher_scope_label("product") == "Voucher sản phẩm"
    assert voucher_scope_label(None) == "Voucher toàn Shop"
