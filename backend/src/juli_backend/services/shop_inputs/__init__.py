"""The seller's imported inputs (P90 step 4, ADR-120 d.12): Cài đặt › Thông số shop.

Template (``template``), parse / validate / diff / apply (``importer``), versioned writes
and restore (``versions``), the cost fallback (``fallback``), the recommendations an
input change re-runs (``affected``), and the screen's read model (``overview``). Storage
is the existing ``shop_rules`` projection plus ``shop_rule_versions`` history; no table of
its own.
"""

from __future__ import annotations

from juli_backend.services.shop_inputs.affected import (
    AffectedRecommendations,
    StaleRequest,
    affected_recommendations,
    mark_stale,
    register_recompute_hook,
    unregister_recompute_hook,
)
from juli_backend.services.shop_inputs.catalogue import (
    CatalogueSku,
    load_catalogue,
    load_current,
    sku_scope,
    split_scope,
)
from juli_backend.services.shop_inputs.fallback import (
    ASSUMED_COST_SHARE,
    OWNER_DEFAULT_GROSS_MARGIN_PCT,
    CostFallback,
    assumed_cost,
    cost_fallbacks,
)
from juli_backend.services.shop_inputs.importer import (
    KIND_LABELS,
    SUGGESTED_REASONS,
    ApplyResult,
    FieldDiff,
    FileMismatch,
    ImportFileError,
    ImportPreview,
    NothingToApply,
    Rejection,
    apply_import,
    preview_affected,
    preview_import,
)
from juli_backend.services.shop_inputs.overview import build_overview, versions_index
from juli_backend.services.shop_inputs.template import TemplateResult, build_template
from juli_backend.services.shop_inputs.versions import (
    Actor,
    ChangeSet,
    RuleChange,
    VersionError,
    VersionNotFound,
    list_versions,
    restore_sku_version,
    restore_version,
    sku_history,
    write_rule,
    write_version,
    write_versions,
)
from juli_backend.services.shop_inputs.xlsx_io import MAX_FILE_BYTES

__all__ = [
    "ASSUMED_COST_SHARE",
    "KIND_LABELS",
    "MAX_FILE_BYTES",
    "OWNER_DEFAULT_GROSS_MARGIN_PCT",
    "SUGGESTED_REASONS",
    "Actor",
    "AffectedRecommendations",
    "ApplyResult",
    "CatalogueSku",
    "ChangeSet",
    "CostFallback",
    "FieldDiff",
    "FileMismatch",
    "ImportFileError",
    "ImportPreview",
    "NothingToApply",
    "Rejection",
    "RuleChange",
    "StaleRequest",
    "TemplateResult",
    "VersionError",
    "VersionNotFound",
    "affected_recommendations",
    "apply_import",
    "assumed_cost",
    "build_overview",
    "build_template",
    "cost_fallbacks",
    "list_versions",
    "load_catalogue",
    "load_current",
    "mark_stale",
    "preview_affected",
    "preview_import",
    "register_recompute_hook",
    "restore_sku_version",
    "restore_version",
    "sku_history",
    "sku_scope",
    "split_scope",
    "unregister_recompute_hook",
    "versions_index",
    "write_rule",
    "write_version",
    "write_versions",
]
