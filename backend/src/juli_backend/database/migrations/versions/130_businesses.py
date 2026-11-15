"""Businesses: one seller account, many businesses, many shops on many platforms (P101 W1)

Revision ID: 130_businesses
Revises: 129_stock_alert
Create Date: 2026-11-15

Contract ``fasttrack/contracts/p101-tiktok-parity.md`` §2.1 (T4). Three new tables, two new
``shops`` columns, one trigger, two replaced ``shops`` policies. No row is moved: the additive
gate refuses a data step, so the backfill of existing shops (each shop → its own business; its
owner and active members → business members; the TikTok sandbox shop → ``kind = 'sandbox'``) is the
separately-operated ``deferred/130_businesses_backfill.py``, which also sets ``shops.business_id``
NOT NULL. Until it runs nothing is lost: a shop with no business keeps P93's access rule (below).

- ``businesses`` -- id, name, created_at, updated_at.
- ``business_invites`` -- a business owner's invite by e-mail: the sha256 of the token, who sent it,
  expiry, accept / revoke stamps. ``juli_ops`` only (the service checks the owner, then writes).
- ``business_members`` -- (business, user, role owner|member, e-mail snapshot, added_at, added_via
  owner|invite|backfill, invite_id, removed_at). One ACTIVE row per (business, user): a partial
  unique index. ``juli_app`` SELECTs its own rows only; ``juli_ops`` writes.
- ``shops.business_id`` (nullable FK, NOT NULL after the backfill) and ``shops.kind``
  (real|sandbox|sample, default real, check constraint).
- ``shops`` SELECT / UPDATE: an active member of the shop's business, or an active ``shop_members``
  row; P93's "owner without a row" stays only for an owner with NO row at all (no ``shop_members``
  row, no ``business_members`` row in that business): pre-backfill shops and the inserting statement
  itself. ``shops.user_id`` stays the primary contact; once its person has any row it grants nothing
  by itself, so a removal is final. INSERT keeps the owner
  predicate: a membership check there would not see the owner row the trigger below writes in the
  same statement, so the chosen business is checked in ``services/businesses`` before the insert.
- A BEFORE INSERT trigger on ``shops`` (SECURITY DEFINER) gives a shop inserted without a business
  its own business named after the shop, with ``shops.user_id`` as owner -- every insert path
  (contract shops, seeds, the previous release during a deploy) keeps working with no code change.

``downgrade`` drops the trigger, restores migration 121's policies, drops the columns and tables.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "130_businesses"
down_revision: str | None = "129_stock_alert"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
OPS_ROLE = "juli_ops"
BUSINESSES = "businesses"
INVITES = "business_invites"
MEMBERS = "business_members"
FN = "public.shops_default_business()"

_SHOP_MEMBER = (
    "EXISTS (SELECT 1 FROM public.shop_members m WHERE m.shop_id = shops.id "
    "AND m.user_id = app_current_user_id() AND m.removed_at IS NULL)"
)
_BUSINESS_MEMBER = (
    "EXISTS (SELECT 1 FROM public.business_members bm WHERE bm.business_id = shops.business_id "
    "AND bm.user_id = app_current_user_id() AND bm.removed_at IS NULL)"
)
# The owner with NO row of their own -- neither in ``shop_members`` for this shop nor (any state)
# in ``business_members`` for its business: a shop made before the backfill, and the very INSERT
# whose trigger writes the owner row (a statement does not see rows its own trigger wrote, and
# ``INSERT ... RETURNING`` is checked against this policy). Any row -- a removed one included --
# ends this branch, so removal stays final.
_LEGACY_OWNER = (
    "(user_id = app_current_user_id() AND NOT EXISTS (SELECT 1 FROM public.shop_members m "
    "WHERE m.shop_id = shops.id AND m.user_id = app_current_user_id()) AND NOT EXISTS (SELECT 1 "
    "FROM public.business_members bm WHERE bm.business_id = shops.business_id "
    "AND bm.user_id = app_current_user_id()))"
)
_ACCESS = f"({_BUSINESS_MEMBER} OR {_SHOP_MEMBER} OR {_LEGACY_OWNER})"
# Migration 121's predicates, restored by downgrade.
_P93_MEMBER = (
    "(EXISTS (SELECT 1 FROM public.shop_members m WHERE m.shop_id = shops.id "
    "AND m.user_id = app_current_user_id() AND m.removed_at IS NULL) "
    "OR (user_id = app_current_user_id() AND NOT EXISTS (SELECT 1 FROM public.shop_members m "
    "WHERE m.shop_id = shops.id AND m.user_id = app_current_user_id())))"
)


def _set_shop_policies(access: str) -> None:
    op.execute("DROP POLICY IF EXISTS shops_select_public ON public.shops")
    op.execute("DROP POLICY IF EXISTS shops_update_public ON public.shops")
    op.execute(  # nosec B608 - fixed module constants
        f"CREATE POLICY shops_select_public ON public.shops FOR SELECT USING {access}"
    )
    op.execute(  # nosec B608 - fixed module constants
        f"CREATE POLICY shops_update_public ON public.shops FOR UPDATE "
        f"USING {access} WITH CHECK {access}"
    )


def upgrade() -> None:
    op.create_table(
        BUSINESSES,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{BUSINESSES}"),
    )
    op.create_table(
        INVITES,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "business_id",
            sa.Uuid(),
            sa.ForeignKey("businesses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("accepted_user_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=f"pk_{INVITES}"),
        sa.UniqueConstraint("token_hash", name="uq_business_invites_token_hash"),
    )
    op.create_index("ix_business_invites_business", INVITES, ["business_id", "email"])
    op.create_table(
        MEMBERS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "business_id",
            sa.Uuid(),
            sa.ForeignKey("businesses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("added_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("added_via", sa.String(length=16), nullable=False),
        sa.Column("invite_id", sa.Uuid(), sa.ForeignKey("business_invites.id"), nullable=True),
        sa.Column("removed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=f"pk_{MEMBERS}"),
        sa.CheckConstraint("role IN ('owner', 'member')", name="ck_business_members_role"),
        sa.CheckConstraint(
            "added_via IN ('owner', 'invite', 'backfill')", name="ck_business_members_added_via"
        ),
    )
    op.create_index(
        "uq_business_members_active",
        MEMBERS,
        ["business_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("removed_at IS NULL"),
    )
    op.create_index("ix_business_members_user", MEMBERS, ["user_id", "business_id"])

    op.add_column(
        "shops",
        sa.Column("business_id", sa.Uuid(), sa.ForeignKey("businesses.id"), nullable=True),
    )
    op.create_index("ix_shops_business_id", "shops", ["business_id"])
    op.add_column(
        "shops",
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="real"),
    )
    op.create_check_constraint("ck_shops_kind", "shops", "kind IN ('real', 'sandbox', 'sample')")

    op.execute(f"ALTER TABLE public.{BUSINESSES} ENABLE ROW LEVEL SECURITY")  # nosec B608
    op.execute(f"ALTER TABLE public.{MEMBERS} ENABLE ROW LEVEL SECURITY")  # nosec B608
    op.execute(f"ALTER TABLE public.{INVITES} ENABLE ROW LEVEL SECURITY")  # nosec B608
    op.execute(  # nosec B608 - fixed module constants
        f"CREATE POLICY {MEMBERS}_select_own ON public.{MEMBERS} FOR SELECT "
        "USING (user_id = app_current_user_id())"
    )
    op.execute(  # nosec B608 - fixed module constants
        f"CREATE POLICY {BUSINESSES}_select_member ON public.{BUSINESSES} FOR SELECT "
        "USING (EXISTS (SELECT 1 FROM public.business_members bm WHERE bm.business_id = "
        "businesses.id AND bm.user_id = app_current_user_id() AND bm.removed_at IS NULL))"
    )
    for table in (BUSINESSES, MEMBERS, INVITES):
        op.execute(  # nosec B608 - fixed module constants
            f"CREATE POLICY {table}_ops_only ON public.{table} FOR ALL TO {OPS_ROLE} "
            "USING (true) WITH CHECK (true)"
        )
        op.execute(f"REVOKE ALL ON public.{table} FROM PUBLIC")  # nosec B608
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'REVOKE ALL ON public.{BUSINESSES}, public.{MEMBERS}, public.{INVITES} FROM {APP_ROLE}';
            EXECUTE 'GRANT SELECT ON public.{BUSINESSES}, public.{MEMBERS} TO {APP_ROLE}';
        END IF;
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON public.{BUSINESSES}, public.{MEMBERS}, public.{INVITES} TO {OPS_ROLE}';
    END
    $$;
    """)  # nosec B608 - fixed module constants

    _set_shop_policies(_ACCESS)

    # One statement per branch (a data-modifying CTE): the business and its owner row are written
    # together, and the new id lands on the row being inserted.
    op.execute(f"""
    CREATE OR REPLACE FUNCTION {FN}
    RETURNS trigger
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $fn$
    DECLARE
        new_business uuid;
    BEGIN
        IF NEW.business_id IS NULL THEN
            WITH b AS (
                INSERT INTO public.businesses (id, name)
                VALUES (gen_random_uuid(), left(coalesce(nullif(btrim(NEW.shop_name), ''), 'Shop'), 200))
                RETURNING id
            ), m AS (
                INSERT INTO public.business_members (id, business_id, user_id, role, email, added_via)
                SELECT gen_random_uuid(), b.id, u.id, 'owner', lower(u.email), 'owner'
                  FROM b JOIN public.users AS u ON u.id = NEW.user_id
                RETURNING business_id
            )
            SELECT b.id INTO new_business FROM b;
            NEW.business_id := new_business;
        END IF;
        RETURN NEW;
    END
    $fn$;
    """)  # nosec B608 - fixed SQL
    op.execute(f"REVOKE ALL ON FUNCTION {FN} FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER shops_default_business BEFORE INSERT ON public.shops "
        f"FOR EACH ROW EXECUTE FUNCTION {FN}"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS shops_default_business ON public.shops")
    op.execute(f"DROP FUNCTION IF EXISTS {FN}")
    _set_shop_policies(_P93_MEMBER)
    op.drop_constraint("ck_shops_kind", "shops", type_="check")
    op.drop_column("shops", "kind")
    op.drop_index("ix_shops_business_id", table_name="shops")
    op.drop_column("shops", "business_id")
    op.drop_index("ix_business_members_user", table_name=MEMBERS)
    op.drop_index("uq_business_members_active", table_name=MEMBERS)
    op.drop_table(MEMBERS)
    op.drop_index("ix_business_invites_business", table_name=INVITES)
    op.drop_table(INVITES)
    op.drop_table(BUSINESSES)
