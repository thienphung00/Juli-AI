"""Let a shop-scoped session read its own shop row.

Issue #1518, ADR-089.

`shops` carried only user-keyed policies:

    shops_select_public | SELECT | (user_id = app_current_user_id())

which were written for the HTTP path, where `get_active_shop` sets both GUCs.
ADR-089 then introduced `with_shop_scope` for work that has a shop but no user
-- and no policy on `shops` answers to it, so such a session cannot read its
own shop. `mock_analytics_reconcile` needed exactly that to resolve its TikTok
shop key, read zero rows as `juli_app`, and returned early having done nothing.

THIS IS NOT A CROSS-TENANT GRANT. The predicate is `id = app_current_shop_id()`
-- one row, the caller's own, and only when a shop context is set. A session
scoped to shop X reading shop X is what tenancy means; it was the absence of
this policy, not its presence, that was the anomaly. Measured on a database at
head with the policy in place: own shop 1 row, other tenant 0, total rows
visible 1, and 0 with no context at all.

Chosen over the two alternatives deliberately. Passing the key as a second
environment variable would make a developer hand-copy a value the database
already holds, and let it drift silently. A `SECURITY DEFINER` resolver would
let ANY `juli_app` session map any shop id to its vendor key, which is a wider
grant than the task needs and the kind of avoidable exemption #1510 exists to
narrow.

`users` is deliberately NOT given the same treatment: nothing shop-scoped needs
to read a user, and `with_shop_scope` withholding the user GUC is the property
that keeps it that way.
"""

from __future__ import annotations

from alembic import op

revision: str = "053_shops_shop_scope_select"
down_revision: str | None = "052_reaper_waiting_approval"
branch_labels: str | None = None
depends_on: str | None = None

_POLICY = "shops_shop_scope_select"


def upgrade() -> None:
    op.execute(f"""
    CREATE POLICY {_POLICY} ON public.shops
      FOR SELECT
      USING (id = app_current_shop_id());
    """)


def downgrade() -> None:
    # The user-keyed policies are untouched by this migration, so dropping this
    # one restores the previous behaviour exactly: the HTTP path keeps working
    # and shop-scoped background work stops being able to read its own shop.
    op.execute(f"DROP POLICY IF EXISTS {_POLICY} ON public.shops;")
