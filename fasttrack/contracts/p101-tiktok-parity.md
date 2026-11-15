# P101 — TikTok Shop parity, one product for Shopee and TikTok

Owner grill, 15 Nov 2026 (decisions T1–T18). Supersedes `plan-2026-11-09.md` (#2264) where
they differ, and lifts D85.1 ("P94 / P95 wait"). P95's ask stands: P90–P92 features for every
TikTok seller on the Shopee screens, the reviewer sandbox on the same shell, sellers creating
Đề xuất themselves.

## 1. Goal and minimum bar

1. A TikTok shop opens the same shell as a Shopee shop: Tổng quan → Phân tích → Quyết định
   (Đề xuất · Thực hiện · Đo lường) → Dữ liệu shop. No platform fork in code.
2. Two gates. **Shop gate** `/v1/shops/{id}/…` = one shop on one platform. **Unified gate**
   `/v1/businesses/{id}/…` = one seller business across its Shopee and TikTok shops.
3. One data layer. Platforms differ only by mapper; no shop id or platform name selects a code path.
4. TikTok end to end: read and write through the Partner API wherever an endpoint exists; the
   Juli Connector only for actions with no TikTok write endpoint; every write verified.
5. Everything dynamic and automatic (T2): no per-shop config, no hand-run backfill or recompute,
   no shop id in source. Scripts survive only as break-glass wrappers of the automatic jobs.
6. One calculation everywhere (T6): the same (shop, metric, window) gives the same number on
   every screen, export, Ops view, recommendation, measurement and agent tool.

## 2. Architecture

### 2.1 Identity (T4)
- `businesses`; `business_members (user_id, business_id, role owner|member)` many-to-many;
  `shops.business_id` (one business per shop); `shops.kind real|sandbox|sample`.
- One account → many businesses → many shops on many platforms.
- Access = business membership, or a shop-level `shop_members` row (staff of one shop).
  `shops.user_id` stops being the access rule. Invites are self-serve by the business owner;
  the Ops-only invite (P93) is retired.
- Migration is automatic: each existing shop → its own business; its user + active members →
  business members.
- Connect runs inside the business selected in the switcher; a TikTok grant that returns several
  authorised shops attaches all of them; a first-time user gets a business named after the
  first shop. Moving a shop between businesses = owner action in Cài đặt.
- Token claims carry (business, optional shop).
- Cross-platform product match: seller SKU → barcode → title + price similarity with confidence;
  high links automatically, low stays separate; the seller can split a wrong match.

### 2.2 Four data layers (T5)
1. **Raw landing per platform**, replayable. TikTok: API/webhook payloads (today's `orders`,
   `order_items`, `products`, `settlements`, `analytics_performance_intervals` become this layer).
   Shopee: file rows and Connector payloads.
2. **One mapper per platform** through the ingest gateway (one-writer rule).
3. **Canonical tables** keyed `platform` + `shop_id`: `order_lines`, `order_settlements`,
   `affiliate_lines`, `platform_*`. The `shopee_*` names are renamed and dropped (compat views
   for one release only).
4. **Juli-computed, versioned** tables: `shop_metrics_daily`, `product_metrics_daily`,
   `source_metrics_daily`, each stamped with `DERIVATION_VERSION`.

Screens, recommendations, measurement and agent tools read layers 3–4 only. A CI guard bans
layer-1 reads outside the mappers. Legacy TikTok reads are removed in W4.

### 2.3 Metric registry (T6, owned by S1 — PR #2300)
- `services/metrics/{registry,components,compute,allocation}.py`; generated
  `apps/demo/src/lib/metrics/registry.generated.ts`.
- Each metric: formula over canonical components, unit, rounding, window/anchor rule, summable,
  per-platform source. Ratios computed from summed components, never averaged. The frontend
  formats, never recomputes.
- **Headline GMV = platform-reported (T8)**: Shopee shop totals; TikTok analytics shop
  performance. Doanh thu thực (net of cancels/returns) beside it; profit and margins on net.
- Shared traffic-source list: Organic (card, search, Shop tab) · Video · LIVE · Affiliate (TTLK /
  creators) · Ads (DVHT / GMV Max). Shared fee categories: commission, payment, service/program,
  shipping net, affiliate commission, ads, voucher, tax. Day boundary midnight Asia/Ho_Chi_Minh;
  money summed within one currency.
- TikTok mapper fills per day/scope: gmv, orders, units, line_gmv/orders/units, net_revenue,
  cogs (+cogs_known_gmv), packaging, fees, shipping_net, ads_spend, ads_gmv_platform,
  affiliate_commission, offer_promo/voucher/combo, other_marketing, views, clicks (per source),
  samples_cost, stock_units.
- Report spec for both platforms = ORY's request (T7): %, trend vs previous month and target,
  full cost structure, channel profit, product shares, KOC status, result → compare → cause → action.

### 2.4 Capabilities (T9)
- Per platform, in code: `services/capabilities/registry.py`,
  `can(platform, capability) → Capability(route api|connector|none, reason)`.
- Replaces the `_shopee()` 409 on 13 routes, `destinationsFor`, and the frontend platform checks.
- A shop lacking a granted scope or with expired auth is a connection state ("Cần cấp lại quyền
  TikTok"), not a capability difference.
- Capability ids: read_orders, read_shop_totals, read_ads, write_price, write_listing,
  write_stock, promo_discount, promo_flash_sale, voucher, bundle, affiliate_commission,
  ads_campaign, live_schedule, shop_tab. TikTok rows from W0 (docs, then sandbox).

### 2.5 Juli Connector (T11, T12 — split = PR #2301)
- Platform-free `core/` (pairing, jobs, scheduler, ingest, fill engine, UI) + `platforms/<id>/`
  packs behind `PlatformPack`; lint bans platform names and shop ids in core.
- Shop and platform only from the pairing token; one pairing per shop, several per install;
  server answers 409 `platform_mismatch`. `PILOT_SHOP_IDS`, `ORY_SHOP_ID`, `SAMPLE_SHOP_IDS` deleted.
- **On TikTok the Connector only does actions with no TikTok write endpoint.** The TikTok pack has
  form maps + saved signal only; no readers. Verification uses an API read when one exists, else
  the saved signal. When TikTok ships an endpoint, the registry flips the action to `api` and its
  form map is deleted.
- TikTok host `https://seller-vn.tiktok.com/*` is an optional host permission, requested after a
  TikTok pairing through a second button ("Cho phép truy cập TikTok Seller Center") whose click
  handler calls `chrome.permissions.request` first. Shopee-only installs never see it.

## 3. Functional requirements

| # | Requirement |
|---|---|
| F1 | Connect a TikTok shop by OAuth; all authorised shops attach to the selected business. |
| F2 | Backfill 90 days automatically, with progress ("Đang tải dữ liệu 90 ngày · n/90"). |
| F3 | Every tab renders for a TikTok shop from layers 3–4; TikTok-only rows (Video, LIVE, TikTok fees) shown; a metric the platform lacks shows "—" with the reason on hover (no captions). |
| F4 | Unified gate: Tổng quan columns per shop + total for summable metrics; Phân tích split by platform; Đề xuất lists cards across shops with a platform chip. |
| F5 | Engine cards and Tự tạo phương án (single or groups) offer only actions `can(platform, …)` allows. |
| F6 | The seller's approval is the only human decision (T10). After it, API actions run on the schedule inside guardrails; Connector actions are filled automatically and the seller clicks Lưu. |
| F7 | Every write is read back and verified; mismatch → one retry → rollback → card error. |
| F8 | A group is all-or-nothing within a 15-min start window (T14). |
| F9 | Measurement per card/group with frozen baseline; late data recomputes it ("cập nhật dd/mm"); Tối ưu shows keep · revert · next group. |
| F10 | Ops per-shop sync page: connection state, dataset freshness, job queue, errors. |
| F11 | Demo/ISV: one sample business with a Shopee and a TikTok sample shop, mirroring the real app, generated from registry components (S2); live TikTok sandbox stays connected (D73). |
| F12 | Self-serve business invites; business and shop switcher in the header. |

Route per action (W0 confirms): listing, price, stock, activate/deactivate, promotion activities =
API; voucher, affiliate plan, bundle = API if a create endpoint exists else Connector; GMV Max /
ads = Connector until the Business API scope exists (P5); LIVE schedule, Shop tab = Connector.
Juli auto-approval and Connector auto-save are out of scope (later, opt-in, after a ToS check).

## 4. Non-functional requirements (T15)

| Area | Target |
|---|---|
| Freshness | TikTok orders ≤ 15 min (webhook + hourly poll); TikTok analytics yesterday by 09:00 VN (W0 confirms lag); Shopee per Connector daily run |
| Backfill | 90 days ≤ 24 h after connect |
| Latency | Screens p95 < 800 ms, served from layer 4 |
| Writes | Applied ≤ 5 min after schedule; verified ≤ 10 min |
| Availability | API 99.5 %; workers resumable; idempotency key on every write |
| Isolation | RLS on `shop_id` + `business_id`; unified gate reads member shops only |
| Audit | Every write: approver, card/version, before → after, route, result; kept 2 years |
| Kill switches | Per platform, per action, per shop; effective ≤ 1 min without deploy |
| Privacy | No buyer PII stored (stripped in the mapper); client data lane-tagged and deletable |
| Cost | LLM ≤ $0.30 per shop per month; TikTok calls within each shop's quota |
| Capacity | Supabase Pro (owner, 15 Nov): full raw retention |
| Consistency | Golden same-number test in CI; nightly consistency sweep repairs or alerts |

## 5. Constraints

- TikTok write surface is limited to the Partner API allowlist (`integrations/tiktok/capabilities.py`);
  sandbox writes per D73; production writes behind the D71 write flag.
- No buyer PII on either platform → per-buyer voucher limits are not enforceable.
- Shopee-calibrated priors are low confidence on TikTok until a shop has its own history.
- TikTok backfill is per shop and rate-limited; re-consent is a shop event, not a code change.
- GMV Max / TikTok ads need the Business API scope (P5); until then Connector or "—".
- Connector store review: TikTok section in PRIVACY.md and STORE_LISTING.md.
- Fast-track gate: full deploy gate + `eslint .` in apps/demo; run `df` before test-running agents;
  owner merges PRs and runs worktree add/remove and `pnpm install`.

## 6. States (T13)

| Machine | States |
|---|---|
| Shop connection | connecting → backfilling → active ⇄ degraded → needs_reauth → disconnected |
| Dataset freshness | pending → loading (n/90) → fresh ⇄ stale → failed (retrying); "Số liệu đến dd/mm" |
| Card / option / group | draft → proposed → approved → scheduled → running → measuring → measured → Tối ưu; exits rejected · expired · withdrawn · blocked |
| Execution step | queued → applying → applied → verifying → verified; retrying → failed → rolling_back → rolled_back; Connector: filled_waiting_save → saved \| timed_out |
| Measurement | baseline_frozen → collecting → enough_data → result; contaminated |

needs_reauth / disconnected → pause automatically, resume automatically: scheduled steps hold,
live promotions stay, gap days are missing in measurement; on re-auth read back, drift →
contaminated with a re-apply / keep choice; 14 days without re-auth → plan expired + one e-mail.

## 7. Errors and edge cases (T14)

| Case | Handling |
|---|---|
| Token expired / revoked | Silent refresh; failure → needs_reauth, pause (§6) |
| 429 | Per-shop backoff with jitter; writes before backfill; resumable cursor |
| 5xx / timeout | 3 retries → failed → rollback; dataset stale |
| Missed webhook | Hourly poll; nightly reconcile → day rebuild |
| Late cancel / refund / settlement | Day rebuild; measurement recompute "cập nhật dd/mm" |
| Read-back mismatch | 1 retry → rollback; drift logged |
| Seller edit during a run | contaminated; seller value kept; offer re-apply |
| Connector wrong page / shop / form changed | Stop, nothing filled; Ops alert on form_changed |
| No Lưu | timed_out after 24 h, one reminder, back to queued |
| Guardrail breach | blocked before any write |
| Group partial failure | Roll back applied siblings within the 15-min window; group failed |
| Same product on both platforms | Separate cards; one unified row |
| Listing deleted | Cards withdrawn; partial result |
| Sandbox / sample | Sandbox writes per D73; sample shops never call a platform |

## 8. Hard-codes removed (T17)

| Hard-code | Replaced by | Owner |
|---|---|---|
| `PILOT_SHOP_IDS`, `ORY_SHOP_ID`, `SAMPLE_SHOP_IDS` | Pairing token | S1 (#2301) |
| `NEVER_SAMPLE_SHOP_IDS` (Fujiwa id, `reviewer/config.py:41`) | `shops.kind` | S2 |
| `_shopee()` 409 on 13 routes | `can()` + shop gate | TikTok session (W3) |
| `destinationsFor` / `APP_DESTINATIONS` | One shell | TikTok session (W3) |
| `platform === "tiktok"` in 27 frontend files | API platform labels + capability flags | TikTok session (W3) |
| `PLATFORM = "shopee"` constants, ~45 `shopee_*` modules | Neutral modules + T5 renames | S1 |
| `shops.user_id` as access rule, Ops-only invites | Business membership | TikTok session (W1) |
| `TIKTOK_APP_REVIEW_USER_ID` default id | Reviewer account resolved from a row | TikTok session (W6) |
| ORY category table in the fee seed | `platform_fee_formulas` rows | S1 |
| Hand-run backfill / recompute scripts | T3 automatic jobs | S1 |

## 9. Acceptance tests

1. CI guards: no UUID literal in `backend/src` / `apps/*/src` outside migrations and tests; no
   platform name in Connector core; no `== "shopee"` / `== "tiktok"` outside registry and mappers;
   no layer-1 reads outside mappers.
2. Golden tests: one Shopee and one TikTok fixture shop; every endpoint returns the same number
   per metric. ORY October 2026 is the Shopee case (GMV 21 336 200 · 123 đơn · ads 3 397 017 ·
   profit 2 838 185; "Cả shop" = −ad spend).
3. New shop, zero config: a new TikTok sandbox shop connects, backfills, renders every tab, takes
   a card to a verified write, and appears in its business's unified view.
4. A contract test per state machine; every §7 row replayed against a fake platform.

## 10. Phases (T18)

| Phase | Work | Waits on | Size |
|---|---|---|---|
| W0 Probe | Docs research (part 1), then live sandbox probe (part 2, owner OK); TikTok capability rows on #2300; TikTok shapes, source keys, fee keys and `can(tiktok, …)` list to S2 | — | 2 |
| W1 Identity | Migration `130_businesses` (businesses / business_members / shops.business_id / shops.kind); access by membership; self-serve invites; switcher | — | 4–5 |
| W2 TikTok mapper + backfill | Raw → canonical, registry components; connect → 90-day backfill → automatic rebuilds; nightly reconcile | S1 registry module + T5 renames | 8–10 |
| W3 Gates + analytics + one shell | `can()` on the 13 routes; shell fork (`destinationsFor`) removed in the same PR so a TikTok shop never lands on a screen that still 409s; frontend platform checks removed; unified-gate endpoints; "—" + hover reason | W1, W2, S1 capabilities module | 5–6 |
| W4 Cards → execution → measurement | TikTok generators + Tự tạo via `can()`; API writers with read-back / retry / rollback; groups all-or-nothing; state machines, audit, kill switches; legacy action cards retired | W3 | 9–11 |
| W5 Connector TikTok pack | `platforms/tiktok/pack.ts` form maps for connector-routed actions; second permission button | #2301 merged, W0 | 3 |
| W6 Reviewer on the shell | Sandbox shop on the shell (pin, mask, D73); new-shop-zero-config E2E | W4, S2 TikTok sample | 3 |
| P5 Ads / GMV Max | Business API when the scope exists | TikTok scope approval | 5–8 |

W0 ∥ W1 start now; then W2 → W3 → W4 with W5 alongside, then W6. About 34–40 agent-days. One PR
per phase into `fasttrack/optimize-product`; the owner merges. Sonnet by default, Opus for
migrations, security and integration.

## 11. Ownership

- **S1** (`juli-ai-v2-3c`): metric registry + capabilities module (#2300), Shopee renames (T5),
  automatic rebuilds (T3), Connector split (#2301), the ORY report fixes.
- **S2** (`juli-ai-v2-ed`): sample shops — TikTok sample + two-shop sample business, `shops.kind`
  use in reviewer config.
- **TikTok session** (`juli-ai-v2-27`): W0–W6, P5; TikTok capability rows; TikTok pack.

Grill log with the full decision text: owner's local `tiktok-parity-grill-2026-11-15.md`.
