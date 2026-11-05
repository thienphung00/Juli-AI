"""Shopee recommendation cards (P90 step 8, ADR-121): generators per family, ranking,
predicted range, learning loop, simulation priors. See ``MODULE.md``.

Importing this package registers :func:`stale.on_stale_request` with the seller-import hook
(``shop_inputs.register_recompute_hook``), so an import that changes costs, caps or targets
flags the recommendations it affects.
"""

from __future__ import annotations

from juli_backend.services.shop_inputs.affected import register_recompute_hook
from juli_backend.services.shopee_recommendations.kol_cards import attach_kol_cards
from juli_backend.services.shopee_recommendations.measure import (
    apply_backfill,
    backfill_natural,
    run_learning,
)
from juli_backend.services.shopee_recommendations.mega import MegaWindow
from juli_backend.services.shopee_recommendations.refs import attach_card_refs
from juli_backend.services.shopee_recommendations.service import (
    WITHDRAW_REASONS,
    backfill_codes,
    card_by_code,
    card_detail,
    decide,
    expire_old,
    generate_cards,
    learning_overview,
    list_cards,
    mark_executed,
    publish,
    recompute,
    requeue,
    seller_view,
    sim_summary,
    withdraw,
)
from juli_backend.services.shopee_recommendations.sim_priors import (
    SimImportError,
    SimPriors,
    parse_priors,
)
from juli_backend.services.shopee_recommendations.stale import (
    mark_stale_for,
    on_stale_request,
    rerun_stale,
)
from juli_backend.services.shopee_recommendations.store import load_sim, save_card, save_sim

register_recompute_hook(on_stale_request)

__all__ = [
    "MegaWindow",
    "SimImportError",
    "SimPriors",
    "apply_backfill",
    "attach_card_refs",
    "attach_kol_cards",
    "backfill_codes",
    "backfill_natural",
    "card_by_code",
    "card_detail",
    "decide",
    "expire_old",
    "generate_cards",
    "learning_overview",
    "list_cards",
    "load_sim",
    "mark_executed",
    "mark_stale_for",
    "parse_priors",
    "publish",
    "recompute",
    "requeue",
    "rerun_stale",
    "run_learning",
    "save_card",
    "save_sim",
    "seller_view",
    "sim_summary",
    "WITHDRAW_REASONS",
    "withdraw",
]
