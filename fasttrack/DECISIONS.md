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
  - *Implementation notes (P14, 2026-10-10; agent choices, owner may overrule):*
    - **17**: "day"/"week" are the shop's (UTC+7, weeks from Monday); a tie
      between limits is reported as `daily_cap`. Validity counts from the
      card's first surfacing (`surfaced_at`, no longer re-stamped each run);
      after 7 days the card's status becomes `expired`. After its 3-day stay a
      card that dropped out of the top 30 is withdrawn. The seller's own
      "Số thẻ mở cùng lúc" rule (1–5), when set, still lowers the 30. Rejected /
      declined / reverted keep P10-A's early return on a > 20 % data change.
    - **6, calibration**: ranking value = recoverable GMV/day × *factor* ×
      *penalty*. *factor* = coefficient ÷ 0.5, clamped to [0.25, 2] — the
      coefficient (realised ÷ expected, `lever_calibrations`) starts at 0.5
      for every lever, so an unmeasured lever is neutral (1) and a lever that
      delivered what was expected (→ 1.0) ranks up to 2×.
    - **6, reasons**: *penalty* = max(0.4, 1 − 0.2 × Σ max(0, 1 − age_days ÷ 60))
      over the shop's Từ chối / Không thực hiện / Hoàn tác reasons for that
      lever in the last 60 days (all products). One fresh reason → 0.8,
      fading to none at 60 days; floor 0.4. Circumstantial codes
      (`editing_myself`, `discontinued`, `other_campaign`, `changed_mind`) carry
      no penalty.
    - The shown "GMV dự kiến" and the day-14 measurement stay on the
      rule-based estimate (D22 label unchanged); the weights reorder cards
      only. The payload carries `adjusted_by_history` (and
      `diagnosis.history_adjustment`); the card says "Thứ tự đề xuất đã điều
      chỉnh theo kết quả trước của shop."

  18. **Content cards (Video / LIVE), P14** (owner, 2026-10-10; artboards
      ContentCards, ContentRun): same card frame + chip "Juli soạn · bạn làm";
      after Phê duyệt Juli reads data and drafts with `gpt-5.4-nano`
      (structured output); the seller picks Dùng kịch bản này / Soạn lại /
      Không thực hiện, then films or goes live; Juli detects the new video
      tagging the product or the next LIVE selling it. **No Hoàn tác** (Juli
      writes nothing to TikTok). Measurement: video CTR on new videos at day
      7 / 14; LIVE CTOR over the **next 3 sessions** selling the product.
  19. **Content analysis and voice** (owner, 2026-10-10): P14 reuses the
      juli-content-engine script frame (HOOK / SETUP / VALUE / CTA, `cut.json`
      ideas) as the JSON schema and its generic voice rules as prompt
      templates rewritten for the seller's product, on `gpt-5.4-nano`;
      analysis uses TikTok numbers only (CTR, views, tagged product, basket
      position). Analysing the content of existing videos/LIVEs is P15: first
      check whether Juli may fetch the seller's video files through TikTok
      APIs and run its own pipeline (ASR, cut detection, vision); if not,
      the seller uploads the video file to Juli. Scripts follow the seller's
      voice (tone and banned words in Quy tắc + the shop's own best-selling
      videos/LIVEs as examples), never Juli's founder voice; no Fujiwa data.
      *2B result (2026-10-10):* no compliant API gives the seller's video or
      LIVE replay file. Accounts API prohibits downloading media; Spark Ads /
      GMV Max `preview_url` exists but needs ads authorization and conflicts
      with that rule; no API returns transcripts or LIVE replays. → P15 uses
      **seller upload (2C)**, plus compliant signals: Accounts API
      `video_view_retention`, caption, thumbnail/share URL (after the Business
      app and the Accounts API form are approved) and Partner shop metrics.
  20. **P15 content analysis** (owner, 2026-10-10): the seller uploads the
      video or LIVE recording; ASR via OpenAI transcription for short videos
      and LIVE windows (faster-whisper on the VPS only at volume); scene cuts
      (PySceneDetect + content-engine `reference_analyze.py`), on-screen text
      (OCR), product-on-screen by matching product images to keyframes;
      `gpt-5.4-nano` scores hook / CTA from the derived signals (structured
      output) — the whole video is never sent to a model. LIVE: only windows
      around the product's pin/mention times. No Remotion video building for
      now. Uploaded files are deleted after analysis; only derived data kept.
      Cost estimate (to verify against OpenAI pricing): ≈ $0.006–0.009 per
      analysed minute; a 30–60 s video ≈ $0.005–0.01; a LIVE ≈ $0.2–0.3 with
      windows (≈ $0.7–1.1 for a whole 2 h session).

- **D25** — Internal console ("ops") for the Juli team (owner grill,
  2026-10-10). Includes P9-B (shop handover).
  1. **Where**: `ops.app-juli.com`, built from the demo app's code so staff see
     exactly what the seller sees; two gates — Cloudflare Access (Google,
     @app-juli.com only) and a staff role in the database.
  2. **Roles**: Xem (view only) · Vận hành (change a shop's settings, enter
     Quy tắc for the seller, approve cards for the seller when the seller has
     agreed) · Admin (staff and feature flags). Every action is audited (who,
     what, when).
  3. **"Xem như shop"**: read-only by default — the shop's Trang chủ, Phân
     tích, Quyết định with a banner "Đang xem như Shop X · chỉ xem", all
     writes blocked. Acting for the seller is enabled per shop, with the
     seller's recorded consent, every action audited.
  4. **Per-shop settings overriding defaults**: card limits, enabled actions
     and streams, content cards on/off, promotion API on/off, OpenAI model,
     **monthly OpenAI cost cap**, and the shop stage — **Thử nghiệm · Tự vận
     hành · Pilot đặc biệt**; "về mặc định"; all changes audited.
  5. **Overview**: totals (connected, active, disconnected/token expired) and a
     filterable list per shop — last poll, last diagnosis, cards open /
     approved / rejected, approval rate, failed runs, OpenAI cost this month,
     GMV 30 days.
  6. **Privacy**: staff never see buyer data (masked), only shop data; every
     "Xem như shop" session is logged; the privacy policy's staff-access
     sentence gains "to support and operate the service", accepted by the
     seller when connecting a shop.
  7. **Handover (P9-B)**: "Mời seller" sends an email invite; the seller signs
     in and takes ownership; the team keeps Vận hành access if the seller
     agrees; cards, runs, rules and history are kept.
  21. **P14 integration choices** (owner, 2026-10-10): (1) return after
      Từ chối / Không thực hiện / Hoàn tác is strictly 7 days — no early
      return on a > 20 % data change; (2) the seller rule "Số thẻ mở cùng lúc"
      becomes 5–30, default 30; (3) legacy-workflow cards follow the same
      7-day rule; (4) product and content cards are ranked **separately, with
      fixed daily slots** (3 Juli tự làm / ảnh · 1 Seller Center · 1 nội dung);
      a slot with no candidate stays empty; (5) new seller rules "Giọng văn"
      and "Từ không được dùng", read by content runs.
- **D25 additions** (owner, 2026-10-10):
  8. Over the monthly OpenAI cap: stop new drafting for that shop and alert
     the team; rule cards keep running; the cap is set per shop in Ops.
  9. Staff can open each run's detail (timeline, LLM output, tokens),
     read-only.
  10. **Ops tab "Mô phỏng"** (4 KPI × 4 streams), for both target-setting per
      shop and sales demos. Locked cells: Video CTOR, Video AOV, LIVE AOV;
      Hiển thị editable with an "indirect" warning. Baseline = the shop's last
      30 days, **plus a volatility view**: per stream and per product/content
      row, the normal high/low band of each KPI (daily spread), so the team
      can pick streams with stable impressions and small swings — the
      simulation must show whether a target is inside normal noise.
      Scenarios are saved per shop with a name and can be set as the shop's
      target. Internal only for now.
  12. **History for the 90-day window** (owner, 2026-10-10, option A): keep the
      60-day backfill at connect (fast first cards), then extend history in
      the background each night, slowly, up to 180 days (or the API's real
      maximum look-back, checked first; beyond that history accumulates
      naturally). The 90-day window unlocks when 2 × 90 days exist; until then
      it is greyed "Đang tải lịch sử · còn N ngày". Fix the video-windows 429
      handling in the same work: longer retry/back-off on 429 and skip the
      video tables for that cycle instead of falling back to whole-day reads.
  14. **Rules set by the team first** (owner, 2026-10-10): staff edit each
      shop's Quy tắc from Ops "Cài đặt shop" (audited); later the seller adjusts
      and optimises them in their own Quy tắc. Card approval stays seller-only.
  15. **Permission status**: token refresh also stores `granted_scopes`; Ops
      shows each shop's scope status; a missing scope shows the seller a
      "Kết nối lại TikTok Shop để cấp quyền mới" strip. (The 30-minute beat only
      checks; a token is refreshed only within 24 h of expiry, about weekly.)
- **D24.22** — Banned words and tone go into the drafting prompt and the draft
  is checked before the seller sees it (owner, 2026-10-10, option A).

- **D26** — Cards right after connecting: "quét nhanh" (owner, 2026-10-10).
  Runs in parallel with the 60-day backfill, on the priority queue, ~2–3 min
  after connect: the last **14 days** of product performance (1–2 calls for
  the whole shop) + TikTok listing diagnosis codes for the top 5–10 products
  → **1–3 cards of Tiêu đề / Mô tả / Ảnh bìa only** (Juli tự làm), labelled
  "Đề xuất nhanh · dựa trên 14 ngày", confidence "Tham khảo". They take the
  day-1 Juli slots (3/1/1); the full diagnosis (~10–20 min) fills the
  remaining slots and keeps quick cards that are still valid, updating their
  numbers. The client shows progress ("Juli đang đọc dữ liệu shop · bước
  1/3"), and cards appear as soon as they exist. Delivered in **P17** with
  D25.12 (history to 180 days, 429 fix) and faster cost reads for the first
  30 days (60 orders / 15 min, rate-limited).
