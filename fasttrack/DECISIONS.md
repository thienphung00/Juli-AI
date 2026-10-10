# Decisions

From the grilling session of 2026-10-05 (owner + Claude). New decisions get the
next number. Mark owner-unconfirmed ones as PROPOSED.

## G1 — the fast track itself

- **D1** — The fast track is a long-running branch (`fasttrack/optimize-product`)
  in `thienphung00/Juli-AI`, not a separate repo.
- **D2** — `main` is frozen while the fast track runs. Production deploys from
  this branch through a manual workflow. The branch merges back into `main` once,
  at the end. One migration chain, one production target.
- **D3** — Freeze point: #2079 merged; #2077 parked (cherry-pick if needed);
  Dependabot paused and its open PRs closed; branch cut from that `main` commit
  (`0332c405`).

## G2 — gates

- **D4** — Direct work: no PRDs, issues, slices, Executor/Review artifacts,
  validators or ADRs on this branch. The `fasttrack/` folder holds spec, ACs,
  progress, decisions, log and debt. `.claude` edit hooks and the executor-cache
  pre-commit gate are off on this branch.
- **D8** — Pre-deploy check (`fasttrack/check.sh`, run by the manual deploy):
  1. **Database backup. If it fails or can't be verified, the deploy stops
     before any migration runs.**
  2. Migration check: `alembic upgrade head` on a throwaway Postgres.
  3. Shop-isolation (RLS / two-tenant) tests.
  4. gitleaks.
  5. ruff + pytest on files touched since the last deploy.
  Everything else in `pr.yml` / `release.yml` is cut for this branch.

## G4 — the workflow

- **D6** — On Fujiwa, the model's score and recommendation are visible before
  approval. Approval stays manual.
- **D7** — A shop connecting triggers data collection automatically. Every
  connected shop is polled on a schedule. Manual refresh is no longer how data
  arrives.
- **D9** — Poll speed-ups:
  1. Split cadence by data type: orders/returns/inventory/products incremental
     every 15 min (webhooks are primary); analytics once a day when TikTok's
     `latest_available_date` advances.
  2. Backfill analytics by date range (one product-detail call returns daily
     intervals over a range).
  3. Run per-product / per-SKU detail calls in parallel up to the rate limit.
  4. One task per shop per cycle.
- **D10** — Two-phase backfill on connect:
  - **Fast phase** (high priority, right after connect): 30 days of analytics +
    recent orders/products/returns/inventory. Only job: the first
    recommendation.
  - **History phase** (low priority, queued after): as far back as TikTok
    allows, chunked, rate-limited. Training only. Never blocks the first card.
- **D11** — Scoring runs once when the fast backfill finishes, then once a day
  after the analytics pass, plus a webhook re-check that only suspends or
  withdraws affected cards (no re-score).
- **D12** — Optimize Product pipeline:
  1. Score the whole catalog. 2. Rank → top-K products become cards.
  3. Per-category scores per product (SEO, traffic, conversion, trust,
  economics, operations). 4. Recommend specific changes for the weakest
  changeable categories. 5. Execute on seller approval. 6. Measure at day 7 and
  day 14 against the expected outcome; feed back into the model; new
  recommendations at day 7 and day 14.
- **D13** — v1 execution on the real shop:
  - Executed: `update_product_listing` (title, description, attributes).
  - Images: analysed and recommended; uploaded only when the seller supplies a
    photo (`upload_product_image`).
  - Price: recommendation only. `update_product_price` is switched off.
  - Trust / operations: scores where data exists, "no data" otherwise, never
    actions.
  - Add competitor price (third-party data) and seller-entered product cost
    (gross margin).
- **D14** — Day 7 is a check-in: clearly worse than expected → recommend a
  revert (executable immediately); otherwise show the next recommendation, but
  it executes only after day 14. Day 14 is final and feeds the model.

## G3 — the model

- **D5** — Target: P(order | product, day) (orders per product per day), ranked
  by value. Query- and customer-level inputs are out until such data exists.
- **D15** — Priority = the largest expected **gross-profit gain** from a
  changeable category over 14 days. The same computation yields the category
  to fix and the expected outcome that day 7 / day 14 are measured against.
- **D16** — Two linked models:
  - **Market model** (FastMoss data, VN): sales speed vs price, rating,
    listing age, creators, competitor context.
  - **Shop model** (our TikTok API): LightGBM, orders per product-day, using
    traffic/CTR/CVR/stock + market-model outputs.
  - Expected gain per category = re-predict with the category's features set to
    the shop's 75th percentile; × unit gross profit × 14 days.
  - Calibration: per-category realised ÷ predicted ratio, starting at 0.5,
    updated by day-14 readings.
- **D17** — Quality bar: on a held-out last 14 days the model must beat the
  "previous 14 days" baseline on per-product orders error, and its top-20 list
  must hold up. Then live on Fujiwa, cards labelled "model v1, uncalibrated"
  until 10 measured changes exist.
- **D18** — No cost entered → rank by revenue gain. Cards carry a one-field
  cost input; CSV upload for the catalog. Price recommendations only for
  products with a cost.
- **D19** — Competitor matching is automatic: FastMoss search (region=VN, l3
  category, title keywords, ±50% price) → text + image similarity → LLM judge
  (top 30) → keep 10–30. Low-confidence matches dropped. Seller can mark "not
  comparable"; corrections train the judge.

## Defaults taken (owner may overrule)

- Optimize Product shows a top-10 ranked list with up to 5 active cards (raises
  today's one-card limit).
- Model retrains weekly and when new day-14 readings arrive.
- Third-party data source: FastMoss REST API (`/product/v1/search`,
  `/product/v1/salesTrend`, `/product/v1/reviewList`; optional
  `/rank/topSelling`, `/rank/newListed`). MCP/CLI not used for the pipeline.
- No in-house scraping of TikTok Shop (risk to Juli's TikTok Partner app).

## Later decisions

- **D20** — Production deploys from the fast track are triggered by pushing a
  `fasttrack-deploy-*` tag on a commit already on `fasttrack/optimize-product`
  (2026-10-05). `workflow_dispatch` stays for use after the merge into `main`.

- **D21** — The demo becomes the product (owner, 2026-10-08). demo.app-juli.com is
  replaced by the fast-track app; it had no real data worth keeping.
  - **Quyết định** (tab label restored; overrides #1910's "Hành động") shows the
    shop's Optimize Product cards from the ADR-106 pipeline on real P1 data
    (rule-based stage diagnosis) until the P3 model replaces the ranking.
  - **Phân tích** shows the ADR-108 shop diagnosis report for the signed-in shop,
    refreshed once a day; the report JSON (`shop_diagnosis` `report.json` shape)
    is the API contract.
  - UI follows `docs/product/design/ui_kits/app/index.html` + `colors_and_type.css`.
  - The fast-track deploy builds and ships the demo lane itself (repays the
    demo/landing block in DEBT).

- **D22** — Optimize Product recommends in three tiers; FastMoss is not a
  prerequisite for the model (owner, 2026-10-08). Amends D15–D17 and P2/P3.
  1. **Diagnosis** — ADR-106 funnel-stage diagnosis per product (impressions →
     clicks → add-to-cart → orders) against the shop's peers and the prior 30
     days; the weak stage picks the lever. TikTok API data only.
  2. **Ranking** — priority = recoverable GMV per day, built from TikTok's own
     decomposition GMV = Lượt hiển thị sản phẩm × CTR × CTOR × AOV (SKU)
     (TikTok Academy VN, "Lưu lượng truy cập sản phẩm": CTR = lượt nhấp ÷
     lượt hiển thị; CTOR = đơn hàng SKU ÷ lượt nhấp; AOV (SKU) = GMV ÷ đơn
     hàng SKU):
     - CTR stage: impressions × (reference CTR − current CTR) × the product's
       CTOR × AOV (SKU) — extra clicks only become GMV through CTOR.
     - CTOR stage: clicks × (reference CTOR − current CTOR) × AOV (SKU).
     Reference = peer median, else the product's own prior 30 days; daily
     averages over the last 30 days. Cards say it is a rule-based estimate
     until the model replaces it. (Amended 2026-10-08, owner: the first text
     omitted CTOR at the CTR stage.)
  3. **Learning** — every executed change is measured at day 7 / day 14
     (ADR-077/106). Per-lever calibration (realised ÷ expected, starting at 0.5)
     updates from day-14 readings; a learned uplift model only once enough
     measured changes exist.
  - **Model v1 (P3)** is the shop model only (LightGBM, orders per
    product-day, TikTok features), used for ranking — not for counterfactual
    "set category to P75" gains, which observational data cannot support.
  - **FastMoss (P2)** becomes optional: competitor price (D13, D19) and
    market/category context as a control. The market model (D16) waits for
    multiple shops and cleaned FastMoss data.

- **D23** — UI follows the sales demo video; decisions recorded in
  [ADR-109](../docs/adr/109-demo-app-follows-the-sales-demo-video.md) at the
  owner's request (an exception to D4's no-ADR rule) (owner, 2026-10-08).
  Grill in progress; open points listed in the ADR.

- **D24** — Recommendation pipeline for all four streams (owner grill,
  2026-10-10). Principle: rules decide *what* and *how much*; the LLM only
  writes content; the LLM never produces a number.
  1. **No OpenAI call before the seller's first approval.** Producing and
     ranking cards (nightly) is rules and arithmetic only; a card's text is a
     template. The model is called only once the seller approves a card
     (Phê duyệt), so unapproved proposals cost nothing.
  2. **Rules choose the action** from the lever map (canvas "Đòn bẩy",
     4 streams × metric) after the gates: enough data, TikTok eligibility,
     the seller's rules, cooldown, no overlapping change in measurement.
     Seller-facing term: **"Hành động"** (replaces "Đòn bẩy"/lever in UI copy).
  3. **Card copy stays templated** (reason, expected GMV); LLM only in runs.
  4. **Video and LIVE get "Juli soạn · bạn làm" cards**: video hook/script for
     a product whose video CTR fell; LIVE host script / basket order for LIVE
     CTOR. The seller films or goes live; Juli measures on the next
     videos/sessions.
  5. **Promotions stay seller-executed** (Seller Center, Juli verifies). Juli
     proposes a discount only within the seller's margin rule (cost price or
     minimum margin in Quy tắc) and against competitor prices (FastMoss, with
     industry/market data); the promotion-create API is enabled only later.
  6. **Learning now**: expected GMV × the lever's calibration coefficient
     (currently written but unused); Từ chối / Hoàn tác reasons lower that
     action's priority for the shop.
  7. **Models**: `gpt-5.4-nano` for the tool loop; a stronger OpenAI model for
     writing content (title, description, scripts), chosen by eval before it
     is switched on. Estimate ≈ $0.02 per workflow, ≈ 1 workflow/shop/day at
     most (≤ 5 product cards + ~3 content cards per week) → ≈ $0.6/shop/month;
     to be replaced by measured `workflow_runs` cost.
  8. **Customer vocabulary**: now a per-category vocabulary bank in the prompt
     (TikTok SEO words, the shop's best-selling listings, buyer reviews with
     buyer data removed, FastMoss). SFT later, per category, objective in this
     order: *effective* (day-14 Đạt / Gần đạt) and *accepted* (seller kept or
     edited it) — training examples must be both; seller-edited final text is
     the target.
  9. **Campaigns**: Juli also proposes TikTok platform campaigns (Chiến dịch
     sàn: which products to register, at what discount within margin) and the
     seller's own campaigns; research of the API and rules in progress.
  10. **Campaign timing** (owner, 2026-10-10): a "Kế hoạch chiến dịch" card
      ~14 days before each mega sale day, ~7 days before double days and
      payday; Juli detects registration itself via `campaign_inventory`
      (stock locked for a campaign); seller promotions become one
      "Kế hoạch khuyến mãi" per product (one price layer — platform campaign >
      flash sale > product discount — plus cart layer and one voucher), checked
      against stacking rules and the margin floor.
  11. **GMV Max on sale days**: Juli suggests turning on "Ngày khuyến mãi"
      3–5 days before the event (Academy), ROI target ≥ break-even ROAS
      (1 ÷ margin), budget from TikTok's `/gmv_max/bid/recommend/`; the seller
      applies it. Juli writes ads settings only after the Business app is
      approved and with per-change consent. No manual ROI edits on the day
      (they forfeit ROI Protection). The agency's "0h–2h" practice is a
      hypothesis: measured per shop from hourly shop GMV and GMV Max hourly
      cost on the next sale day before Juli recommends it.
  12. **ROI of promotions and campaigns** = (incremental GMV × margin −
      seller-funded cost) ÷ seller-funded cost; platform-funded discounts are
      not a cost; incremental GMV vs normal days and sibling controls
      (ADR-077); needs cost price in Quy tắc.
  13. **Cost data**: ingest, read-only, `GET /order/202407/orders/{id}/price_detail`
      (seller vs platform deductions) and per-order finance transactions.
  14. **Agent research tools** (only in runs after approval, D24.1): curated,
      read-only — `search_juli_documentation` over vetted Academy excerpts,
      FastMoss market reads with a per-run credit cap, existing TikTok read
      tools. No open web search (injection, determinism; ADR-068 amended).
  15. **Market data**: a weekly non-LLM job caches FastMoss data (competitor
      prices, category best-sellers and videos, keywords); card selection and
      the agent read the cache.
  16. **Structured output**: every LLM output that becomes seller-facing or
      a write (title, description, scripts, narration) uses OpenAI structured
      output (JSON schema), validated for length, banned terms, the seller's
      protected terms and facts before the consent step.
  17. **Card limits and return times** (owner, 2026-10-10; trial phase —
      the goal is continuous use):
      - One limit for every shop: at most **5 new cards/day, 25/week, 30 open**
        (replaces `max_active` 5 / weekly novelty 3). Campaign-plan cards are
        outside the limit. Nightly candidates: top 30 (was 10).
      - On connect: day 1 shows the top 5 mixed by type (~3 Juli tự làm,
        1 Seller Center, 1 video/LIVE); then +5/day while fewer than 30 are
        open.
      - A card is valid 7 days (a campaign plan until registration closes);
        open cards are re-scored daily with the new numbers.
      - Expired, rejected (Từ chối), declined (Không thực hiện) or reverted
        (Hoàn tác): the same action on the same product may return after
        **7 days**, every time — no escalation, no per-reason durations
        (reasons still lower its priority, D24.6).
      - Once surfaced, a card stays at least **3 days** (numbers still update
        daily); it is withdrawn earlier only when no longer valid (product
        edited outside Juli, out of stock, metric already at target), not for
        dropping in rank.
