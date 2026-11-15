"""DATA step for P101 W1: every existing shop gets its own business; then ``shops.business_id`` NOT NULL.

Revision ID: 130_businesses_backfill
Revises: 102_shop_members_backfill
Create Date: 2026-11-15

**Deliberately NOT in ``versions/``.** It is ``INSERT ... SELECT`` + ``UPDATE`` + ``SET NOT NULL``,
which ``infra/scripts/migration_additive_gate.py`` refuses from an automatic release (same reason as
``101``, ``074`` and ``102`` in this directory). Run it separately once migration 130 is serving:
copy this file (and the chain under it) into the serving release's ``versions/``, take the backup
(``safe-alembic-upgrade.sh`` does), ``alembic upgrade head``.

Running it late is harmless. Until it runs, a shop with no business keeps P93's access rule (an
active ``shop_members`` row, or its owner without a row); shops inserted after 130 already get a
business from the ``shops_default_business`` trigger.

Per shop with ``business_id IS NULL`` (idempotent, re-runnable):

1. a business with the shop's own id (no mapping table needed; ``uuid4`` ids do not collide across
   tables), named after ``shops.shop_name``;
2. ``shops.user_id`` -> ``owner`` member, unless that person was REMOVED from the shop (a
   ``shop_members`` row, none active): removal stays final;
3. every other active ``shop_members`` row -> ``member`` (``added_via = 'backfill'``);
4. ``shops.business_id`` set.

Then ``shops.kind = 'sandbox'`` for Juli's TikTok sandbox shop, derived from data the same way
``services/reviewer/sandbox.classify_pin`` does: it holds a ``sandbox_write`` credential, no
``production_read`` credential and no ``production_write_shops`` row. The reviewer sample shop is
known only from env config (``REVIEWER_SAMPLE_SHOP_IDS``), so it stays ``real`` here (S2 switches it).

Finally ``shops.business_id`` becomes NOT NULL; the trigger keeps every insert path valid.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "130_businesses_backfill"
down_revision: str | None = "102_shop_members_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
    INSERT INTO public.businesses (id, name)
    SELECT s.id, left(coalesce(nullif(btrim(s.shop_name), ''), 'Shop'), 200)
      FROM public.shops AS s
     WHERE s.business_id IS NULL
    ON CONFLICT (id) DO NOTHING
    """)
    op.execute("""
    INSERT INTO public.business_members (id, business_id, user_id, role, email, added_via)
    SELECT gen_random_uuid(), s.id, u.id, 'owner', lower(u.email), 'backfill'
      FROM public.shops AS s
      JOIN public.users AS u ON u.id = s.user_id
     WHERE s.business_id IS NULL
       AND (
            EXISTS (SELECT 1 FROM public.shop_members m
                     WHERE m.shop_id = s.id AND m.user_id = u.id AND m.removed_at IS NULL)
            OR NOT EXISTS (SELECT 1 FROM public.shop_members m
                            WHERE m.shop_id = s.id AND m.user_id = u.id)
       )
       AND NOT EXISTS (SELECT 1 FROM public.business_members bm
                        WHERE bm.business_id = s.id AND bm.user_id = u.id)
    ON CONFLICT DO NOTHING
    """)
    op.execute("""
    INSERT INTO public.business_members (id, business_id, user_id, role, email, added_via)
    SELECT gen_random_uuid(), s.id, m.user_id, 'member', m.email, 'backfill'
      FROM public.shops AS s
      JOIN public.shop_members AS m ON m.shop_id = s.id AND m.removed_at IS NULL
     WHERE s.business_id IS NULL
       AND m.user_id <> s.user_id
       AND NOT EXISTS (SELECT 1 FROM public.business_members bm
                        WHERE bm.business_id = s.id AND bm.user_id = m.user_id)
    ON CONFLICT DO NOTHING
    """)
    op.execute("UPDATE public.shops SET business_id = id WHERE business_id IS NULL")
    op.execute("""
    UPDATE public.shops AS s SET kind = 'sandbox'
     WHERE s.kind = 'real'
       AND EXISTS (SELECT 1 FROM public.tiktok_credentials c
                    WHERE c.shop_id = s.id AND c.capability = 'sandbox_write')
       AND NOT EXISTS (SELECT 1 FROM public.tiktok_credentials c
                        WHERE c.shop_id = s.id AND c.capability = 'production_read')
       AND NOT EXISTS (SELECT 1 FROM public.production_write_shops p WHERE p.shop_id = s.id)
    """)
    op.execute("ALTER TABLE public.shops ALTER COLUMN business_id SET NOT NULL")


def downgrade() -> None:
    """Only the constraint is undone: the businesses and members are ordinary rows by now."""
    op.execute("ALTER TABLE public.shops ALTER COLUMN business_id DROP NOT NULL")
