# P100 Session 2 — ISV demo client ("Dữ liệu mẫu" shop)

Started 2026-11-11, in parallel with Session 1 (`p100-a/b/c/g`). Source: `p100-session-briefs.md`
§B.2, §B.18, §B.22–23, §F. Base: `fasttrack/p99-combo` 250217be + 55922fb7 (§J).
Standing rules unchanged (ask before push/tag/SSH/merge; never write Fujiwa `2b1da87b-…` or
ORY; synthetic data only in the repo; the owner runs every prod command).

## What exists today (read 2026-11-11)

- No Shopee sample shop. The sample modes (`demo-landing`, `no-shop-sample-strip`,
  `lib/quyet-dinh/sample-data.ts`, reviewer `sample`) are client-side fixtures, TikTok-era.
- The reviewer account (`services/reviewer/`, migration 090) pins shops through
  `REVIEWER_SHOP_IDS`; `sandbox.pin_mode` gives `sandbox` (Juli's TikTok sandbox shop, live
  writes) or `masked` (any other shop: identity mask on, read-only, simulated Duyệt/Thực thi).
- Shopee data enters only through `POST /v1/ingest/{platform}/{dataset}`
  (`services/ingest/gateway.py`, datasets in `services/ingest/mapping.py:DATASETS`, row models in
  `services/ingest/schemas.py`), then `materialize.after_ingest` rebuilds
  `shopee_*_metrics_daily`. Costs (giá vốn) come from `services/shop_inputs`.
- `Shop` has no sample/synthetic flag.

## Slices that can start now (no file overlap with Session 1)

### S2-A — synthetic shop generator + loader (data-platform)
- `scripts/sample_shop/`: a deterministic generator (fixed seed) of a minimal Shopee shop: 6
  products (household goods, synthetic brand and names, ORY-like price/AOV/traffic shapes,
  1–3 variations each), 30 days ending on a given date, every day present. It produces
  **Connector-shaped `IngestBody` rows** for the datasets the Shopee screens read (orders +
  income, catalog/snapshot, shop + product + per-source traffic, ads campaign daily, promotions
  incl. one running Combo Khuyến Mãi) plus the shop-input costs, so the shop goes through the
  same gateway → materialize path as a real Connector.
- Loader: `--dry-run` (writes JSONL only), in-process `--database-url` (local), never a default
  remote DB. It creates the shop itself (Shopee platform, name "Dữ liệu mẫu", reserved
  synthetic `shopee_shop_id` range) and **refuses any target shop it did not create** (no
  credentials, id in the reserved range) and the Fujiwa / sandbox ids by name.
- Test: Postgres test DB, generate → ingest → materialize → the Shopee analytics read model
  returns all 30 days, product ≤ shop every day, known-cost profit non-NULL, ads ROAS sane.

### S2-B — reviewer "sample shop" pin mode (backend, security)
- New pin mode `sample` beside `sandbox` / `masked`: a pin listed in `REVIEWER_SAMPLE_SHOP_IDS`
  **and** holding no TikTok/Shopee credentials and no `production_write_shops` row → mask off
  (names are synthetic), writes off, Duyệt/Thực thi simulated exactly as for `masked`. Any check
  failing → `masked` (fail closed).
- `GET /reviewer` exposes the mode; the banner says "Dữ liệu mẫu"; no visible word "demo".

## Later (wait for Session 1)
- S2-C Tự tạo offers only finished strategies (Combo first) — after `p100-c-combo` lands
  (it edits `panels-offers.tsx`).
- S2-D pre-generated titles (≤ 1 live regenerate / product) and banners from the shop
  profile — after Session 1 E.7.
- S2-E prod load: the owner runs the loader against prod after S2-A/B deploy; then pin it.

## Defaults taken (owner may override)
- 30 days (owner, 2026-11-11), no missing days (a clean shop; the missing-day path is shown on
  ORY, not here).
- Reviewer reaches the shop through the existing reviewer login, as an extra pin.

## S2-A result — synthetic shop generator + loader (2026-11-11)

Code: `scripts/sample_shop/` (`catalog.py` products and id range, `generator.py` pure/deterministic,
`loader.py` CLI). Owner change applied: **30 days** ending at `--end-date`, every day present.

**Reserved id range.** `shopee_shop_id` 990000000000..990000000999 (12 digits; real Shopee ids
have at most 10), default `990000000001` (`catalog.SAMPLE_SHOPEE_SHOP_ID*`). The loader writes only
a shop in this range, platform shopee, with no TikTok credential / ingest token /
`production_write_shops` row. Fujiwa `2b1da87b-…` and sandbox `1862f13b-…` are refused by id. A
remote database host needs `--allow-remote-database`. Shop name "Dữ liệu mẫu"; `service` consent.

**Datasets generated (Connector-shaped `IngestBody`, source `extension`, VND, rates as fractions):**
`item_catalog`, `item_snapshot` (2 captures), `order_lines` + `order_income` (income for orders
older than 4 days), `shop_overview` / `shop_traffic` / `traffic_overview` (confirmed; plus the ads
row, placed), `item_traffic_sources` (per product x stream x Thẻ-sản-phẩm child, confirmed),
`ads_campaign_daily` (2 campaigns, placed) + `ads_campaign_period`, `promotion_daily` and
`promotions` (one running Combo Khuyến Mãi, 2 tiers: buy 2 -5 %, buy 3 -10 %, the tiers in `extra`
numbers because the gateway stores none). Giá vốn per variation through `shop_inputs.write_versions`
(`sku_cost`, scope `item:model`; a "Combo 3" variation carries the single item's cost, the engine
multiplies by the pack count in the name).

**Run.**
```
python -m scripts.sample_shop --end-date 2026-11-10 --dry-run --out /tmp/sample   # JSONL only
python -m scripts.sample_shop --end-date 2026-11-10 --database-url postgresql://…@127.0.0.1/db
```
`--end-date` must not be after today (GMT+7). Re-running finds the shop by its reserved id and
re-posts identical bodies (all `duplicate`), so it is idempotent. The loader skips the gateway's
per-post materialize hook and runs `backfill_shop` once at the end (same rows, 13x less work).

**No earlier period.** The sample shop has only 30 days, so "30 ngày trước" is empty. Backend: the
overview/matrix payloads carry `warnings: [previous_period_thin]` ("Kỳ trước chưa đủ dữ liệu đơn
hàng để so sánh: các mức tăng / giảm so với kỳ trước được ẩn."), every `kpi_strip.*.previous` and
`change_pct` is `null`. Nothing errors. The product page's 7-day compare still works (the prior 7
days are inside the 30). Whether the web shows no arrow or a dash is a front-end behaviour not
checked here.

### S2-A follow-up: Quyết định cards (2026-11-11)
`scripts/sample_shop/decisions.py`, run by the loader after the backfill, only while the shop has
no proposal (idempotent). Every step uses the app's services with the time it would have happened
(`manual.create_manual`, `service.decide`, `mark_executed`, `change_sets.set_window`,
`verification.verify_shop`, `measure.read_change_sets`, `generate_cards`, `publish`); no number is
written. State after a load on `--end-date` e:
- **Đo lường, finished**: a Voucher (8k, đơn từ 150k, product 1) built e-16, started e-15; its 7-day
  window closed e-8. The generator counts the voucher's use from the simulated orders
  (`shop_voucher_share`, top-up of baskets), posts `voucher_settings` + a `promotions` Voucher row
  with `usage_rate`/`voucher_cost`; `impact_final` (ratio DiD on the product's daily AOV) is read from
  the rows. Window is e-15..e-8, not e-22..e-9: the reading needs 14 days before the change and the
  history has 30. Confidence is "thấp" (`no_controls`: too few comparable products).
- **Đo lường, counting down**: a Tiêu đề (product 4, fixed string `catalog.NEW_TITLE`) applied e-5,
  verified from `item_catalog`, 7-day window open. Old/new title are also in two
  `platform_item_snapshots` rows (the gateway's `item_snapshot` has no title column).
- **Đang thực hiện**: the engine's Ảnh bìa card on product 6, approved, not done yet.
- **Đề xuất**: engine cards as of e: Tiêu đề (product 2, keyword seed "khăn lau bếp"), Ảnh bìa
  (product 5), Voucher (product 3, positive only because the past voucher gives a usage rate), plus
  other kinds S2-C filters out.
Front-end gaps for S2-C: `tabOfCard` puts a *verified executed* card in Đo lường and maps status
`measured` (window closed) to `null`, so the finished voucher is in no tab until `measured` maps to
`do-luong`; the running title is the one in Đo lường today. Đang thực hiện shows only approved or
unverified-executed cards, so the "applied title" cannot sit there once its change is read back.

## Owner decisions 2026-11-11 (after the contract)
- **Reviewer pins = sample shop (default) + TikTok sandbox. Fujiwa is dropped** from
  `REVIEWER_SHOP_IDS` (prod env change, no code). No client data reaches the ISV reviewer,
  masked or not.
- **Only the tabs that work**: in sample mode the Shopee rail shows Tổng quan · Phân tích · Sản phẩm
  · Quyết định; Từ khóa, Quảng cáo, Đơn hàng, Luồng are hidden (not greyed out, no "sắp có"). In
  Tự tạo: **Tiêu đề · Ảnh bìa · Voucher** only (owner, later 2026-11-11: Combo removed); KOL,
  Quảng cáo, Combo nhiều SKU, Combo Khuyến Mãi hidden. Cài đặt menu: Đổi shop · Đăng xuất. Thực hiện =
  checklist. Design: https://claude.ai/artifact/HKYu5uqPX4egtX2cHB6bgK (6 boards).
- New slice **S2-C nav gating** (`lib/app-navigation.ts` sample-mode list + the Tự tạo strategy
  allowlist), after `p100-c-combo` lands (it edits `panels-offers.tsx`).
- **Đề xuất shows the same three kinds only** (Tiêu đề, Ảnh bìa, Voucher); every other generated
  card kind is filtered out in sample mode (part of S2-C). Đang thực hiện and Đo lường must not be
  empty: S2-A follow-up seeds one running Tiêu đề card (day 5/7) and one measured Voucher card
  (actual vs expected) in the same synthetic 30 days.

## Status 2026-11-11 (end of day)
- S2-A `e42ddfbf` on `fasttrack/p100-s2-data`: generator + loader; 24 unit pass, 2 Postgres skipped
  (sandbox) → owner ran both on local Postgres 16: 2/2 pass.
- S2-B `e2a5a189` on `fasttrack/p100-s2-reviewer`: `sample` pin mode; owner ran `-k reviewer` on local Postgres: 282 pass, 0 skip.
- New slice **S2-F reviewer Shopee routes**: every `/v1/demo/shopee/*` route is 403 `read_only` for a
  reviewer today. Needs a reviewed sample-only allowlist (some GETs write, e.g. keywords) and a
  simulated Shopee Duyệt (`POST …/recommendations/{id}/approve`) — touches `shopee-decisions/**`,
  so after Session 1. Also: `lib/reviewer/guide-copy.ts` (still "shop thật, ẩn tên", "Shop TikTok"),
  `dictionary.md` reviewer keys.

## Owner decisions 2026-11-11 (late)
- **Option A: the sample shop accepts Juli's own writes** from a sample-mode reviewer (Chọn, Kế
  hoạch, what-if, Duyệt, Bỏ qua, Đã làm …) — Juli's database only, never anything outbound to Shopee
  (no fill jobs, no Connector work, no platform API). "Đặt lại dữ liệu mẫu" restores the seeded
  state. LLM drafts stay refused until S2-D. Slice **S2-G**.
- **Reviewer guide back to English** (P77 stands); the app stays Vietnamese.

## S2-G result (2026-11-11)
- Option A built: sample-pin route table with reasons (`api/reviewer.py` `SAMPLE_SHOP_ROUTES`,
  24 reads / 23 writes, `SAMPLE_SHOP_REFUSED` 14 reviewed refusals), real Duyệt, fill queue off in
  any reviewer request, `reviewer_sample_write` audit. Details: `p32-reviewer-access.md`
  amendment S2-G.
- Reviewer guide back to English (`lib/reviewer/guide-copy.ts`, dictionary `reviewer.guide_sample`);
  banner "Tài khoản đối tác · Dữ liệu mẫu · lưu trong Juli, không gửi tới Shopee", shop menu
  "Shop Shopee Dữ liệu mẫu".
- Catalogue + decision seeding moved to `backend/src/juli_backend/services/sample_shop/`
  (`scripts/sample_shop/catalog.py` re-exports, `decisions.py` is the loader's session wrapper).
- **Reset blocked on a migration** (juli_app has no DELETE on the decision tables). Options for the
  owner: (a) a migration granting `juli_app` DELETE + `_delete` policies on the ~14 decision tables,
  or narrower (b) a SECURITY DEFINER function `sample_shop_reset_decisions(shop_id)` that refuses any
  shop outside the reserved `shopee_shop_id` range; then the route `POST /v1/reviewer/sample-shop/reset`
  (sample pin only, 1/min per pin, audited) calls it and `seed.seed_all`.

## Reset: owner decision (c), 2026-11-11
- No migration, no route, no banner button: `juli_app` keeps no DELETE (append-only tables stay so).
- Operator command on the owner connection: `python -m scripts.sample_shop --reset --database-url
  "$DATABASE_DIRECT_URL" --allow-remote-database` previews (per-table counts, rolled back); add
  `--yes` to delete and re-seed (`scripts/sample_shop/reset.py`, then the normal load).
- Tables come from the live catalogue (every `shop_id` table + `shop_id`-less FK children), FK-safe
  order, one transaction, only the one shop; refused unless `check_target` passes (reserved range,
  no credential, never Fujiwa/sandbox). Kept: `shops` row (id stays in `REVIEWER_SHOP_IDS`),
  consent, membership + invites, `ops_audit_log`, settings, pseudonym keys, subscription, LLM log.
- Run before each Shopee review. Tests: `tests/unit/test_sample_shop_reset.py` (plan + ORM schema),
  `tests/integration/test_sample_shop_reset_postgres.py` (wipe → reload restores the cards).

## E.7 card specs: proposed shapes (Session 2 → Session 1, 2026-11-12)

Session 1 asked Session 2 to propose these shapes; S1 builds E.7 on them unchanged, and S2-D (the
sample shop) fills them. Sources: briefs B.20, B.22, B.23 and D; banner kinds and fields come from the
design canvas `catalog()` (https://claude.ai/artifact/4SuySBPc5VbTQFU1SMK1wx), which stays the
authority for the kind list.

### Where they live: one additive table (migration `127_card_content_specs`, the next head after 126)
Why not a JSON key on an existing row: `juli_app` may UPDATE only `shop_proposals.status` (column
grant, migration 109); the card's `proposed` payload is frozen in append-only `card_events`; and a new
`card_events.event_type` would need the CHECK changed, which is a migration too. So it is one table,
**append-only** (the same discipline as card events), with no UPDATE or DELETE grant:

```
card_content_specs
  id            uuid pk
  shop_id       uuid fk shops      -- RLS: shop_isolation like every shop table; juli_app SELECT, INSERT
  spec_type     varchar(16)        -- CHECK IN ('title', 'banner', 'style_profile')
  proposal_id   uuid fk shop_proposals NULL   -- the card (NULL for style_profile)
  item_id       varchar(64) NULL              -- the product (NULL for style_profile)
  schema_version smallint          -- the JSON shape below, starting at 1
  inputs_hash   char(64)           -- sha256 of the canonical JSON inputs: a cache hit is provable
  spec          jsonb              -- the shape for spec_type, below
  source        varchar(16)        -- CHECK IN ('llm', 'seller', 'seeded')  ('seeded' = sample shop)
  llm_call_id   uuid NULL          -- the llm_call_log row, when source = 'llm'
  created_by_user_id uuid NULL
  created_at    timestamptz
  index (shop_id, spec_type, item_id, created_at desc)      -- title quota per product
  index (shop_id, spec_type, proposal_id, created_at desc)  -- latest per card; style_profile: proposal_id NULL
```
- **Latest wins**: the newest row for (card, type) is the current title or banner spec; for the style
  profile it is the newest row for (shop, type). History stays for audit and learning.
- **"Tạo lại" limit**: count the `source='llm'` title rows per (shop, item_id) in the GMT+7 day:
  ≤ 3 on the real app. The first generation counts toward the 3; `seeded` and `seller` rows never count. The sample shop allows ≤ 1 live row in total per product, on top of the
  `seeded` rows.
- A seller edit is a new row with `source='seller'` (the same inputs_hash, a new `spec`), so
  regenerating never overwrites an edit silently.
- Fallback with **no migration**, if S1 prefers it: the style profile becomes a `shop_rules` key
  `style_profile` (JSON, versioned by `shop_rule_versions`); titles and banners then have no
  per-card home and live in the client until E.7. I don't recommend it.

### spec_type = 'title' (B.20, B.22), schema_version 1
```json
{
  "inputs": {"current_title": "…", "keywords": [{"keyword": "…", "role": "chinh|phu",
             "searches": 1234}], "banned_terms": ["…"], "max_chars": 100},
  "candidates": [{"title": "…", "chars": 87, "keywords_placed": ["…"], "keywords_late": [],
                  "note": "…"}],
  "chosen": null,
  "model": "gpt-5.4-nano"
}
```
- There are exactly 3 candidates from one gated call (`gated_client`). `inputs_hash` = sha256 of
  canonical `inputs`, which is the value wave 1 G logs as `titles_hash` in `ops_audit_log.after`.
- `chosen` is the index the seller picked, or null. Choosing writes a `source='seller'` row.
- Every candidate is ≤ `max_chars` and is checked against `banned_terms` before it is stored; a
  candidate that fails is dropped, never cut.

### spec_type = 'banner' (B.20, D), schema_version 1
```json
{
  "template": "toi_gian|noi_bat|khung_vien",
  "day_mode": "ngay_thuong|mega_sale",
  "size_px": 1200,
  "banners": [{
    "shape": "ngang|goc|the",
    "kind": "mega|pct|genuine|freeship|combo|voucher|gift|addon|unit|quy_cach|…",
    "values": {"<field>": 149000},          // typed raw: money = integer đ, % = number, text = text
    "sources": {"<field>": {"card_id": "uuid|null", "field": "change_after.inputs.value"}},
    "position": "top|top_left|top_right|middle_right|bottom_right",
    "colour": "#RRGGBB",
    "size": "S|M|L"
  }],
  "checks": [{"code": "overlap|overload|text_long|empty_value|covers_product",
              "banner": 0, "fix": "…"}],
  "check_call_id": null
}
```
- Positions by shape: `ngang` → `top`; `goc` → `top_left`, `top_right`; `the` → `middle_right`,
  `bottom_right`. `bottom_left` is never allowed.
- Counts: `ngay_thuong` ≤ 3 banners; `mega_sale` ≤ 4 plus the top strip (a `ngang` `mega`).
- `values` are typed raw values, never pre-formatted text such as "149K". The display text is derived
  at render time, so a format change never rewrites a stored spec.
- `values` come only from card or listing fields named in `sources`. A missing value stays
  `null` and shows as an empty field, never an invented claim.
- `colour` must be in the shop's `style_profile.palette`.
- Two banners on one position is a `checks` warning, not a refusal.
- `checks` are filled by the one vision call on the final image (step 4 Kiểm tra) and re-run after
  edits; before that they are the rule-based checks.
- Kinds `gift` and `addon` cite the card "Mua Để Nhận Quà" or "Mua Kèm Deal Sốc" once w2-offers
  lands; the engine families stay `gift` / `add_on`.

### spec_type = 'style_profile' (B.23), schema_version 1 (proposal_id and item_id NULL)
```json
{
  "palette": ["#RRGGBB", "#RRGGBB", "#RRGGBB"],
  "primary": "#RRGGBB", "accent": "#RRGGBB",
  "type_feel": "geometric|rounded|serif|handwritten|condensed",
  "radius": "none|small|large|pill",
  "text_density": "low|medium|high",
  "positions_used": ["top_left", "bottom_right"],
  "covers_seen": [{"item_id": "…", "image_id": "…", "image_sha256": "…"}]
}
```
- `palette` holds 3 to 5 colours. The profile comes from one vision call over ≤ 12 covers at
  connect.
- `inputs_hash` = sha256 of the sorted `covers_seen` image ids or bytes, never the URL: a CDN URL can
  change for the same image. A changed cover changes the hash; the profile can be re-run on demand.

### S2-D (sample shop) on these shapes
- The loader and `--reset` write `source='seeded'` rows:
  - one `style_profile` (a fixed palette for "Hiên Nhà");
  - a `title` spec with 3 fixed candidates for each of the 6 products;
  - a `banner` spec on the open voucher card and the cover cards.
  No LLM call at load.
- A sample-pin reviewer may make ≤ 1 live title regenerate per product. It is refused after that
  (`sample_llm_quota`), and the reset brings the quota back.
- **Accepted by S1 on 2026-11-12, with 4 amendments (folded in above): the second index, typed
  `values`, explicit quota counting, image-id hash.** Migration `127_card_content_specs` is Session 2's,
  on a branch from `fasttrack/optimize-product`. S1 builds E.7 on it unchanged; S1 wave 2 has no
  migration, and if that changes S1 takes 128.

## S2-D result (2026-11-12), on migration 127
- Seeded rows (`backend/src/juli_backend/services/sample_shop/content_specs.py`), written by the
  loader and `seed.seed_all` after the cards (`seed.seed_content`; on a re-load of a shop loaded
  before S2-D too), all `source='seeded'`, no LLM call, a no-op once present:
  - one `style_profile`: palette `#2F6B4F` / `#F4EFE6` / `#E07A3F`, rounded, large radius, low text
    density; `covers_seen` = the catalogue's cover ids (`image_sha256` null: the sample covers have
    no bytes); `inputs_hash` = sha256 of the sorted image ids;
  - one `title` spec per product, 3 fixed candidates (facts only; the two keyword products carry
    their "Chính" keyword). A test holds every one to `drafts.screen_titles` against the loaded
    product's facts;
  - one `banner` spec per open (sent / approved) voucher or cover card: a `goc` `voucher` banner
    (top right, accent) with `value` / `min_spend` read from the card (`sources` =
    `change.after.<field>`), and a `the` `quy_cach` banner (bottom right, primary) when the listing
    states a size (`item.name` or `item.variations.name`); no size, no banner. `checks` empty
    (rule-based; the vision check is E.7's).
- Title route on the sample pin: seeded first, `regenerate` = the one live draft per product, then
  `sample_llm_quota` (details: `p32-reviewer-access.md` amendment S2-D). The UI shows "Viết lại
  bằng AI (còn 1 lần)" under seeded titles only (`panels-listing.tsx`); other shops never send
  `regenerate` and are unchanged.
- `llm_call_id` stays null on the live row: the builder's gated client does not expose the
  `llm_call_log` id yet (E.7 can add it). Banners have no reader until E.7's UI.

## S2-D2 result (2026-11-13): fixes from the prod check, and more strategies
Found on prod after S2-D's deploy (reviewer session in Chrome, 2026-11-13):
- The live title draft answered 503 "LLM tắt": the sample shop held `service` consent only. The
  loader now grants `service` and `llm_processing` (`loader.SAMPLE_CONSENT_SCOPES`), and adds any
  missing scope to an existing shop on re-load.
- Four of the six products had no "Chính" keyword, so Tự tạo › Tiêu đề could not be used on them
  (the draft button needs a ticked keyword). `catalog.KEYWORDS` now holds one per product (their
  current titles already carry it, so no new Tiêu đề card), every seeded candidate carries its
  product's keyword, and a re-load adds the missing keywords.
- `/` showed the TikTok Trang chủ on the sample shop; `sampleShopRedirect` sends it to Tổng quan.

Owner decision 2026-11-13 (option B): the real shop is the working standard; inside its four
screens the sample shop copies the seller app instead of offering a hand-picked list. Built on
`fasttrack/optimize-product` 9aeacca0 (S1's PR #2284: B.15 edits of running Dịch vụ hiển thị
campaigns). Tự tạo shows every kind and tool tab, the lists show every card, Duyệt takes any kind;
only the safety layer stays sample-specific. Details in `p32-reviewer-access.md`, amendment S2-D2.
A test evaluates and saves Combo, Deal Sốc (Mua kèm, quà tặng), a new and an edited Dịch vụ hiển
thị campaign and Affiliate on the loaded sample shop.

After deploy: run `--reset --yes` once. The re-seed rewrites the title specs with the new
candidates, which a plain re-load does not do.
