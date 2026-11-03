"""Read-back verification events on ``card_events`` (P90 assisted execution, step 6)

Revision ID: 114_card_verification_events
Revises: 113_shopee_orders_and_logs
Create Date: 2026-11-04

P90 plan "Assisted execution" step 4: after a person saves an approved change in Seller Centre,
the Connector's next reading is compared with the expected value and one of three events is
logged on the card: ``verified`` (the new value was seen), ``mismatch`` (another value was seen
by the 48 h deadline), ``not_seen`` (nothing was seen by the deadline).

ALTERED: the CHECK ``ck_card_events_event_type`` is widened with the three names. They are not
single-per-card (a card can be executed, reverted and executed again), so the partial unique
index is unchanged; the writer's ``dedup_key`` carries the execution.

EXPAND-ONLY AND REVERSIBLE. A wider CHECK, no data change, no table, policy or grant touched.
``downgrade`` restores 112's list as ``NOT VALID`` (like 112's own downgrade): rows already
written with the new names are kept and not re-checked.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "114_card_verification_events"
down_revision: str | None = "113_shopee_orders_and_logs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "card_events"
CHECK = "ck_card_events_event_type"

#: Written out, not imported from the model: a migration must not change when the model does.
#: ``tests/unit/test_card_verification.py`` pins the new list equal to the model's.
EVENT_TYPES_112 = (
    "proposed",
    "shown",
    "accepted",
    "edited",
    "dismissed",
    "expired",
    "seller_done",
    "executed",
    "not_executed",
    "reverted",
    "impact_preliminary",
    "impact_final",
    "seller_change",
    "shadow",
    "superseded",
    "whatif_adjusted",
)
NEW_EVENT_TYPES = ("verified", "mismatch", "not_seen")
EVENT_TYPES = (*EVENT_TYPES_112, *NEW_EVENT_TYPES)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.drop_constraint(CHECK, TABLE, type_="check")
    op.create_check_constraint(CHECK, TABLE, f"event_type IN ({_in(EVENT_TYPES)})")


def downgrade() -> None:
    op.drop_constraint(CHECK, TABLE, type_="check")
    op.execute(
        f"ALTER TABLE public.{TABLE} ADD CONSTRAINT {CHECK} "
        f"CHECK (event_type IN ({_in(EVENT_TYPES_112)})) NOT VALID"
    )  # nosec B608 - fixed module constants
