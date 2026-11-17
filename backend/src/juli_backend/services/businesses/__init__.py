"""P101 W1 identity: businesses, their people, self-serve invites (contract §2.1, T4).

One account → many businesses → many shops on many platforms. Access to a shop is the one rule in
``repositories.identity.shops_of_user_clause`` (business membership, or a ``shop_members`` row);
this package manages the business side of it. Nothing commits here.
"""

from juli_backend.services.businesses.backfill import BackfillResult, run_backfill
from juli_backend.services.businesses.service import (
    ACTION_BUSINESS_INVITE_ACCEPT,
    ACTION_BUSINESS_INVITE_CREATE,
    ACTION_BUSINESS_MEMBER_REMOVE,
    ROLE_MEMBER,
    ROLE_OWNER,
    BusinessError,
    CreatedBusinessInvite,
    accept_invite,
    active_memberships,
    business_for_new_shop,
    chosen_business,
    create_invite,
    find_invite,
    in_shop_team,
    list_for_user,
    member_of,
    members_of_shop_business,
    owns_shop,
    preview_invite,
    remove_member,
    remove_person_from_shop_business,
    shop_business_id_expr,
    transfer_shop_business_owner,
)

__all__ = [
    "ACTION_BUSINESS_INVITE_ACCEPT",
    "ACTION_BUSINESS_INVITE_CREATE",
    "ACTION_BUSINESS_MEMBER_REMOVE",
    "ROLE_MEMBER",
    "ROLE_OWNER",
    "BackfillResult",
    "BusinessError",
    "CreatedBusinessInvite",
    "accept_invite",
    "active_memberships",
    "business_for_new_shop",
    "chosen_business",
    "create_invite",
    "find_invite",
    "in_shop_team",
    "list_for_user",
    "member_of",
    "members_of_shop_business",
    "owns_shop",
    "preview_invite",
    "remove_member",
    "remove_person_from_shop_business",
    "run_backfill",
    "shop_business_id_expr",
    "transfer_shop_business_owner",
]
