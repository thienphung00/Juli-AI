"""Partner reviewer trial accounts (fast track P32-A, DECISIONS D42).

A partner platform's reviewer (Shopee ISV review) signs in with a team-created
e-mail + password, reads the reference shop masked and walks a simulated
Duyệt → Thực thi. The HTTP gate lives in ``api/reviewer.py``; this package holds
the accounts, the mask, the simulation and the provisioning command.
Contract: ``fasttrack/contracts/p32-reviewer-access.md``.
"""

import uuid
from typing import Any

from juli_backend.services.ops.view_as import enter_shop_read_scope
from juli_backend.services.reviewer import (
    accounts,
    catalog,
    config,
    masking,
    sandbox,
    simulation,
)
from juli_backend.services.reviewer.accounts import ReviewerAccount, load_account
from juli_backend.services.reviewer.masking import MaskDictionary, mask_payload
from juli_backend.services.reviewer.sandbox import PinMode


async def ensure_create_product_card(session: Any, shop_id: uuid.UUID) -> Any:
    """P64 (D73.3): the sandbox reviewer's "Tạo sản phẩm" card (``create_product_card``).

    Imported on call: the card module reads the agent playbook registry, which this
    package (imported by the API's reviewer gate at start-up) must not pull in eagerly.
    """
    from juli_backend.services.reviewer.create_product_card import (
        ensure_create_product_card as _ensure,
    )

    return await _ensure(session, shop_id)


__all__ = [
    "MaskDictionary",
    "PinMode",
    "ReviewerAccount",
    "accounts",
    "catalog",
    "config",
    "enter_shop_read_scope",
    "ensure_create_product_card",
    "load_account",
    "mask_payload",
    "masking",
    "sandbox",
    "simulation",
]
