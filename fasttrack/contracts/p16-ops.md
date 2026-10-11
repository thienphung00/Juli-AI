# P16 contract — Juli Ops (internal console) + P9-B handover

Owner decisions: DECISIONS **D25** (items 1–15, incl. the 2026-10-10 additions and the
D25.3 amendment) and **D27** (speed, confirmations, audit log — §8; migration
`085_ops_daily_precompute`). Artboards: `docs/product/design/ops/` (OpsOverview, OpsViewAs,
OpsShopSettings, OpsSimulate — **OpsSimulate is implemented as drawn and still needs the
owner's explicit review**). Owner steps: `docs/runbooks/ops-console-runbook.md`.

One migration, **`083_ops_console`** (onto `081_order_cost_data` on this branch; the
orchestrator re-chains it after P15's `082_content_analysis` at merge). The deferred
`074_users_placeholder_phone_cleanup` is re-parented onto 083 and stays the tail.

## 1. Gates (every `/v1/ops/*` route, fail closed)

| # | Gate | Failure |
|---|---|---|
| 1 | `Cf-Access-Jwt-Assertion` verified (`core/security/cf_access.py`): RS256 against `https://<team>.cloudflareaccess.com/cdn-cgi/access/certs`, `aud` = `CF_ACCESS_AUD`, `iss` = team URL, `exp`, `email` in `OPS_ALLOWED_EMAIL_DOMAIN` (default `app-juli.com`). Missing header / config / certs → deny. `OPS_CF_ACCESS_BYPASS=1` works outside production only. | 403 |
| 2 | Supabase JWT (`get_current_user`) | 401 |
| 3 | Active `ops_staff` row for the user (seeded by e-mail, bound to the Supabase user id on first sign-in); its e-mail must equal the Access e-mail | 403 |
| 4 | Role: `viewer` (Xem) < `operator` (Vận hành) < `admin` (Admin) | 403 |

Database precondition: the runtime login role must be a member of `juli_ops`
(`GRANT juli_ops TO <role>;`). Without it `SET LOCAL ROLE juli_ops` is refused and
every `/v1/ops/*` route answers **503** `{"detail": "Thiếu quyền juli_ops cho database —
chạy GRANT juli_ops TO <role>."}` (`<role>` = the session's `current_user`; log
`ops_role_missing`, once per request) — never a bare 500. The deploy refuses a release
while the grant is missing (runbook §"Kiểm tra khi deploy").

Every response is re-serialised through `services/ops/masking.mask_pii` (route class
`MaskedRoute`): buyer/recipient/phone/address keys → `•••`, phone numbers in text →
`•••`, non-staff e-mails → `abcdef…@…`.

## 2. Data (migration 083)

| Object | Notes |
|---|---|
| role `juli_ops` | NOLOGIN, no BYPASSRLS; granted to every LOGIN member of `juli_app`. The ops path does `SET LOCAL ROLE juli_ops` around ops-table work (`services/ops/access.ops_role`) and back. |
| `ops_staff` | `email` (lower, unique), `user_id` (unique, NULL until first sign-in), `role`, `active` |
| `ops_audit_log` | `actor_staff_id`, `actor_email`, `shop_id`, `action`, `before`/`after` JSON, `at`; 085 adds `field` (the one setting / rule a change touched, NULL for a multi-key save) and `merged_count` (default 1). `juli_ops` has SELECT, INSERT and, since 085, UPDATE (merge) and DELETE (undone merge, retention). |
| `ops_shop_settings` | per shop: `stage` (`trial`/`self`/`pilot`), overrides (NULL = Mặc định): `card_daily_limit`, `card_weekly_limit`, `card_open_limit`, `enabled_streams`, `enabled_actions`, `content_cards_enabled`, `promotion_api_enabled`, `openai_model` |
| `ops_sim_scenarios` | `shop_id`, `name`, `deltas` JSON `{stream:{kpi:pct}}`, `is_target` (≤ 1 per shop, partial unique index) |
| `ops_shop_daily_summary` (085) | one row per shop: the Tổng quan numbers + `generated_at` / `data_through` (D27.1); ops-only like the rest |
| `shop_daily_streams` / `shop_daily_products` (085) | tenant tables (RLS via `app_current_shop_id()`, `juli_app` SELECT/INSERT/UPDATE, no DELETE): one row per shop × stream (× product) × day — impressions, clicks, SKU orders, GMV — written when the diagnosis report is built (D27.2) |
| `ops_shop_invites` | `email`, `token_hash` (sha256; token only in the e-mail), `expires_at` (7 d), `keep_ops_access`, `accepted_at`, `accepted_user_id`, `seller_kept_ops_access`, `revoked_at` |
| `users.staff_access_consent_at` | D25.6, stamped by the connect start; `juli_app` may UPDATE this column on its own row |
| `ops_current_shop_overrides()` | DEFINER; returns only `app_current_shop_id()`'s row; EXECUTE `juli_app`, `juli_ops` |
| `ops_list_shops()` | DEFINER; every shop + owner id / e-mail / consent; EXECUTE `juli_ops` only |
| `ops_transfer_shop(shop, user)` | DEFINER; the P9-B ownership move; EXECUTE `juli_ops` only |

All five 083 tables (and 085's `ops_shop_daily_summary`): RLS on, one policy `FOR ALL TO juli_ops`, nothing granted to `juli_app`,
`anon`, `authenticated`; classified `ops_only` in `database/tenant_scoped_tables.py`.

**Monthly OpenAI cap** (D25.8, shared with P15): a `shop_rules` row
`rule_key = "openai_monthly_cap_usd"`, `scope_ref = ''`, value USD; no row → default
`OPENAI_MONTHLY_CAP_USD_DEFAULT` (env, **$5**). Not a seller rule key (the seller route
refuses it). Accessor: `services/shop_rules/openai_cap.py` (`openai_monthly_cap_usd`,
`set_openai_monthly_cap`, `clear_openai_monthly_cap`). Ops exposes it as the override
`openai_monthly_cap_usd`.

## 3. Who reads the overrides (defaults unchanged when unset)

| Override | Reader |
|---|---|
| card limits | `action_cards/emission_budget.apply_emission_budget` (replace D24.17 limits; the seller's "Số thẻ mở cùng lúc" can still only lower the open cap) |
| streams / actions / content on-off | the same budget suppresses a draft (`suppressed_reason = "ops_disabled"`); `content_cards.emission` writes no card for an off content kind |
| `openai_model` | content drafting (`content_cards.planner` via `driver.draft_gate_for`) and agent runs (`workers/tasks/agent_workflow._ops_llm_config`); only priced models allowed |
| monthly cap | content drafting stops (run `failed`, `content_run.error = "openai_cap_reached"`); Optimize Product model calls refused (`CapGuardedLLMService` → `LLMProviderError`); log `ops_openai_cap_reached`; overview badge. Rule cards unaffected. Spend = this month's (UTC+7) `workflow_runs.cost_usd`. |
| `promotion_api_enabled` | stored/shown/audited; gates nothing yet (Juli makes no promotion write, D13) — DEBT |

## 4. Endpoints

| Method + path | Role | Notes |
|---|---|---|
| GET `/v1/ops/me` | Xem | `{email, role, role_label}` |
| GET `/v1/ops/overview` | Xem | `generated_at` (the OLDEST summary shown — "cập nhật lúc") + `data_through` (oldest last analytics day among connected shops, else all; `YYYY-MM-DD` or null) + totals (`accounts, connected, active, disconnected, cards_approved_30d, approval_rate_30d, openai_cost_month_usd, openai_cap_alerts`) + `shops[]` (stage, connection `ok/expired/none`, last poll / diagnosis, cards open / approved 30d / rejected 30d, approval rate, failed runs 30d, OpenAI month + cap + reached, GMV 30d, `permissions`, and per-row `generated_at` / `data_through`). Read from `ops_shop_daily_summary`; a shop with no row yet is computed once and stored (D27.1) |
| POST `/v1/ops/overview/refresh` | Vận hành | "Làm mới": recompute every shop's summary now; same body as GET; audited as `data_refresh` (kind `view`, `after = {target: "overview"}`) |
| GET/PUT `/v1/ops/staff` | Admin | upsert `{email, role, active}`; the last active Admin cannot be removed |
| GET `/v1/ops/audit?shop_id=&kind=&limit=` | Xem | newest first; `kind` ∈ `config` / `view` / `system` filters (422 otherwise); `limit` 1–500, default 100. Each row: `{id, at, actor_email, shop_id, action, kind, field, merged_count, before, after}` (§8) |
| GET `/v1/ops/shops/{id}/settings` | Xem | `{shop, settings{stage, overrides, defaults, options}, invites, audit}` |
| PUT `/v1/ops/shops/{id}/settings` | Vận hành | `{changes:{…}}`; `null` = back to default; 422 on invalid. One save = **one** audit row listing every changed key (`before`/`after` hold only changed keys); `field` = the key when exactly one changed, else null (§8 merge rules). Unchanged values write no row |
| POST `/v1/ops/shops/{id}/settings/reset` | Vận hành | "Về mặc định" |
| GET/PUT/DELETE `/v1/ops/shops/{id}/rules[/{key}]` | Xem / Vận hành | D25.14: the seller's rules (same storage + validation as `/v1/demo/rules`), always `set_by = team`, audited before/after |
| GET `/v1/ops/shops/{id}/runs[/{run}]` | Xem | read-only run detail: timeline (events), LLM output (assistant text + content drafts), tokens, cost |
| POST `/v1/ops/shops/{id}/view-session` | Xem | `{mode: view|exit}` — logs every "Xem như shop" session |
| GET `/v1/ops/shops/{id}/view/{analysis, analysis/rankings, decisions, rules, runs, runs/{id}, runs/{id}/changes, runs/{id}/instructions, runs/{id}/measurement, revert-questions}` | Xem | the SAME handlers as the seller's routes, under the shop's tenant scope |
| any non-GET under `/v1/ops/shops/{id}/view/` | — | **403** (D25.3 amended: always read-only; there are no act routes) |
| GET `/v1/ops/shops/{id}/simulation?window=7|14|30|90` | Xem | baseline + trend + bands + volatility + scenarios (§5), plus `data_through` (last day in the compact table) and `generated_at` (when that newest day was written; null when read from report JSON) and `rebuilding` (true when the shop had no daily rows and a forced diagnosis rebuild was just queued — the UI says the numbers are on their way; at most one forced build per shop per 6 h) |
| POST `/v1/ops/shops/{id}/simulation/refresh?window=` | Vận hành | "Làm mới": re-derive this shop's compact daily rows from its latest stored report + recompute its Tổng quan summary; same body as GET; audited `data_refresh` (`after = {target: "simulation", window}`) |
| POST `/v1/ops/shops/{id}/simulation/compute` | Xem | `{window, deltas}` → GMV result + actions |
| POST/PATCH/DELETE `/v1/ops/shops/{id}/scenarios[/{id}]` | Vận hành | `{name, deltas, is_target}`; one target per shop |
| GET/POST `/v1/ops/shops/{id}/invites` | Xem / Vận hành | P9-B; e-mail via SMTP, else `accept_url` returned for staff to forward |
| POST `/v1/ops/shops/{id}/disconnect` | **Admin** | D25.13 `{reason, confirm_name}`; idempotent; audited |
| GET `/v1/shop-invites/preview?token=` · POST `/v1/shop-invites/accept` | seller (signed in) | only the invited, verified e-mail; 404 / 409 used / 410 expired / 403 wrong account |
| GET `/v1/shops/me/permissions` | seller | D25.15 `{status: complete|missing|unknown|not_connected, missing[], needs_reconnect}` |
| GET `/v1/auth/tiktok/start?staff_access_consent=true` | seller | stamps `users.staff_access_consent_at` |

## 5. Simulation (D25.10, D25.11)

Data (D27.2, migration 085): the simulation reads the compact `shop_daily_streams` /
`shop_daily_products` rows, written when the diagnosis report is built — not the stored
report JSON. Reports stored before 085 are copied into them once, on the first read that
finds none (no TikTok call). The paragraph below describes the report fields those rows
come from. Originally: the daily diagnosis report gains (additive) `daily_streams`
`{stream:{day:[impressions, clicks, sku_orders, gmv]}}` and `daily_products` (top 15 per
stream, same shape per product); `daily_products` is stripped from the seller's analysis
payload. Every stored report of the shop is merged (newest wins per day), so history grows
beyond 60 days as the job runs. **Today a shop has ≤ 60 days**: windows 7 / 14 / 30 are
fully computable (2N ≤ 60); 90 is not (needs 180 days) and is returned with
`baseline_available = comparable = false` (greyed, "Chưa đủ dữ liệu (cần 2 × N ngày)").

Per window N: baseline = per-day average of the last N days (impressions/day; CTR =
clicks/impressions; CTOR = SKU orders/clicks; AOV = GMV/SKU orders); trend = last N vs the
N before (▲/▼, grey under 0.5 %); band = p10–p90 of the daily values, `band_pct` = the
larger distance from the mean in % of it; CV of daily impressions → stable < 0.15 ≤
medium < 0.30 ≤ volatile. GMV/day = Hiển thị × CTR × CTOR × AOV per stream; ±5 % steps;
locked: Video CTOR, Video AOV, LIVE AOV; Hiển thị flagged indirect; a delta within
`band_pct` is "Trong dao động thường ngày". Actions per changed cell from the lever map.

## 6. Handover (P9-B, D25.7)

Ops "Mời seller" → invite (older pending ones revoked) → e-mail → seller opens
`/nhan-shop?token=…` on the seller app, signs in with that e-mail, accepts →
`ops_transfer_shop` moves `shops.user_id`; cards, runs, rules, history stay (all keyed on
`shop_id`). The seller's answer to "let the team keep Vận hành access" is stored on the
invite (`seller_kept_ops_access`); since D25.3's amendment that means the team keeps
managing Ops settings, never acting in the seller's client.

## 7. Disconnect (D25.13)

TikTok Shop has no token-revoke endpoint: Juli overwrites the stored tokens with a
non-token marker, sets the credential `needs_reauth`, `shops.is_active = false` (poll +
card generation stop), sets `cancel_requested` on queued / running / waiting runs, keeps
history, e-mails the owner. Reconnecting through the normal connect flow writes fresh
tokens, resets the credential to `active` and the shop to active.

## 8. D27 — freshness, confirmations, audit log

**Daily precompute (D27.1, D27.2).** Tổng quan and Mô phỏng read numbers computed once a
day, right after the shop's daily analytics pass. Both responses carry `generated_at`
(ISO datetime) and `data_through` (ISO date) for "Số liệu đến hết DD/MM · cập nhật lúc
HH:MM". "Làm mới" = `POST /v1/ops/overview/refresh` (all shops) or
`POST /v1/ops/shops/{id}/simulation/refresh` (this shop); both Vận hành, both audited as
`data_refresh`. Commerce polling is hourly (D27.3; `SHOP_COMMERCE_INTERVAL_MINUTES = 60`).

**Audit kinds (D27.4).** Derived from `action`, not stored, so older rows classify the
same: `view` = `view_as_view`, `view_as_exit`, `data_refresh`; `system` = actions
prefixed `system_`; `config` = everything else. `GET /v1/ops/audit?kind=` filters by it.

**One save = one row (D27.5).** A multi-key settings PUT writes ONE row with
`field = null`, `before`/`after` = only the changed keys; a no-op save writes nothing.
Rule PUT/DELETE set `field = "<rule_key>:<scope_ref>"`.

**Merging (D27.6).** A `config` row that names one `field`, by a staff actor (never
the system), merges into that actor's previous row for the same shop + action + field
written within **10 minutes**: the row keeps its first `before`, takes the new `after`,
`merged_count += 1`, `at` moves to now. If the merged `after` equals the original
`before` (the change was undone) the row is deleted — nothing stays logged. Multi-key
rows (`field = null`) and `view`/`system` rows never merge.

**No reason field (D27.7)** except Huỷ kết nối (`reason` stays required).

**Retention (D27.4).** `config` rows 365 days; `view` and `system` rows 90 days. The
nightly Celery beat entry `ops-audit-retention` (task `juli_backend.ops_audit_retention`,
20:31 UTC = 03:31 UTC+7, default queue) deletes expired rows
(`services/ops/audit.purge_expired`); index on `at` (085) + (`shop_id`, `at`) (083).
