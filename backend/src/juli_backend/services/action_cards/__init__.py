"""Action Card persistence and manual refresh — P2-B1 (#303, ADR-021)."""

from juli_backend.services.action_cards.card_groups import GroupError, group_views
from juli_backend.services.action_cards.dispatch import (
    enqueue_action_card_refresh,
    get_refresh_dispatcher,
    set_refresh_dispatcher,
)
from juli_backend.services.action_cards.legacy_recommendations import (
    persist_legacy_recommendations,
)
from juli_backend.services.action_cards.persist import (
    emit_scoring_cards,
    persist_scoring_result,
)
from juli_backend.services.action_cards.refresh import (
    maybe_poll_tiktok_data,
    run_action_card_refresh,
)
from juli_backend.services.action_cards.refresh_cooldown import (
    bind_action_card_refresh_cooldown_gate,
    get_refresh_cooldown_gate,
    set_refresh_cooldown_gate,
)

# Lazy (fast track P53, D62): the Ops routes and the rescore task reached these by
# deep import (`check_import_boundaries.py` reports that), always inside a function
# body. `optimize_product_cards` imports `services.optimize_product`, so an eager
# re-export here could turn into a package-init cycle; deferring to first attribute
# access keeps this package's import-time behaviour unchanged. Same shape as
# `services/tiktok/__init__.py`.
_LAZY_EXPORTS = {
    "open_cell_counts": "juli_backend.services.action_cards.emission_budget",
    "rescore_shop_cards": "juli_backend.services.action_cards.optimize_product_cards",
}


def __getattr__(name: str):
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module(module_path)
    return getattr(module, name)


__all__ = [
    "GroupError",
    "bind_action_card_refresh_cooldown_gate",
    "emit_scoring_cards",
    "enqueue_action_card_refresh",
    "get_refresh_cooldown_gate",
    "get_refresh_dispatcher",
    "group_views",
    "maybe_poll_tiktok_data",
    "open_cell_counts",
    "persist_legacy_recommendations",
    "persist_scoring_result",
    "rescore_shop_cards",
    "run_action_card_refresh",
    "set_refresh_cooldown_gate",
    "set_refresh_dispatcher",
]
