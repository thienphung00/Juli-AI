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
  21. **P14 integration choices** (owner, 2026-10-10): (1) return after
      Từ chối / Không thực hiện / Hoàn tác is strictly 7 days — no early
      return on a > 20 % data change; (2) the seller rule "Số thẻ mở cùng lúc"
      becomes 5–30, default 30; (3) legacy-workflow cards follow the same
      7-day rule; (4) product and content cards are ranked **separately, with
      fixed daily slots** (3 Juli tự làm / ảnh · 1 Seller Center · 1 nội dung);
      a slot with no candidate stays empty; (5) new seller rules "Giọng văn"
      and "Từ không được dùng", read by content runs.
  22. Banned words and tone go into the drafting prompt and the draft
      is checked before the seller sees it (owner, 2026-10-10, option A).

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
  11. **Mô phỏng window and trend:** a window selector 7 / 14 / 30 / 90 ngày drives the
      baseline (per-day average over N), the ▲/▼ chip on every cell (last N vs the N
      before; green up, red down, grey when |Δ| < 0.5 %) and the volatility bands (p10–p90
      within N). A window the history cannot cover is shown greyed "Chưa đủ dữ liệu (cần
      2 × N ngày)" — never invented. API takes `window` ∈ {7, 14, 30, 90}.
  12. **History for the 90-day window** (owner, 2026-10-10, option A): keep the
      60-day backfill at connect (fast first cards), then extend history in
      the background each night, slowly, up to 180 days (or the API's real
      maximum look-back, checked first; beyond that history accumulates
      naturally). The 90-day window unlocks when 2 × 90 days exist; until then
      it is greyed "Đang tải lịch sử · còn N ngày". Fix the video-windows 429
      handling in the same work: longer retry/back-off on 429 and skip the
      video tables for that cycle instead of falling back to whole-day reads.
  13. **"Huỷ kết nối"** per connected / token-expired shop in Tổng quan, Admin only:
      confirmation listing the effects, a required reason (audited) and the typed shop
      name; revoke Juli's stored authorization, stop polling and card generation, cancel
      pending runs, write nothing more to TikTok, keep history / rules / measurements so
      reconnecting resumes, e-mail the seller. TikTok has no revoke endpoint: stored
      tokens are destroyed and the credential marked `needs_reauth`.
  14. **Rules set by the team first** (owner, 2026-10-10): staff edit each
      shop's Quy tắc from Ops "Cài đặt shop" (audited); later the seller adjusts
      and optimises them in their own Quy tắc. Card approval stays seller-only.
      *P16 detail:* Vận hành / Admin edit every seller rule (incl. the P14
      keys, "Giọng văn", "Từ không được dùng", "Số thẻ mở cùng lúc" 5–30) through the
      existing rule store and validation, always as the team, every change audited; the
      seller later sees and keeps editing them. Approving cards stays the seller's.
  15. **Permission status**: token refresh also stores `granted_scopes`; Ops
      shows each shop's scope status; a missing scope shows the seller a
      "Kết nối lại TikTok Shop để cấp quyền mới" strip. (The 30-minute beat only
      checks; a token is refreshed only within 24 h of expiry, about weekly.)
      *P16 detail:* every token refresh persists the granted scopes when the
      response carries them; Ops shows per shop "đủ quyền / thiếu X / chưa rõ" for the
      scopes Juli uses; a missing scope shows the seller "Kết nối lại TikTok Shop để cấp
      quyền mới".
  - **D25.3 amended:** "Xem như shop" is ALWAYS read-only — staff see everything the
    seller's client shows (Trang chủ, Quyết định incl. run details, Phân tích, Juli, Quy
    tắc) and can never write through it. No act-for-seller mode, no team-may-act flag or
    consent field; the view-as API refuses every non-GET with 403. Staff change things
    only via Cài đặt shop (overrides, Quy tắc) and Admin-only Huỷ kết nối.
  - **D25.8 storage (coordination with P15):** the monthly OpenAI cap is the `shop_rules`
    row `openai_monthly_cap_usd` (default $5/month from `OPENAI_MONTHLY_CAP_USD_DEFAULT`),
    read by P15's content analysis and by P16's drafting / agent-run gates.

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

- **D27** — Juli Ops: speed, confirmations, audit log (owner, 2026-10-11).
  Artboards: canvas "Thiết kế UI flow", row "Juli Ops · xác nhận, nhật ký, tốc độ
  (D27)" — `OpsConfirm`, `OpsLog`, and the header of `OpsSimulate`.
  1. **Daily precompute, not live recompute (9A).** Ops Tổng quan and Mô phỏng read
     numbers computed once a day, right after the shop's daily analytics pass
     (new days landed). Pages show "Số liệu đến hết DD/MM · cập nhật lúc HH:MM" +
     **Làm mới**, which recomputes only the shop being viewed (Tổng quan: all rows).
  2. **Compact daily table for Mô phỏng (2A):** one row per shop × stream × day
     (impressions, clicks, orders, GMV), written when the diagnosis report is built;
     the simulation reads it instead of merging stored report JSON. Daily refresh only.
  3. **Commerce polling hourly (8B):** orders / inventory / returns / products / order
     costs every 60 min instead of 15 (analytics stays once a day).
  4. **Audit retention (4A):** configuration changes 365 days; view-as sessions and
     system jobs 90 days; a nightly job deletes expired rows; index on (shop_id, at).
  5. **Every change is confirmed (5B, 10A):** stage → a before→after dialog; checkboxes
     / toggles / selects (streams, actions, API khuyến mãi, model, OpenAI cap) are a
     draft with a bottom bar "N thay đổi chưa lưu · Bỏ thay đổi · Lưu thay đổi (N)",
     then one confirm dialog listing each before→after; one save = one audit row.
  6. **Audit merging (6A):** same actor + same shop + same field within 10 minutes →
     one row (first before → last after); if the final value equals the original, the
     row is deleted (nothing logged).
  7. **No reason field (7)** except Huỷ kết nối, where it stays required (already live).
  8. **Mô phỏng lives in one place:** the main nav (Tổng quan · Mô phỏng · Nhân viên ·
     Nhật ký). The page shows only the current shop's name + "Đổi shop ở Tổng quan ›";
     shops are chosen and searched in Tổng quan (search by shop name), and the last
     chosen shop is remembered. No shop chosen → "Chọn một shop ở Tổng quan ›". Removed:
     Mô phỏng in the shop nav and the per-row Mô phỏng link.

- **D28** — Juli Ops: number reliability, OpenAI limits, shop terms (owner, 2026-10-12).
  Artboards: canvas "Thiết kế UI flow", row "Juli Ops · độ tin cậy số liệu, giới hạn
  OpenAI, thời hạn shop (D28)" — `OpsSimBand`, `OpsOpenAICap` (tab Chi phí),
  `OpsShopTerm` (tab Thời hạn). Main nav: Tổng quan · Mô phỏng · Chi phí · Thời hạn ·
  Nhân viên · Nhật ký.
  1. **Band of the window mean (11A).** A Mô phỏng cell shows "Dao động TB N ngày: ±X %"
     = 1.2816 × stdev(daily values) / √(days present) / mean; the daily p10–p90 band
     ("Mỗi ngày: ±Y %") is shown on hover / click. "Đo được" compares a target to the
     window band, so it shrinks from 7 → 14 → 30 days.
  2. **Low-data cells (3C):** fewer than 30 clicks (CTR) or 30 orders (CTOR, AOV) in the
     window → the value stays but is grey with a "*" mark, a dashed cell, a grey "~"
     trend chip and "ít dữ liệu · N đơn"; a target on it reads "Ít dữ liệu".
  3. **System OpenAI limit (5A), tab Chi phí:** monthly system cap (default $50,
     Admin-editable with a confirm dialog). ≥ 80 %: banner on every Ops page + one email to
     Admins per month. ≥ 100 %: no new OpenAI calls for any shop (drafting, content
     analysis, agent runs); cards are still emitted; the seller sees "Juli tạm dừng soạn
     nội dung mới". Each shop's own cap (default $5) is editable per row ("· riêng").
  4. **Shop terms (6A), tab Thời hạn:** manual extension by package only — 30 or 365
     days — recorded as a *subscription period* (shop, plan, starts_on, ends_on, source
     `contract` | `payment`, reference = contract no. / payment id, unique per source,
     actor). A still-active shop's new period starts at its current end; an expired one
     starts today. Expiry = latest `ends_on`. States: còn hạn; sắp hết (≤ 14 days);
     ân hạn 7 days after expiry (Juli runs, seller sees an amber reminder to contact
     lienhe@app-juli.com); then **chỉ xem** (no new cards, no runs or drafting; data sync
     continues so the shop resumes at once). Admins see days left and may extend without
     limit. A shop with no period yet is "Chưa đặt thời hạn" and is NOT restricted.
  5. **Payment-ready:** the future payment system calls the same grant function with
     `source=payment` and its transaction id (idempotent on the reference); Ops needs no
     change.

- **D29** — How Juli diagnoses and sets KPIs for volatile metrics (owner, 2026-10-12).
  Context: Fujiwa's Thẻ sản phẩm moves ±26 % impressions and ±66 % CTOR per day, so a
  7–14-day gap against the shop median is mostly noise; the ranker ignored volatility.
  1. **Adaptive window (16.1A):** per product, the shortest of 14 → 30 → 60 days with
     ≥ 30 clicks (CTR) / ≥ 30 orders (CTOR, AOV); otherwise "ít dữ liệu", no diagnosis.
  2. **A problem starts at GMV (16.2):** a product is a candidate only when its GMV fell
     by more than its own volatility band versus its stable level; then GMV is split into
     Hiển thị × CTR × CTOR × AOV to find the metric that caused it. The same band is the
     basis of the KPI.
  3. **Reference (16.3A):** the higher of the shop median, the product's own earlier stable
     level, and a category benchmark when available.
  4. **Several levers, one metric (16.4A):** one card chain per (product, lever), but a
     product has ONE target metric at a time; several levers may run together only within
     that metric (e.g. CTR: Ảnh bìa A + Tiêu đề T), never CTR and CTOR at once, so results
     stay attributable.
  5. **Stable first (16.5A):** ranking prefers products with stable traffic (low CV); their
     KPIs are more precise.
  6. **Confidence on the card (16.6A):** "Độ tin cậy: Cao / Vừa / Thấp" from data volume and
     volatility.
  7. **KPI target (17.1A):** = the 16.3 reference, clamped to [current + 1 × window-mean
     band, current + 3 × band] (below 1 band it cannot be measured; above 3 it over-promises).
  8. **Success (17.2A):** the target metric's window mean moves by more than 1 band in the
     right direction AND the product's GMV does not fall by more than its band. Day 7:
     "Đang lên" / "Chưa rõ"; day 14: "Đạt" / "Một phần" / "Không đạt".
  9. **Guard metrics (17.3A):** the hold threshold of every non-target metric = its own
     window-mean band (replaces the fixed ±3 %); editable.
  10. **Volatile products (17.4A, CV > 30 %):** cards still allowed, KPI shown as a range
      (e.g. "CTR 3,2 % → 3,8–4,4 %"), confidence "Thấp", judged at day 14 only.
  11. **Who sets it (17.5A):** Juli proposes; the seller may edit within [min, max] when
      approving; **Juli Ops Admins may change every level per shop** (bands, KPI range
      multipliers, guard thresholds, data minimums) — Ops is where each shop is tuned
      before the seller uses demo.app-juli.com.

- **D30** — Baselines, external changes, Quality Score and Performance Prediction
  (owner, 2026-10-12). What Juli has today: daily per-product performance since
  2026-03-16 (reconstructable); price / title / description / images / promotions are
  current-state only (no history) except Juli's own writes (`run_write_values`).
  1. **Record history from now (18.1A):** (a) a daily product content + SKU price snapshot
     (only products whose TikTok `update_time` moved are re-read), with a content hash;
     (b) promotions persisted in tables (activities incl. expired/deactivated, with dates
     and per-SKU activity price), backfilled once from the Promotion API; (c) a full
     baseline frozen at approval and again at execution: 14-day metric pre-series, price,
     active promotions, Quality Score, TikTok listing codes, content hash.
  2. **Quality Score, layer 1 (18.2A):** 0–100 per product, rule-based, daily, no OpenAI:
     completeness (title length, description ≥ 200 chars with sections/images, ≥ 3
     sub-images, video, attributes), search fit (SEO words / Opportunities keywords in the
     title, category vs Recommend Category), TikTok listing diagnosis codes, and a rule
     list of risky claims. An OpenAI truthfulness check runs only when the seller approves
     a content card (D24 unchanged).
  3. **Performance Prediction, layer 2 (18.3A):** per (lever, Quality-Score gap) a prior
     lift from TikTok Academy guidance, calibrated by measured day-14 results — shop-level
     when the shop has enough results, otherwise fleet-level (shrinkage) — output as a
     range CTR/CTOR → GMV with confidence, feeding the D29 KPI.
  4. **External changes (18.4):** subscribe TikTok webhooks **15 Product information
     change** (`changed_fields`, `update_time`), **63 Activity change** (promotion
     CREATE / UPDATE / DEACTIVATE with the products and SKUs added or removed — richer than
     39 Activity status change, which stays as a fallback), **16 Product creation**
     (baseline from day one, new-product rules), plus 18 / 5 / 37 / 27 / 68 already
     available; 25 Opportunity matching waits for the Opportunities/keywords work; on an event Juli re-reads the product, diffs
     it against the snapshot and records an "external change". A daily `update_time`
     reconciliation catches missed webhooks and price changes (no price webhook). External
     changes appear on the product timeline; a measured card overlapping one reads "bị ảnh
     hưởng bởi thay đổi khác" instead of crediting Juli. Unknown webhook types are already
     acknowledged (200) and stored raw, so events from today can be replayed.
  5. **Internal only (18.5B, amended by owner 19):** Quality Score and Performance
     Prediction are internal algorithms that pick, rank and size cards (D29 KPI range and
     confidence); no Ops tab or monitoring screen. What surfaces is only their effect on
     the cards (ranking, "Độ tin cậy", KPI range) and, on a measured card, "bị ảnh hưởng
     bởi thay đổi khác" when an external change overlaps. Scores stay queryable in the
     database / logs for debugging.

- **D31** — Shopee data, the Juli Connector extension, and change strength
  (owner, 2026-10-12). Research: Open Platform corpus (455 APIs, push codes) in
  `~/shopee-corpus/open-platform/`, Seller Centre internal data calls in
  `~/shopee-corpus/seller-centre-internal/`, Shopee Uni VN (1,387 docs, SQLite FTS,
  `query.py`) in `~/shopee-corpus/edu/`. Boards: "Shopee · 4 luồng × chỉ số",
  "Shopee · hành động theo chỉ số", "Shopee · nguồn dữ liệu".
  1. **Scope (S1A, S4A, S5A, S8A, S9A, S11A, S12B):** Shopee VN only; the same frame as
     TikTok: 4 streams Thẻ sản phẩm / Video / Live / Tiếp thị liên kết, Dịch vụ Hiển thị
     (ads, lever Q) as an overlay row; the same 4 KPIs (Hiển thị, CTR, Tỉ lệ chuyển đổi,
     AOV → GMV), funnel steps only for diagnosis; a separate "Sức khoẻ shop" band (V, U);
     the same lever letters A–U.
  2. **Official API (S2, S6B, S7B):** the owner registers an Open Platform partner account
     and applies for all five app types now (ERP, Ads Service, AMS, Video Management,
     Livestream Management); Juli writes its own thin Python client (HMAC signing, 4 h /
     30 d token rotation, the shared per-shop rate limiter).
  3. **One ingest gateway (S13 → given):** every source (official API, the extension, a
     file upload fallback, data vendors) lands through one normalized ingest contract,
     tagged with its source and confidence; diagnosis and cards read only the normalized
     form.
  4. **Juli Connector, a Chrome extension (S14 → main source, S17B, S18A):** the primary
     source for what the API lacks (per-source and per-product × source traffic,
     funnel). It runs in the seller's own logged-in Seller Centre session with the
     seller's consent, never stores a password, and syncs on its own once a day while the
     browser is open, at a human-like low rate. Released Unlisted on the Chrome Web Store
     to pilot shops first, Public later. File upload stays only as a fallback.
  5. **Later / never (S15A, S16A):** a Juli MCP server comes after cards and measurement
     are stable (read-only first); a server-side bot logging in as the seller is never
     built.
  6. **Recon (S20):** the gateway and the extension skeleton start now; a second Seller
     Centre pass on a shop with orders (item rows, level-2 sources, Ads / Live / Video /
     AMS / shop-health / finance pages) is pending and gates the per-item readers.
  7. **Change strength (owner, after the volatility explainer):** a change is compared
     with the COMBINED band of both windows, √(a² + b²); because daily values are not
     independent (weekday effect, runs), the band is optimistic, so one shared rule grades
     every comparison: |change| ≥ 2 × band → "Thay đổi rõ"; 1–2 × band → "Có thể thay
     đổi"; below → "Trong dao động". "Not random" is not "caused by Juli": a day-14 result
     still needs no overlapping external change and holding guard metrics (D29/D30).
     A met day-14 target whose strength is "likely" or "noise" reads "Đạt · chưa chắc
     chắn" (S22A: a weaker result never gets a stronger label). Card candidates keep the
     1 × combined band (catch "likely" falls); certainty shows through "Độ tin cậy".
  8. **Copy (owner):** one vocabulary across the system, the Ops guide and the seller
     guide: the seller guide uses the on-screen labels only, never backend, endpoint or
     team terms.
  9. **TikTok and the connector (S21A):** the ingest gateway serves TikTok now (e.g.
     a seller-entered ad spend lands as source `manual`); TikTok ad spend moves to the
     TikTok API for Business once that app is approved; a Juli Connector reader for TikTok
     Seller Center is built only after the TikTok Shop partner terms are reviewed, and
     only for data with no official route (Juli's partner API access is not risked).
  10. **Watching platform changes (owner):** TikTok Shop and Shopee change their APIs and
      docs often. A scheduled watcher snapshots both platforms' API docs (endpoint list,
      request/response fields, push/webhook catalog, changelogs, SDK releases), diffs
      against the stored snapshot and opens one GitHub issue per change set, flagging
      endpoints Juli calls. At runtime every client (TikTok, Shopee, the connector)
      reports schema drift (missing or unexpected fields) instead of failing silently;
      Shopee push 5 `shopee_updates` is logged as a platform notice.

- **D32** — A card's KPI is set and measured on the channel its lever acts on (decision S24C,
  fast track P27, 2026-10-12). Context: D29 read the target metric over ALL channels, so a cover
  image change (seen only on the product card) was measured against CTR diluted by Video / LIVE
  traffic it cannot move, and the band of that mixture was wide (a real card showed "▲ 12–39 %").
  1. **Lever → channel:** Ảnh bìa, Tiêu đề, Mô tả → Thẻ sản phẩm (A-33 `PRODUCT_CARD`: search,
     recommendation, shop page, Shop Tab); Giảm giá, Flash sale, Giảm phí vận chuyển, Mua nhiều
     giảm nhiều → all channels (a price shows everywhere). Video / LIVE stay the content cards'
     (P14-E, already read on their own stream). Map: `optimize_product/kpi_channel.LEVER_CHANNEL`.
  2. **What is per channel:** the stored A-33 breakdown (`traffic_breakdown` impressions + CTR →
     clicks, `sales_breakdown` GMV) per product-day — so Lượt hiển thị and CTR. No per-channel SKU
     orders are stored, so CTOR and AOV stay all-channel (ADR-106 Amendment 2).
  3. **On the channel:** the adaptive window (D29.1), the window-mean band (1.2816 × stdev / √n /
     mean), the KPI clamp (kpi_min..kpi_max × band), the reference (the channel's shop median and
     the product's earlier level on it; the all-channel category benchmark is not used), "Độ tin
     cậy" (the channel's clicks and impressions CV), the GMV estimate (the channel's GMV/day), the
     "already at target" withdrawal, the pre-D29 re-score, and the day-7 / day-14 verdicts,
     strength and "target reached". The GMV-first trigger and the decomposition (D29.2) and the
     guard bands + GMV hold (D29.8/9) stay product-wide.
  4. **Fallback:** when the channel window is "ít dữ liệu" (< Dữ liệu tối thiểu clicks on the
     longest window) or the product has no breakdown rows, the KPI uses all channels and
     `kpi.channel = "total"`; otherwise `kpi.channel = "product_card"`. A card from before D32
     has no `kpi.channel` and is measured on all channels as before.
  5. **Copy:** the card's window note reads "· 30 ngày · đo trên kênh Thẻ sản phẩm" or "· 30 ngày ·
     đo trên tất cả kênh"; the Đo lường target reads "CTR · đo trên kênh Thẻ sản phẩm"; an
     all-channel card's KPI label is the metric alone ("CTOR"), no longer "CTOR - Thẻ sản phẩm".

- **D33** — Many cards per shop: an opt-in quota per cell (product owner, fast track P28,
  2026-10-12). Context: each card targets +5–10 % on one metric, so a seller should see several
  at once — up to 5 open cards per (metric × traffic stream), e.g. 5 for CTR and 5 for CTOR on
  Thẻ sản phẩm. Trial on one shop first; every other shop unchanged.
  1. **Switch:** three team tunables in the existing `shop_rules.diag_tunables` row (no
     migration, no env): `card_quota_mode` (default off), `card_quota_per_cell` (5, 1–20),
     `card_quota_max_open` (40, 5–100). Juli Ops → Cài đặt shop → "Nhiều thẻ mỗi ô (thử
     nghiệm)", Admin only, audited like the D29.11 tunables.
  2. **Cells:** a card's cell is `<target metric>@<kpi.channel>` (D32: `ctr@product_card`,
     `ctor@total` …); `content_video` / `content_live` are their own cells; a pre-D32 card is
     `@total`, a pre-D29 card takes its stage's metric, anything else is `other`.
  3. **Mode on (emission budget):** the D24.21 daily slots (3 Juli / 1 Seller Center /
     1 content) and the default daily / weekly limits are replaced by ≤ `card_quota_per_cell`
     OPEN cards per cell under an overall open cap of `card_quota_max_open`; a draft whose cell
     is full is suppressed `cell_cap`. Kept: validity / expiry, the 7-day cooldowns, D29.4 (one
     target metric per product, enforced at emission), `ops_disabled`, the gift exclusion, a
     daily / weekly / open limit Ops set explicitly, and the seller's "Số thẻ mở cùng lúc"
     (still only lowers the cap, so it wins). The planner keeps 3 × N candidates per cell
     instead of 30 per executor type.
  4. **Mode on (planner):** (a) price levers read stored facts: the discount cap is "set" when
     the shop has `default_max_discount_pct` or any SKU `max_discount_pct` rule; a running
     product discount / flash sale (`promotion_activities`, not ended, product not removed)
     blocks Juli's product discount on that product; a running Mua nhiều giảm nhiều blocks
     BMSM. Flash sale and shipping discount still need gates no stored data gives (they stay
     off). (b) **S28B "below shop level"**: a product whose GMV did NOT fall (D29 `no_gmv_drop`)
     but whose CTR / CTOR / AOV sits below the shop median by more than one band of its own
     window (enough data: not "ít dữ liệu", median with enough peers), and also below the
     channel's median on the lever's channel, gets a card: the metric furthest below; KPI =
     the minimum clamp alone (current + KPI tối thiểu × band, a point); "Độ tin cậy" Thấp;
     ranked after every GMV-drop card; payload `reason_code = "below_shop_level"`; seller copy
     "CTR của sản phẩm trên kênh Thẻ sản phẩm thấp hơn mức chung của shop (x so với y); doanh
     thu không giảm, đây là cơ hội tăng thêm". (c) The Quality-Score lever weight (D30.2,
     up to 1.5× for listing levers) is neutral, so price levers rank like listing levers.
  5. **Mode off:** byte-identical behaviour (tests compare a shop with no row and one with the
     mode explicitly off; the planner's proposals are equal with the quota inputs passed).
  6. **Reachable cells today** (from what P1 stores): `impressions@product_card` /
     `impressions@total` (title, D29 drop only), `ctr@product_card` / `ctr@total` (cover image,
     title), `ctor@total` (description; product discount when the cap rule exists), `aov@total`
     (BMSM), `content_video`, `content_live`. CTOR and AOV per channel are not reachable (no
     per-channel orders, D32.2).

- **D34** — Optimise in groups, each with a randomised delayed control (grill G1–G8, product
  owner, 2026-10-12). Context: a shop optimising 3–5 products, one of them a best-seller, cannot
  tell a working lever from luck (platform algorithm, season, competitors). Cards are also chosen
  *because* a product just dropped, so before/after alone over-credits levers (regression to the
  mean). Not built yet; D33's per-cell quota is the delivery mechanism.
  1. **Group (G1A):** target metric × lever × channel, within one shop (e.g. "CTR · Ảnh bìa ·
     Thẻ sản phẩm"), matching D33's cells and D32's channels.
  2. **Control (G2A):** of the eligible products in a group, about 1/3 are drawn at random as
     the control and get their card 14 days later (a delayed holdout: no seller loses the card
     for good). Randomisation is the only design that removes both external shocks and
     regression to the mean. A stratification score (D35) may balance the draw; it never
     decides who is treated.
  3. **Waves (G3A):** a group launches within a ~3-day window and is measured at the same day 14
     for treatment and control.
  4. **Verdict (G4A, relaxed):** difference-in-differences of the median per-product change
     (treated vs control), bootstrap interval, worded with D31.7 ("Thay đổi rõ / Có thể thay
     đổi / Trong dao động"). A verdict needs ≥ 3 treated + ≥ 2 control products and is labelled
     "Sơ bộ"; from ≥ 5 + ≥ 3 the label is dropped. Fewer: "Chưa đủ cơ sở".
  5. **Assignment, not approval (G5A):** the primary result is by assignment (intent-to-treat,
     whether or not the seller approved); approved-only is a secondary view.
  6. **Small shops (G6A):** a shop too small for a group shows "Chưa đủ cơ sở" with the
     cross-shop result for the same metric × lever ("Ở các shop tương tự, đòn bẩy này: +x %").
  7. **Learning (G7A):** every group result, from every shop, goes to a lever-effect table;
     once a metric × lever has ~10 groups, that table replaces the fixed ranking weights
     (e.g. D30.2's 1.5× listing boost).
  8. **Who sees it (G8A):** Ops sees groups, controls and intervals; the seller sees one plain
     sentence ("Nhóm 6 sản phẩm đổi ảnh bìa: lượt nhấp tăng khoảng 7 % so với các sản phẩm chưa
     đổi").

- **D35** — Buyer simulation with AI agents before the real A/B test (grill G9–G14, product
  owner, 2026-10-12). Simulated buyers get the direction right more often than the size, and
  cannot reproduce the platform's distribution, so simulation never replaces D34's control.
  1. **Role (G9A):** score each product's headroom per cell, pick the best of 3–4 variants for a
     card, and stratify D34's control draw. The real A/B test stays the judge.
  2. **Cells:** CTR · Thẻ sản phẩm (a shuffled grid of ~12 cards: the shop's and competitors'
     cover image, title, price, rating, sold) and CTOR (a product page: images, description,
     price, sampled reviews → buy or not, with a reason) first; AOV (quantity choice) later;
     Video weak; Lượt hiển thị and LIVE are not simulated.
  3. **Personas (G11A):** built from aggregate audience data and from the reviews of the
     product and its competitors (needs, purchase criteria, objections from 1–3★ reviews, usual
     spend), 8–10 archetypes per category mixed by their review share. Never from an
     individual buyer's data; reviewer identities are dropped at collection.
  4. **Competitors (G12A):** the shop's other products plus top sellers in the same category
     (stored data or FastMoss).
  5. **Randomisation:** grid order, variant order and blind labels shuffled per call with a
     logged seed; an A/A arm (the original shown twice) measures the simulation's own noise,
     and a difference counts only beyond it.
  6. **Trust (G13A):** at first the score only picks variants and stratifies; it ranks cards
     only after ≥ 10 groups show a rank correlation ≥ 0.3 with real D34 results.
  7. **Pilot (G10, G14):** Fujiwa (TikTok Shop) and Ory (Shopee), 10 products each, 50
     personas, grid 4 variants (original, Juli's proposal, 2 alternatives) + page 2 variants,
     GPT-5.4 nano. A cost estimate is printed and confirmed before the run, with a hard stop.
     Inputs and results stay outside the repo (shop data and reviews are never committed). The
     report compares the simulation with Juli's proposals (win rate with interval, headroom
     rank vs Juli's card choice, reasons), and gains a "real result" column at Fujiwa's day 14.

- **D36** — A model-free buyer simulator: a calibrated choice model run as Monte Carlo (grill
  H1–H7, product owner, 2026-10-13). The LLM simulation (D35) is costly per call; this one runs
  thousands of visits for free and learns after every run. Not built yet; prototype offline.
  1. **Model (H1A):** a discrete-choice (logit) model over card and page features: utility =
     persona weights × features + position effect + Gumbel noise → click; a page model →
     order. Interpretable and fit for little data. A machine-learning model (e.g. gradient
     boosting) replaces or augments it only once enough labelled outcomes exist.
  2. **Learning sources (H2A):** real per-product metrics (a shop's impressions / clicks /
     orders, or public category sales shares) calibrate the baseline; D35's LLM runs label the
     effect of text variants (distillation); D34 group results are the judge and update the
     weights after every wave.
  3. **Text → features (H3A):** rules and per-category lexicons (keywords, numbers such as
     volume / pack size, claimed benefits, review aspects such as delivery, taste, packaging,
     price); an LLM may draft a category's lexicon once, after which everything runs without AI.
  4. **Runs (H4, early stopping):** visits are simulated in batches of 200 over draws of the
     model's uncertain weights; after each batch the estimate (CTR / CTOR per variant and its
     interval) is compared with the previous one, and the run stops when it moves less than a
     tolerance for 2 batches in a row (patience) or at a ceiling. The variant search stops the
     same way: when new variants no longer beat the best one beyond the simulation's noise.
  5. **KPI (H5A):** the predicted range goes into `kpi_target(predicted=…)` (D30.3): it may
     narrow the [1×, 3×] band clamp, never widen it.
  6. **Where (H6A):** a prototype in the local pilot folder next to D35, compared with it;
     moved into the backend only after it meets G13 (rank correlation ≥ 0.3 with real results).
  7. **Validation (H7A):** calibrate on 2/3 of the products, predict the held-out 1/3; backtest
     past title changes where they exist. Calibration can use a public category scrape (≈200
     listings with price, sold, rating, badges, position) instead of one client shop; public
     pages carry sales but no impressions or clicks, so that calibration fits sales shares, and
     CTR / CTOR calibration needs a connected shop's analytics.

- **D37** — The product-card funnel simulator by shopper segment (grill I1–I7, product owner,
  2026-10-13). Scope: the product-card flow only; Video / LIVE later. Full design (rubric,
  model, data needs) is kept with the local pilot (`research/d37_funnel_design.md`); research
  notes (`vn_shopper_segments.md`, `funnel_model_evidence.md`) sit beside it.
  1. **Segments (I1, research-led):** four axes drawn jointly — spend archetype (Cimigo 2025),
     discovery mode (search / feed / shop-category), trust orientation, deal behaviour — plus
     traits (new vs returning, COD, hidden-fee sensitivity) and an FMCG overlay (stock-up,
     one-off trial, replenisher). Shares are priors with ranges, each labelled sourced or
     inferred; reviews never define segments.
  2. **Stages (I2A):** Chú ý (stop and look; a proxy, never the impression count, which the
     algorithm decides) → Bấm (CTR) → Chốt đơn (CTOR) → Số lượng (AOV).
  3. **Rubric (I3A):** each stage lists minimum requirements (1 point each) and "better" levels
     (+1 each), measured by rule from data where possible and by fixed yes/no AI questions
     otherwise; points sum per criterion group (0–1). The AI never decides click or order.
  4. **Model:** per-stage logit, one weight per criterion group (4–6 parameters per stage),
     a fixed position offset, segment deviations shrunk to the shared weights (hierarchical);
     the click stage is a multinomial choice in the grid with a "no click" option; AOV is a
     choice among the order options actually on the page.
  5. **Reviews (I4A):** a separate feature R per stage (card stars / count / sold; page aspect
     sentiment by true star mix), its contribution capped at 10 % of the stage's utility range;
     every run has a review-blind and a review-on arm; the cap and weight update after each
     real A/B wave (D34).
  6. **Proposals (I5A):** labelled "không phụ thuộc đánh giá" (listing facts) or "phụ thuộc
     đánh giá" (answers review objections) and reported apart, in both arms.
  7. **Guards (I6A):** rubric per category frozen before a run and versioned; parameters
     versioned; calibration / hold-out split fixed by product-id hash and locked; every run
     writes a manifest (code commit, rubric and parameter versions, category, data hash,
     seeds, split, stopping, cost, validation).
  8. **AOV (I7, revised):** only observable inputs — pack options and unit prices, buy-more
     tiers, combos, free-ship and voucher thresholds, shipping fee by quantity, purchase
     limits — and an effective price per customer type (list price minus the vouchers that type
     can use: new buyer, follower, platform-funded, Mall). Research found no per-user list-price
     personalisation, only vouchers.
  9. **Data needs:** third-party data for 3 categories × ≥ 150 products from ≥ 40 shops (≤ 10
     each), 90 days daily (prices, promotions, free ship, units / GMV by day and by channel if
     available, rating, reviews, listing attributes, Mall, SKUs) + ≥ 50 reviews per product;
     CTR / CTOR need first-party analytics: ≥ 15 connected shops, ≥ 300 products with ≥ 800
     product-card impressions / 30 days (CTOR: ≥ 150 clicks).

- **D38** — Iterative variant optimisation with simulated buyers (grill L1–L3, M1–M5, product
  owner, 2026-10-13). Context: the grid design counted rare clicks and could not separate
  variants (an A/A pair differed 2×); the pairwise design fixed that (A/A within 1–2 points) and
  showed, pooled over 10 products, buyers prefer Juli's description (60–67 %) but the original
  card (≈ 40 % chose Juli's), mostly because Juli's "less text" cover dropped the original's
  promotion banner.
  1. **Measurement (L1A–L3):** forced-choice pairwise comparisons (card pair, page pair, A/A),
     sides randomised, labels blind, both review arms; results are preference shares with
     intervals and the personas needed to conclude. Simulated absolute CTR / CTOR are never
     reported as predictions; real rates come from the calibrated model (D37).
  2. **Search (M1A):** champion–challenger rounds; challengers get personas by Thompson
     sampling; stop after 2 rounds with no challenger beating the champion beyond the A/A noise,
     at most 6 rounds. The card starts from the original, the description from Juli's version.
  3. **Challengers (M2A):** each changes exactly one tagged component of one lever, so wins
     accumulate as component knowledge per category and platform.
  4. **Anti-overfit (M3A):** the final champion must also win on a held-out persona panel, in
     both review arms, and with a second model as judge, before it becomes a card proposal;
     the real test stays D34.
  5. **Scope (M4A):** title (cover kept), cover choice among the shop's own images, cover with a
     price / promotion / voucher overlay that is actually running (rendered as a still with
     Remotion in juli-content-engine), description. Combos are out of scope; no generated
     imagery and no claim or promotion that is not real.
  6. **Budget (M5A):** ≈ $0.4–0.8 per product with early stopping and bandit allocation, a hard
     cap per run.
