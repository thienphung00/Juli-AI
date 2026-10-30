"""P78: the reviewer mask's digit rule never rewrites a UUID.

A uuid5 shop alias can end in an all-digit 12-character group
(``562e12d5-671d-5c79-86c9-064082235957``). The 12-20 digit rule used to rewrite that
group into ``id-<hash8>``, so the alias the reviewer must send back as ``X-Shop-Id``
no longer matched (seen as a flaky ``test_reviewer_two_pins`` failure in deploy run
41012222263).
"""

from __future__ import annotations

import uuid

from juli_backend.services.reviewer import config
from juli_backend.services.reviewer.masking import MaskDictionary, mask_payload

DIGIT_TAIL_UUID = "562e12d5-671d-5c79-86c9-064082235957"
TIKTOK_PRODUCT_ID = "1738280771184854659"


def _shop_with_digit_tail_alias() -> tuple[uuid.UUID, uuid.UUID]:
    """A shop id whose reviewer alias ends in an all-digit group (deterministic search)."""
    for n in range(100_000):
        shop_id = uuid.uuid5(uuid.NAMESPACE_URL, f"p78-shop-{n}")
        alias = config.shop_alias_id(shop_id)
        if str(alias).rsplit("-", 1)[1].isdigit():
            return shop_id, alias
    raise AssertionError("no alias with an all-digit tail in the search range")


def test_a_uuid_with_an_all_digit_tail_survives_the_mask() -> None:
    shop_id, alias = _shop_with_digit_tail_alias()
    dictionary = MaskDictionary(shop_id=shop_id, alias_id=alias)
    masked = mask_payload(
        {"shops": [{"id": str(alias)}], "card_id": DIGIT_TAIL_UUID},
        dictionary,
    )
    assert masked["shops"][0]["id"] == str(alias)
    assert masked["card_id"] == DIGIT_TAIL_UUID


def test_a_long_digit_run_outside_a_uuid_is_still_aliased() -> None:
    shop_id, alias = _shop_with_digit_tail_alias()
    dictionary = MaskDictionary(shop_id=shop_id, alias_id=alias)
    note = f"Đã tạo sản phẩm · mã {TIKTOK_PRODUCT_ID} · run {DIGIT_TAIL_UUID}"
    masked = mask_payload({"note": note}, dictionary)
    assert TIKTOK_PRODUCT_ID not in masked["note"]
    assert DIGIT_TAIL_UUID in masked["note"]
