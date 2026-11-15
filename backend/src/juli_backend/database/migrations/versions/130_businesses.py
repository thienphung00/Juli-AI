"""Businesses: one seller account, many businesses, many shops on many platforms (P101 W1)

Revision ID: 130_businesses
Revises: 129_stock_alert
Create Date: 2026-11-15

Contract ``fasttrack/contracts/p101-tiktok-parity.md`` §2.1 (T4). Three new tables, two new
``shops`` columns, one trigger, two replaced ``shops`` policies, four reviewed SECURITY DEFINER
functions. No row is moved here (the additive gate refuses a data step). The backfill of existing
shops is AUTOMATIC (owner rule T2): the worker job ``juli_backend.businesses_backfill`` (beat every
10 min and at worker start, ``services/businesses/backfill.py``) calls
``businesses_backfill_batch`` until no shop is left without a business, then
``businesses_require_shop_business``, which adds and validates ``CHECK (business_id IS NOT NULL)``.
Until then nothing is lost: a shop with no business keeps P93's access rule (below).

- ``businesses`` -- id, name, created_at, updated_at.
- ``business_invites`` -- a business owner's invite by e-mail: the sha256 of the token, who sent it,
  expiry, accept / revoke stamps. ``juli_ops`` only (the service checks the owner, then writes).
- ``business_members`` -- (business, user, role owner|member, e-mail snapshot, added_at, added_via
  owner|invite|backfill, invite_id, removed_at). One ACTIVE row per (business, user): a partial
  unique index. ``juli_app`` SELECTs its own rows only; ``juli_ops`` writes.
- ``shops.business_id`` (nullable FK; CHECK NOT NULL once the job is done) and ``shops.kind``
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

- Functions for ``juli_ops``, which holds no grant on ``shops`` (Ops reads shops only through
  reviewed functions, migrations 083 / 110): ``ops_shop_business(shop)`` and
  ``ops_business_first_shop(business)`` (one id each), ``businesses_backfill_batch(limit)`` and
  ``businesses_require_shop_business()`` (the job's two steps). ``juli_app`` needs no new grant:
  its ``shops`` SELECT / INSERT / UPDATE grants are table-level (043, 058), so they cover the new
  columns.

``downgrade`` drops the functions and trigger, restores migration 121's policies, drops the columns
and tables.
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
SHOP_BUSINESS_FN = "public.ops_shop_business(uuid)"
FIRST_SHOP_FN = "public.ops_business_first_shop(uuid)"
BACKFILL_FN = "public.businesses_backfill_batch(integer)"
REQUIRE_FN = "public.businesses_require_shop_business()"
OPS_FUNCTIONS = (SHOP_BUSINESS_FN, FIRST_SHOP_FN, BACKFILL_FN, REQUIRE_FN)
#: Added (NOT VALID, then VALIDATE) by ``businesses_require_shop_business`` once no NULL is left.
BUSINESS_SET_CHECK = "ck_shops_business_id_set"

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
    _create_ops_functions()


def _create_ops_functions() -> None:
    op.execute("""
    CREATE OR REPLACE FUNCTION public.ops_shop_business(p_shop_id uuid)
    RETURNS uuid
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $fn$
        SELECT s.business_id FROM public.shops s WHERE s.id = p_shop_id
    $fn$;
    """)
    op.execute("""
    CREATE OR REPLACE FUNCTION public.ops_business_first_shop(p_business_id uuid)
    RETURNS uuid
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $fn$
        SELECT s.id FROM public.shops s WHERE s.business_id = p_business_id
         ORDER BY s.created_at, s.id LIMIT 1
    $fn$;
    """)
    # One statement of data-modifying CTEs: every CTE sees the same snapshot, and the foreign keys
    # are checked at the end of the statement, so the businesses, their people and the shops'
    # business_id land together. A business takes its shop's id (idempotent, no mapping table).
    # SKIP LOCKED: two workers never take the same shops.
    op.execute("""
    CREATE OR REPLACE FUNCTION public.businesses_backfill_batch(p_limit integer)
    RETURNS TABLE (out_shops integer, out_owners integer, out_members integer, out_sandbox integer)
    LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $fn$
        WITH picked AS (
            SELECT s.id, s.user_id, s.shop_name FROM public.shops s
             WHERE s.business_id IS NULL
             ORDER BY s.id
             LIMIT greatest(coalesce(p_limit, 500), 1)
             FOR UPDATE SKIP LOCKED
        ), made AS (
            INSERT INTO public.businesses (id, name)
            SELECT p.id, left(coalesce(nullif(btrim(p.shop_name), ''), 'Shop'), 200) FROM picked p
            ON CONFLICT (id) DO NOTHING
            RETURNING id
        ), owners AS (
            INSERT INTO public.business_members (id, business_id, user_id, role, email, added_via)
            SELECT gen_random_uuid(), p.id, u.id, 'owner', lower(u.email), 'backfill'
              FROM picked p JOIN public.users u ON u.id = p.user_id
             WHERE (EXISTS (SELECT 1 FROM public.shop_members m WHERE m.shop_id = p.id
                             AND m.user_id = u.id AND m.removed_at IS NULL)
                    OR NOT EXISTS (SELECT 1 FROM public.shop_members m
                                    WHERE m.shop_id = p.id AND m.user_id = u.id))
               AND NOT EXISTS (SELECT 1 FROM public.business_members bm
                                WHERE bm.business_id = p.id AND bm.user_id = u.id)
            ON CONFLICT DO NOTHING
            RETURNING 1
        ), members AS (
            INSERT INTO public.business_members (id, business_id, user_id, role, email, added_via)
            SELECT gen_random_uuid(), p.id, m.user_id, 'member', m.email, 'backfill'
              FROM picked p
              JOIN public.shop_members m ON m.shop_id = p.id AND m.removed_at IS NULL
             WHERE m.user_id <> p.user_id
               AND NOT EXISTS (SELECT 1 FROM public.business_members bm
                                WHERE bm.business_id = p.id AND bm.user_id = m.user_id)
            ON CONFLICT DO NOTHING
            RETURNING 1
        ), moved AS (
            UPDATE public.shops sh
               SET business_id = sh.id,
                   kind = CASE
                       WHEN sh.kind = 'real'
                        AND EXISTS (SELECT 1 FROM public.tiktok_credentials c
                                     WHERE c.shop_id = sh.id AND c.capability = 'sandbox_write')
                        AND NOT EXISTS (SELECT 1 FROM public.tiktok_credentials c
                                         WHERE c.shop_id = sh.id
                                           AND c.capability = 'production_read')
                        AND NOT EXISTS (SELECT 1 FROM public.production_write_shops w
                                         WHERE w.shop_id = sh.id)
                       THEN 'sandbox' ELSE sh.kind END
              FROM picked p
             WHERE sh.id = p.id
            RETURNING sh.kind
        )
        SELECT (SELECT count(*) FROM moved)::integer,
               (SELECT count(*) FROM owners)::integer,
               (SELECT count(*) FROM members)::integer,
               (SELECT count(*) FROM moved WHERE kind = 'sandbox')::integer
    $fn$;
    """)  # nosec B608 - fixed SQL
    # The NOT NULL of business_id, as a CHECK the additive gate accepts: added NOT VALID (new and
    # updated rows only; the trigger fills every insert), then VALIDATEd. Only once no NULL is left,
    # so no pre-backfill row is ever refused an update. True when the check is in force.
    op.execute(f"""
    CREATE OR REPLACE FUNCTION public.businesses_require_shop_business()
    RETURNS boolean
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $fn$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{BUSINESS_SET_CHECK}'
                    AND conrelid = 'public.shops'::regclass AND convalidated) THEN
            RETURN true;
        END IF;
        IF EXISTS (SELECT 1 FROM public.shops WHERE business_id IS NULL) THEN
            RETURN false;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{BUSINESS_SET_CHECK}'
                        AND conrelid = 'public.shops'::regclass) THEN
            EXECUTE 'ALTER TABLE public.shops ADD CONSTRAINT {BUSINESS_SET_CHECK} '
                    'CHECK (business_id IS NOT NULL) NOT VALID';
        END IF;
        EXECUTE 'ALTER TABLE public.shops VALIDATE CONSTRAINT {BUSINESS_SET_CHECK}';
        RETURN true;
    END
    $fn$;
    """)  # nosec B608 - fixed module constants
    for fn in OPS_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {fn} FROM PUBLIC")  # nosec B608 - fixed constant
        op.execute(f"GRANT EXECUTE ON FUNCTION {fn} TO {OPS_ROLE}")  # nosec B608 - fixed constant


def downgrade() -> None:
    for fn in OPS_FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {fn}")  # nosec B608 - fixed constant
    op.execute(f"ALTER TABLE public.shops DROP CONSTRAINT IF EXISTS {BUSINESS_SET_CHECK}")
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
