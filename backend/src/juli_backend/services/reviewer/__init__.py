"""Partner reviewer trial accounts (fast track P32-A, DECISIONS D42).

A partner platform's reviewer (Shopee ISV review) signs in with a team-created
e-mail + password, reads the reference shop masked and walks a simulated
Duyệt → Thực thi. The HTTP gate lives in ``api/reviewer.py``; this package holds
the accounts, the mask, the simulation and the provisioning command.
Contract: ``fasttrack/contracts/p32-reviewer-access.md``.
"""

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

__all__ = [
    "MaskDictionary",
    "PinMode",
    "ReviewerAccount",
    "accounts",
    "catalog",
    "config",
    "enter_shop_read_scope",
    "load_account",
    "mask_payload",
    "masking",
    "sandbox",
    "simulation",
]
