"""Shop team: several seller people on one shop (P93)

Revision ID: 121_shop_members
Revises: 120_planned_changes
Create Date: 2026-11-05

One new table, one trigger, two replaced policies. No row is moved or rewritten (the additive gate
refuses a data step); the backfill of existing shops is the separately-operated deferred step
``deferred/102_shop_members_backfill.py``, and until it runs nothing is lost (see "owner without a row").

- ``shop_members`` -- who may act on a shop: ``shop_id``, ``user_id``, the e-mail the person signed in
  with (a snapshot, so Ops lists members without reading ``users``), when and by which staff member they
  were added (``added_via``: ``owner`` / ``invite`` / ``backfill``), the invite they used, and
  ``removed_at`` / ``removed_by_staff`` (a removal is a soft delete, so the history stays). One ACTIVE row
  per (shop, user): a partial unique index. ``juli_ops`` writes it; ``juli_app`` may only SELECT its own
  rows (``user_id = app_current_user_id()``), which is what ``shops``' policies below read.
- ``shops`` SELECT and UPDATE policies now admit a shop when the current user is an ACTIVE member, or is
  ``shops.user_id`` and has NO ``shop_members`` row of their own ("owner without a row": a shop made before
  the backfill ran, or by a code path that does not know the table yet). A removed member keeps a row with
  ``removed_at`` set, so the second branch never re-admits them: removal is immediate and final at the
  database. INSERT and DELETE keep the owner-only predicate. ``shops.user_id`` stays what it was: the
  primary contact that Ops, the workers and the contract-shop code scope by.
- An AFTER INSERT trigger on ``shops`` (SECURITY DEFINER) gives the new shop's owner a member row, unless
  the owner is a login-less placeholder (no e-mail, no phone, no Terms acceptance: the contract-shop owner)
  or a Juli team account (``@app-juli.com``, which connects a shop before its seller exists; it keeps access as
  "owner without a row" until the first invite hands the shop over).

``downgrade`` drops the trigger, restores the two policies and drops the table (member rows are lost; the
shops and their ``user_id`` are untouched).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "121_shop_members"
down_revision: str | None = "120_planned_changes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
OPS_ROLE = "juli_ops"
TABLE = "shop_members"
FN = "public.shop_members_add_owner()"

_MEMBER = (
    "(EXISTS (SELECT 1 FROM public.shop_members m WHERE m.shop_id = shops.id "
    "AND m.user_id = app_current_user_id() AND m.removed_at IS NULL) "
    "OR (user_id = app_current_user_id() AND NOT EXISTS (SELECT 1 FROM public.shop_members m "
    "WHERE m.shop_id = shops.id AND m.user_id = app_current_user_id())))"
)
_OWNER = "(user_id = app_current_user_id())"


def _set_shop_policies(predicate: str) -> None:
    op.execute("DROP POLICY IF EXISTS shops_select_public ON public.shops")
    op.execute("DROP POLICY IF EXISTS shops_update_public ON public.shops")
    op.execute(  # nosec B608 - fixed module constants
        f"CREATE POLICY shops_select_public ON public.shops FOR SELECT USING {predicate}"
    )
    op.execute(  # nosec B608 - fixed module constants
        f"CREATE POLICY shops_update_public ON public.shops FOR UPDATE "
        f"USING {predicate} WITH CHECK {predicate}"
    )


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("added_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("added_via", sa.String(length=16), nullable=False),
        sa.Column("added_by_staff", sa.Uuid(), sa.ForeignKey("ops_staff.id"), nullable=True),
        sa.Column("invite_id", sa.Uuid(), sa.ForeignKey("ops_shop_invites.id"), nullable=True),
        sa.Column("removed_at", sa.DateTime(), nullable=True),
        sa.Column("removed_by_staff", sa.Uuid(), sa.ForeignKey("ops_staff.id"), nullable=True),
        sa.PrimaryKeyConstraint("id", name=f"pk_{TABLE}"),
        sa.CheckConstraint(
            "added_via IN ('owner', 'invite', 'backfill')", name=f"ck_{TABLE}_added_via"
        ),
    )
    op.create_index(
        "uq_shop_members_active",
        TABLE,
        ["shop_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("removed_at IS NULL"),
    )
    op.create_index("ix_shop_members_user", TABLE, ["user_id", "shop_id"])
    op.execute(f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY")  # nosec B608
    op.execute(  # nosec B608 - fixed module constants
        f"CREATE POLICY {TABLE}_select_own ON public.{TABLE} FOR SELECT "
        "USING (user_id = app_current_user_id())"
    )
    op.execute(  # nosec B608 - fixed module constants
        f"CREATE POLICY {TABLE}_ops_only ON public.{TABLE} FOR ALL TO {OPS_ROLE} "
        "USING (true) WITH CHECK (true)"
    )
    op.execute(f"REVOKE ALL ON public.{TABLE} FROM PUBLIC")  # nosec B608
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'REVOKE ALL ON public.{TABLE} FROM {APP_ROLE}';
            EXECUTE 'GRANT SELECT ON public.{TABLE} TO {APP_ROLE}';
        END IF;
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON public.{TABLE} TO {OPS_ROLE}';
    END
    $$;
    """)  # nosec B608 - fixed module constants

    _set_shop_policies(_MEMBER)

    op.execute(f"""
    CREATE OR REPLACE FUNCTION {FN}
    RETURNS trigger
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $fn$
    BEGIN
        INSERT INTO public.shop_members (id, shop_id, user_id, email, added_via)
        SELECT gen_random_uuid(), NEW.id, u.id, lower(u.email), 'owner'
          FROM public.users AS u
         WHERE u.id = NEW.user_id
           AND NOT (u.email IS NULL AND u.phone IS NULL AND u.terms_accepted_at IS NULL)
           AND lower(coalesce(u.email, '')) NOT LIKE '%@app-juli.com'
        ON CONFLICT DO NOTHING;
        RETURN NEW;
    END
    $fn$;
    """)  # nosec B608 - fixed SQL
    op.execute(f"REVOKE ALL ON FUNCTION {FN} FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER shops_add_owner_member AFTER INSERT ON public.shops "
        f"FOR EACH ROW EXECUTE FUNCTION {FN}"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS shops_add_owner_member ON public.shops")
    op.execute(f"DROP FUNCTION IF EXISTS {FN}")
    _set_shop_policies(_OWNER)
    op.drop_index("ix_shop_members_user", table_name=TABLE)
    op.drop_index("uq_shop_members_active", table_name=TABLE)
    op.drop_table(TABLE)
