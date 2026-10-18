"""P50-P (D60.2): de-identification before any text or JSON reaches the LLM provider.

Buyer contact data (name, phone, e-mail, address) never reaches the provider; buyer and
user ids become stable aliases; shop/business numbers (prices, quantities, KPIs) stay
exactly as they were.
"""

from __future__ import annotations

import json

from juli_backend.core.privacy import REDACTED, deidentify_payload, deidentify_text
from juli_backend.services.ops import mask_pii


def test_text_scrubs_emails_and_vn_phones() -> None:
    text = "Khách Lan gọi 0912 345 678 hoặc +84912345678, mail lan.nguyen@gmail.com nhé"
    out = deidentify_text(text)
    assert "0912 345 678" not in out
    assert "+84912345678" not in out
    assert "lan.nguyen" not in out and "gmail.com" not in out
    assert out.count(REDACTED) == 3
    assert out.startswith("Khách Lan gọi ")


def test_text_scrubs_a_phone_at_the_end_of_a_sentence() -> None:
    assert deidentify_text("Hotline: 0912345678.") == f"Hotline: {REDACTED}."
    assert deidentify_text("tỉ lệ 1.0912345678") == "tỉ lệ 1.0912345678"


def test_text_keeps_prices_quantities_and_ids() -> None:
    text = "Giá 189.000đ, bán 1.234 đơn, GMV 45.600.000, đơn 576543210987654321, CTR 3,2%"
    assert deidentify_text(text) == text


def test_text_scrubs_staff_addresses_too() -> None:
    # The ops console keeps @app-juli.com readable for auditors; the provider needs none.
    assert deidentify_text("liên hệ ops@app-juli.com") == f"liên hệ {REDACTED}"


def test_payload_redacts_buyer_contact_keys_and_keeps_numbers() -> None:
    payload = {
        "shop_id": "7495512345678901234",
        "order_id": "576543210987654321",
        "price": 189000,
        "quantity": 3,
        "gmv_30d": 45_600_000.5,
        "buyer_name": "Nguyễn Thị Lan",
        "recipient_address": {"street": "12 Lê Lợi", "district": "Quận 1", "zip": 70000},
        "phone_number": "0912345678",
        "customer_email": "lan@gmail.com",
        "buyer_count": 120,
        "title": "Kem chống nắng SPF50",
    }
    out = deidentify_payload(payload)
    assert out["shop_id"] == payload["shop_id"]
    assert out["order_id"] == payload["order_id"]
    assert out["price"] == 189000 and out["quantity"] == 3 and out["gmv_30d"] == 45_600_000.5
    assert out["buyer_count"] == 120
    assert out["title"] == "Kem chống nắng SPF50"
    assert out["buyer_name"] == REDACTED
    assert out["phone_number"] == REDACTED
    assert out["customer_email"] == REDACTED
    assert out["recipient_address"] == {"street": REDACTED, "district": REDACTED, "zip": 70000}
    assert payload["buyer_name"] == "Nguyễn Thị Lan"  # input untouched


def test_payload_aliases_buyer_and_user_ids_stably() -> None:
    a = deidentify_payload({"buyer_user_id": "7000111222333", "user_id": 42})
    b = deidentify_payload({"buyer_user_id": "7000111222333", "user_id": 42})
    assert a == b
    assert a["buyer_user_id"] != "7000111222333" and "7000111222333" not in a["buyer_user_id"]
    assert a["user_id"] != 42 and isinstance(a["user_id"], str)
    other = deidentify_payload({"buyer_user_id": "7000111222334"})
    assert other["buyer_user_id"] != a["buyer_user_id"]
    ids = deidentify_payload({"buyer_ids": ["1", "2"]})["buyer_ids"]
    assert len(set(ids)) == 2 and "1" not in ids


def test_payload_leaves_non_personal_id_keys_alone() -> None:
    # An 11-digit id starting with 0 would look like a phone number in free text.
    payload = {"sku_id": "01234567890", "id": "84123456789"}
    assert deidentify_payload(payload) == payload


def test_payload_scrubs_free_text_and_nested_lists() -> None:
    out = deidentify_payload(
        {"reviews": [{"text": "Shop gọi lại 0987654321 giúp em", "rating": 5}], "n": None}
    )
    assert out == {
        "reviews": [{"text": f"Shop gọi lại {REDACTED} giúp em", "rating": 5}],
        "n": None,
    }


def test_payload_handles_json_string_round_trip() -> None:
    # A tool result arrives as a JSON string: keys still decide, not only the regexes.
    raw = json.dumps({"buyer_name": "Lan", "units": 7}, ensure_ascii=False)
    out = json.loads(deidentify_text(raw))
    assert out == {"buyer_name": REDACTED, "units": 7}
    assert deidentify_text("[1, 2]") == "[1, 2]"
    assert deidentify_text("{not json") == "{not json"


def test_ops_mask_pii_still_uses_the_same_patterns() -> None:
    # One source of truth: ops masking reads its regexes from core.privacy.
    import inspect

    from juli_backend.core.privacy import deidentify as core
    from juli_backend.services.ops import masking as ops

    assert "re.compile" not in inspect.getsource(ops)
    assert ops._EMAIL is core.EMAIL_RE
    assert ops._PHONE is core.PHONE_RE
    assert ops._PII_KEY is core.PII_KEY_RE
    assert mask_pii({"buyer_name": "Lan", "note": "0912345678"}) == {
        "buyer_name": "•••",
        "note": "•••",
    }
