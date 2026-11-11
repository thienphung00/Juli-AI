"""Juli Ops "Từ khóa" (ADR-119): keyword combinations from the shop's own titles, with
public search metrics the owner collects on shopeeanalytics.com.

``api/routes/ops_shopee_keywords.py`` is the Ops skin over this package.

- :mod:`.decompose` -- pure title → keyword-combination decomposer (D81.4 / D81.6);
- :mod:`.collection` -- the JSON Lines collection format and the raw-capture converter (D81.8);
- :mod:`.llm_seeds` -- the one model call per shop that refines the candidates (P100-G);
- :mod:`.seeds` -- ``shop_keyword_seeds`` (client lane, under the shop's scope);
- :mod:`.metrics` -- ``market_keyword_metrics`` (public lane, as ``juli_ops``);
- :mod:`.dashboard` -- the board joining the two.
"""

from __future__ import annotations

from juli_backend.services.shop_keywords.collection import (
    CollectionError,
    CollectionRecord,
    from_raw,
    parse_jsonl,
    parse_records,
)
from juli_backend.services.shop_keywords.dashboard import (
    DEFAULT_MIN_VOLUME,
    board,
    build_board,
)
from juli_backend.services.shop_keywords.decompose import Candidate, Title
from juli_backend.services.shop_keywords.metrics import StoreResult, store_records
from juli_backend.services.shop_keywords.seeds import (
    MAX_BRAND,
    GenerateResult,
    SeedNotFound,
    generate,
    seed_json,
    set_enabled,
)

__all__ = [
    "DEFAULT_MIN_VOLUME",
    "MAX_BRAND",
    "Candidate",
    "CollectionError",
    "CollectionRecord",
    "GenerateResult",
    "SeedNotFound",
    "StoreResult",
    "Title",
    "board",
    "build_board",
    "from_raw",
    "generate",
    "parse_jsonl",
    "parse_records",
    "seed_json",
    "set_enabled",
    "store_records",
]
