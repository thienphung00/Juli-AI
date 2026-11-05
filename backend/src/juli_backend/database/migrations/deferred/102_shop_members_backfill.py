"""DATA step for P93: every existing shop's seller becomes a member of that shop.

Revision ID: 102_shop_members_backfill
Revises: 121_shop_members
Create Date: 2026-11-05

**Deliberately NOT in ``versions/``.** It is an ``INSERT ... SELECT``, which
``infra/scripts/migration_additive_gate.py`` refuses from an automatic release (same reason as
``101_write_mode_backfill`` and ``074`` in this directory). Run it separately, after migration 121 is live:
copy this file into the serving release's ``versions/``, take the backup (``safe-alembic-upgrade.sh`` does),
``alembic upgrade head``, then land a follow-up moving it from ``deferred/`` to ``versions/``.

Running it late is harmless. Until it runs, a shop's owner (``shops.user_id``) with no ``shop_members`` row of
their own keeps access through the "owner without a row" branch of the ``shops`` policies (migration 121), and
Ops lists that owner as a member read from ``shops.user_id``. What the backfill adds is the real row, so
the owner can later be removed and the list is the same in the database as on screen.

Predicate: one active row per shop for ``shops.user_id`` unless that user is a login-less placeholder (no
e-mail, no phone, no Terms acceptance: a contract-shop owner) or a Juli team account (``@app-juli.com``). Idempotent (``ON CONFLICT DO NOTHING`` on the
active-member index, and nothing is inserted for a user who already has any row on the shop, so a removed
owner is not re-added).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "102_shop_members_backfill"
down_revision: str | None = "121_shop_members"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
    INSERT INTO public.shop_members (id, shop_id, user_id, email, added_at, added_via)
    SELECT gen_random_uuid(), s.id, u.id, lower(u.email), now(), 'backfill'
      FROM public.shops AS s
      JOIN public.users AS u ON u.id = s.user_id
     WHERE NOT (u.email IS NULL AND u.phone IS NULL AND u.terms_accepted_at IS NULL)
       AND lower(coalesce(u.email, '')) NOT LIKE '%@app-juli.com'
       AND NOT EXISTS (
            SELECT 1 FROM public.shop_members m WHERE m.shop_id = s.id AND m.user_id = u.id
       )
    ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    """No-op: a backfilled row is an ordinary member row; removing them all would lock sellers out."""
