"""Grant UPDATE on tiktok_sync_state to juli_app (issue #1631).

`TikTokSyncStateRepo.save` writes one row per (shop, endpoint). The FIRST save
for a shop inserts, and every save after it UPDATES the existing cursor row.
`juli_app` held SELECT and INSERT but not UPDATE, so incremental sync could
advance its cursor exactly once and then failed with:

    permission denied for table tiktok_sync_state

This is a grant gap, not an RLS one, and the two are easy to confuse: RLS
refuses with "new row violates row-level security policy", while a missing
GRANT refuses with "permission denied for table". The reconcile hit the RLS
form first (fixed by scoping the save); this is what it hits next.

Found before deployment rather than after, by exercising the save twice against
a non-owner role — the first call inserts and passes, the second updates and is
where the gap shows. A test that saves once cannot see this.

UPDATE only, deliberately. `save` never deletes, so DELETE stays ungranted
(least privilege). Follows 054's GRANT_MAP + IF EXISTS shape.
"""

from collections.abc import Sequence

from alembic import op

GrantMap = dict[str, dict[str, tuple[str, ...]]]

revision: str = "055_juli_app_sync_state_update"
down_revision: str | None = "054_juli_app_bronze_select"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_NAME = "juli_app"

GRANT_MAP: GrantMap = {
    "public": {
        # SELECT + INSERT already granted upstream; this adds the UPDATE that
        # every cursor advance after the first one needs.
        "tiktok_sync_state": ("UPDATE",),
    },
}


def _apply(verb: str, grant_map: GrantMap = GRANT_MAP) -> None:
    """GRANT or REVOKE the mapped privileges, guarded by table existence."""
    keyword, preposition = ("GRANT", "TO") if verb == "GRANT" else ("REVOKE", "FROM")
    for schema, tables in grant_map.items():
        for table, verbs in tables.items():
            verb_str = ", ".join(verbs)
            sql = f"""
DO $apply_grant$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = '{schema}' AND tablename = '{table}') THEN
    {keyword} {verb_str} ON {schema}.{table} {preposition} {ROLE_NAME};
  END IF;
END
$apply_grant$;
"""  # nosec B608 — schema/table/role/verbs are fixed module constants
            op.execute(sql)


def upgrade() -> None:
    """Grant UPDATE on tiktok_sync_state to juli_app. Idempotent."""
    _apply("GRANT")


def downgrade() -> None:
    """Revoke only the UPDATE this migration granted; SELECT/INSERT remain."""
    _apply("REVOKE")
