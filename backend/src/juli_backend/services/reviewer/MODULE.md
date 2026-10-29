# Module: services/reviewer

## Responsibility
Partner reviewer trial accounts (fast track P32-A, DECISIONS D42): accounts in
`ops_reviewer_accounts` (via `juli_ops`), the identity mask of every reviewer response,
the pinned shop's mask dictionary, the pure Duyệt → Thực thi simulation and the
provisioning command. The HTTP gate is `api/reviewer.py`. Contract:
`fasttrack/contracts/p32-reviewer-access.md`.

## Public Interface
- `accounts` — `ReviewerAccount`, `load_account` (cached `REVIEWER_ACCOUNT_CACHE_SECONDS`,
  default 30 s since P69), `claim_sign_in`, `upsert_account` / `renew_account` / `revoke_account` /
  `find_by_email` (audited, no commit), `DEFAULT_LIFETIME_DAYS` (30).
- `masking` — `MaskDictionary`, `ReviewerMasker`, `mask_payload`, `brand_terms`, `title_alias`,
  `id_alias`, `REVIEWER_SHOP_LABEL`. P74-A (D77): the reviewer mask's own labels, never "demo"
  (Shopee reads it as not live): shop `Shop TikTok (ẩn danh)`, `Sản phẩm NNN` / `Video NNN` /
  `LIVE NNN` / `Nhà sáng tạo NNN` / `Tệp NNN`, ids `an-<kind>-<hash8>` / `id-<hash8>` (own HMAC
  key, stable). The seller / ops analytics mask keeps ADR-038's "Demo …" / `demo-<kind>-…`.
  P75: structural and fail closed -- every identity field is aliased by its KEY (title / SKU
  keys, entity-record `title`/`name`, the report's `titles` / `seller_skus` maps, ranking rows by
  their table's `stream`) whatever the dictionary holds; the dictionary is the free-text layer. A
  product's alias is keyed on its TikTok product id (else SKU, else raw title) via
  `MaskDictionary.product_refs`, so one product reads one alias on every page.
- `catalog` — `load_dictionary` (products, SKUs, LIVE titles of the shop; 10 min cache). P75: also
  `product_refs` (Juli product id / TikTok SKU id / seller SKU / title → TikTok product id), from
  the same two statements (more columns, no extra round trip). P75c: a title or seller SKU code several
  listings share is left out of `product_refs` (ambiguous), so it never resolves to the first
  listing.
- `pin_cache` — P69: the pinned shop's row + `PinMode`, cached for the account TTL (30 s), per
  pin id (P74-A: several pins, each classified and cached on its own);
  `api/reviewer.enter_reviewer_shop` still applies the shop's tenant scope on every hit.
- `identity` — P69b: `load_identity(session, sub, pin)` → `ReviewerIdentity` (account, own
  `users` row values, pinned shop + `PinMode`). Cached (30 s); on a miss ONE load per
  concurrent burst per `(sub, pin)` (`core.security.SingleFlight`), three statements on
  Postgres (ops role switch; account + role restore + GUCs; users + shops + pin facts), no
  COMMIT. Writes (users provisioning/backfill, sign-in claim, audits) stay exact elsewhere.
- `config` — `reviewer_shop_ids` (P74-A, D77: `REVIEWER_SHOP_IDS`, comma-separated, default
  first; else `REVIEWER_SHOP_ID`), `reviewer_shop_id` (the default pin), `select_pin` (the pin an
  `X-Shop-Id` names by alias or real id, else the default -- selection only; the shop entry
  decides acceptance), `shop_alias_id`, `extra_mask_terms` (`REVIEWER_MASK_TERMS`).
- `simulation` — `simulate(card_item, step)`; imports no TikTok code.
- `sandbox` (fast track P64, D73) — the live sandbox pin: `classify_pin` → `PinMode`
  (`sandbox` only when the pin IS the sandbox credential's shop and holds no `production_read`
  row and no `production_write_shops` row; else masked, writes off, `reviewer_pin_production_shop`
  logged), `connection_info` (connection + synced at, no token), `claim_sync_slot` (one
  `poll_shop` per 60 s per shop). Writes (D73.4): the reviewer's Duyệt is the seller's own
  agent-run approve (`api/reviewer.py` `SANDBOX_RUN_ENDPOINTS`, sandbox pin only); the run
  writes through `SandboxWriteClientFactory` (`services/agent/composition`). P70 (owner,
  2026-10-28): "Hoàn tác" (`start_run_revert`) is on the same list, for a run the reviewer
  started only; the revert run stops at the same confirmation and writes through the same
  sandbox leg.
- `gotrue` — `GoTrueAdmin` (service-role admin calls; CLI only).
- `cli` — `python -m juli_backend.services.reviewer.cli create|renew|revoke|reset|show`. `reset` (P67, D75 Q4) retires the account (Supabase user banned and renamed `local+retired-<stamp>@domain`, ops row revoked under that address) and creates a fresh one: new user id, new `created_at`, so the sandbox reviewer's run history starts empty (`create` on an existing address keeps the same user and row).
- `enter_shop_read_scope` — re-export of `services/ops/view_as`.

## Invariants
- P75: on a masked pin no string under a product / SKU / shop / video / LIVE / creator key leaves
  unaliased, whether or not the catalog knows it (`tests/unit/test_p75_reviewer_structural_mask.py`
  builds each reviewer-reachable response shape from titles / SKUs outside the dictionary).
- Nothing here writes a tenant row; the only writes are `ops_reviewer_accounts` and
  `ops_audit_log`. The P64 live sandbox writes to TikTok (the sandbox shop only), never to a
  Juli table.
- No password is stored, logged or returned except the CLI's one-time stdout line.
- P74-A (D77): with several pins, everything a request does follows the pin `X-Shop-Id` selects
  (`api/reviewer.reviewer_gate`): a masked pin (Fujiwa) is read-only with the simulation, every
  sandbox-only route and "Đồng bộ ngay" refuse there (`tests/unit/test_reviewer_two_pins.py`);
  `classify_pin` logs `reviewer_pin_production_shop` as a warning for an expected production pin
  and as an error only when the sandbox credential's own shop turned production.
