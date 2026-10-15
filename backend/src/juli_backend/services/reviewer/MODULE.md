# Module: services/reviewer

## Responsibility
Partner reviewer trial accounts (fast track P32-A, DECISIONS D42): accounts in
`ops_reviewer_accounts` (via `juli_ops`), the identity mask of every reviewer response,
the pinned shop's mask dictionary, the pure Duyệt → Thực thi simulation and the
provisioning command. The HTTP gate is `api/reviewer.py`. Contract:
`fasttrack/contracts/p32-reviewer-access.md`.

## Public Interface
- `accounts` — `ReviewerAccount`, `load_account` (cached `REVIEWER_ACCOUNT_CACHE_SECONDS`,
  default 15 s), `claim_sign_in`, `upsert_account` / `renew_account` / `revoke_account` /
  `find_by_email` (audited, no commit), `DEFAULT_LIFETIME_DAYS` (30).
- `masking` — `MaskDictionary`, `ReviewerMasker`, `mask_payload`, `brand_terms`, `title_alias`.
- `catalog` — `load_dictionary` (products, SKUs, LIVE titles of the shop; 10 min cache).
- `config` — `reviewer_shop_id` (`REVIEWER_SHOP_ID`), `shop_alias_id`, `extra_mask_terms`
  (`REVIEWER_MASK_TERMS`).
- `simulation` — `simulate(card_item, step)`; imports no TikTok code.
- `gotrue` — `GoTrueAdmin` (service-role admin calls; CLI only).
- `cli` — `python -m juli_backend.services.reviewer.cli create|renew|revoke|show`.
- `enter_shop_read_scope` — re-export of `services/ops/view_as`.

## Invariants
- Nothing here writes a tenant row; the only writes are `ops_reviewer_accounts` and
  `ops_audit_log`.
- No password is stored, logged or returned except the CLI's one-time stdout line.
