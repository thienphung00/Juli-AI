"""Juli Ops knows each shop's platform: ``ops_list_shops()`` / ``ops_find_shop()`` return it

Revision ID: 110_ops_shop_platform
Revises: 109_shop_proposals
Create Date: 2026-11-02

Ops treated every shop as TikTok. A contract-client shop (``POST /v1/ops/contract-shops``)
is ``shops.platform = 'shopee'``, so the two SECURITY DEFINER listings the Ops console
reads (083's ``ops_list_shops()``, 085's ``ops_find_shop(uuid)``) gain a last column,
``out_platform varchar`` (``shops.platform``). Everything else is unchanged: same SQL,
same order, same ADR-089 shape (fixed SQL, ``out_`` columns), EXECUTE revoked from
PUBLIC and granted to ``juli_ops`` only.

A ``RETURNS TABLE`` row type cannot change under ``CREATE OR REPLACE``: each function
is dropped and created again, in one transaction, and its grants re-applied exactly as
083 / 085 did.

REVERSIBLE. No table or data change. ``downgrade`` restores the previous definitions
and grants. The deferred write-mode backfill (and the phone cleanup under it) is
re-parented onto this revision so it stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "110_ops_shop_platform"
down_revision: str | None = "109_shop_proposals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OPS_ROLE = "juli_ops"
LIST_FN = "public.ops_list_shops()"
FIND_FN = "public.ops_find_shop(uuid)"

_LIST_WITH_PLATFORM = """
CREATE FUNCTION public.ops_list_shops()
RETURNS TABLE (
    out_shop_id uuid,
    out_shop_name varchar,
    out_tiktok_shop_id varchar,
    out_is_active boolean,
    out_created_at timestamp,
    out_owner_user_id uuid,
    out_owner_email varchar,
    out_owner_consent_at timestamp,
    out_platform varchar
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $fn$
    SELECT s.id, s.shop_name, s.tiktok_shop_id, s.is_active, s.created_at,
           u.id, u.email, u.staff_access_consent_at, s.platform
    FROM public.shops s
    JOIN public.users u ON u.id = s.user_id
    ORDER BY s.created_at
$fn$;
"""

_FIND_WITH_PLATFORM = """
CREATE FUNCTION public.ops_find_shop(p_shop_id uuid)
RETURNS TABLE (
    out_shop_id uuid,
    out_shop_name varchar,
    out_tiktok_shop_id varchar,
    out_is_active boolean,
    out_created_at timestamp,
    out_owner_user_id uuid,
    out_owner_email varchar,
    out_owner_consent_at timestamp,
    out_platform varchar
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $fn$
    SELECT s.id, s.shop_name, s.tiktok_shop_id, s.is_active, s.created_at,
           u.id, u.email, u.staff_access_consent_at, s.platform
    FROM public.shops s
    JOIN public.users u ON u.id = s.user_id
    WHERE s.id = p_shop_id
$fn$;
"""

#: 083 / 085's definitions, verbatim, for ``downgrade``.
_LIST_PREVIOUS = """
CREATE FUNCTION public.ops_list_shops()
RETURNS TABLE (
    out_shop_id uuid,
    out_shop_name varchar,
    out_tiktok_shop_id varchar,
    out_is_active boolean,
    out_created_at timestamp,
    out_owner_user_id uuid,
    out_owner_email varchar,
    out_owner_consent_at timestamp
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $fn$
    SELECT s.id, s.shop_name, s.tiktok_shop_id, s.is_active, s.created_at,
           u.id, u.email, u.staff_access_consent_at
    FROM public.shops s
    JOIN public.users u ON u.id = s.user_id
    ORDER BY s.created_at
$fn$;
"""

_FIND_PREVIOUS = """
CREATE FUNCTION public.ops_find_shop(p_shop_id uuid)
RETURNS TABLE (
    out_shop_id uuid,
    out_shop_name varchar,
    out_tiktok_shop_id varchar,
    out_is_active boolean,
    out_created_at timestamp,
    out_owner_user_id uuid,
    out_owner_email varchar,
    out_owner_consent_at timestamp
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $fn$
    SELECT s.id, s.shop_name, s.tiktok_shop_id, s.is_active, s.created_at,
           u.id, u.email, u.staff_access_consent_at
    FROM public.shops s
    JOIN public.users u ON u.id = s.user_id
    WHERE s.id = p_shop_id
$fn$;
"""


def _grant(fn: str) -> None:
    """083 / 085's grant: EXECUTE revoked from PUBLIC, granted to ``juli_ops`` only."""
    op.execute(f"REVOKE ALL ON FUNCTION {fn} FROM PUBLIC")  # nosec B608 - fixed constant
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{OPS_ROLE}') THEN
            EXECUTE 'GRANT EXECUTE ON FUNCTION {fn} TO {OPS_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608 - fixed role and function names


def _replace(list_sql: str, find_sql: str) -> None:
    for fn in (LIST_FN, FIND_FN):
        op.execute(f"DROP FUNCTION IF EXISTS {fn}")  # nosec B608 - fixed constant
    op.execute(list_sql)
    op.execute(find_sql)
    for fn in (LIST_FN, FIND_FN):
        _grant(fn)


def upgrade() -> None:
    _replace(_LIST_WITH_PLATFORM, _FIND_WITH_PLATFORM)


def downgrade() -> None:
    _replace(_LIST_PREVIOUS, _FIND_PREVIOUS)
