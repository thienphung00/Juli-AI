"""P16 (D25.6): staff never see buyer data — every ops payload is masked."""

from __future__ import annotations

from juli_backend.services.ops.masking import MASK, mask_pii


def test_buyer_keys_are_masked_recursively():
    out = mask_pii(
        {
            "buyer_email": "a@b.com",
            "recipient_address": {"full_address": "12 Lê Lợi"},
            "orders": [{"phone_number": "0912345678", "total": 100}],
            "shop_name": "Mỹ phẩm Thảo Nhi",
        }
    )
    assert out["buyer_email"] == MASK
    assert out["recipient_address"] == MASK
    assert out["orders"][0]["phone_number"] == MASK
    assert out["orders"][0]["total"] == 100
    assert out["shop_name"] == "Mỹ phẩm Thảo Nhi"


def test_phones_and_non_staff_emails_in_text_are_masked():
    text = mask_pii(
        "Khách 0912.345.678 / +84 912 345 678, mail thaonhi@gmail.com, cc an@app-juli.com"
    )
    assert "0912" not in text and "912 345" not in text
    assert "thaonhi@gmail.com" not in text and "thaonh…@…" in text
    assert "an@app-juli.com" in text


def test_numbers_and_ids_survive():
    out = mask_pii(
        {"gmv_30d": 214900000, "id": "0912345678901", "accept_url": "https://x/?token=0912345678"}
    )
    assert out == {
        "gmv_30d": 214900000,
        "id": "0912345678901",
        "accept_url": "https://x/?token=0912345678",
    }
