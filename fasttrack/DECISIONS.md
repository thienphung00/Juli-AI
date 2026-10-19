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

- **D39** — Metric-first trigger, group proposals with simulated group tests, and D34 in the
  card system (grill N1, O1, O2, product owner, 2026-10-13). Context: Fujiwa's best sellers got
  no card because D29 opens a card only when GMV drops beyond its band; a product whose CTOR fell
  20 % while impressions rose 25 % kept GMV flat and was never proposed.
  1. **Metric first (N1A):** a card is proposed when ANY funnel metric (Lượt hiển thị, CTR, CTOR,
     AOV) drops beyond its own band (on its channel, D32), even when GMV holds. Candidates are
     ranked by the GMV that metric alone costs, from the D29.2 decomposition. Best sellers are
     included. D29.4 (one metric per product at a time) stays. For products with no metric
     drop, a "growth" branch is opened only by a simulated winner (D38) — Độ tin cậy Thấp,
     target 1× band.
  2. **Simulated group test (O1A):** one change (e.g. "pack size in the first 20 characters of
     the title") is applied to every product of a group (metric × lever × channel) and compared
     pairwise per product; pooled into a group effect with an interval and the spread across
     products. Only a change that wins clearly at group level becomes a group proposal.
  3. **D34 in the card system (O2A, fast track P30):** cards grouped by metric × lever ×
     channel; ≈ 1/3 of eligible products drawn at random as a delayed control (card 14 days
     later); a group launches within ≈ 3 days; verdict by difference-in-differences ("Sơ bộ" at
     ≥ 3 treated + ≥ 2 control); Ops sees the detail, the seller one sentence.
  4. **Implementation notes (fast track P30, 2026-10-13).**
     - *N1A:* `optimize_product/metric_trigger.py`. A metric "drops" when its adaptive-window mean
       (D29.1, `min_events` kept) on the lever's channel (D32 `kpi_window`: Lượt hiển thị / CTR on
       Thẻ sản phẩm when it has enough data, CTOR / AOV all-channel) is below the same-length window
       before it by more than 1 × the combined band (D31.7, as the GMV gate). Its GMV cost per day =
       GMV now × (e^(−c) − 1), c = the metric's D29.2 log term on that channel; a product keeps its
       costliest metric (D29.4); ranking value = cost × the D30.3 factor × reason penalty × lever
       weight (as before), stability only breaks ties. GMV read product-wide says "held" (and by
       which rising metric) or "fell" in the seller copy. Skip reason `d39:no_metric_drop`; S28B
       still needs GMV not fallen and no metric drop. Per-shop tunable `diag_trigger`
       (`metric_first` default, `gmv_first` = the D29.2 path unchanged), Ops → Chẩn đoán & KPI →
       "Điều kiện mở thẻ". Growth branch: `growth_candidates()` returns nothing (TODO D39.1). With 4
       metrics tested at 1 × band, noise opens more cards than the GMV gate did (Fujiwa-like
       fixture: 2 instead of 1).
     - *O2A (D34 in the card system):* `action_cards/card_groups.py`, migration `089_card_groups`
       (`card_groups`, `card_group_members`, RLS, juli_app SELECT/INSERT/UPDATE). Key =
       `metric|lever|channel` from the card payload. Run inside the emission budget after the
       cooldown / Ops filters: ≥ 3 drafts of one key from distinct products not in a group of that key
       launched in the last 44 days (a released control is never held twice) → a group (launch = shop day, release = launch + 14, `secrets` seed stored), arms =
       sorted ids shuffled by `random.Random(seed)`, the first round(n/3) (≥ 1) control; control
       drafts suppressed `group_control` until release; treated drafts first during 3 days; the
       budget (D24.21 slots or D33 quota) still caps. Day 14 = newest analytics day ≥ launch + 13:
       per product the target metric on the group's channel, 14 days from launch vs 14 before
       (`measurement.window_totals` / `channel_rows`), ≥ 7 days each; verdict = median treated −
       median control (points of %), 80 % bootstrap interval (2,000 resamples, the group's seed),
       strength by D31.7 against the interval's half-width; "Sơ bộ" ≥ 3 + 2, none ≥ 5 + 3, else
       "Chưa đủ cơ sở" without numbers; approved-only secondary. Ops: `GET /v1/ops/shops/{id}/groups`
       and "Nhóm thử nghiệm (đối chứng chậm)" in Cài đặt shop. Seller: `card.group_result`
       ("Kết quả nhóm") on cards of the same key once their latest group has a verdict. Tunable
       `card_groups` (unset = follows `card_quota_mode`; off = the budget never calls the group
       code). Not built: D34.6 cross-shop result for small shops, D34.7 lever-effect table,
       late joiners (a draft arriving after launch joins a new group only when 3 such drafts
       of its key are waiting together; otherwise it surfaces as before, ungrouped).

- **D40** — Learning levers from little data (grill R1–R8, product owner, 2026-10-13). Context:
  v0.1 found no stable lever on a one-shot cross-section; Fujiwa's ~60 days of daily first-party
  data (impressions, clicks, orders, GMV by channel) were not used for lever effects.
  1. **Denoise first (R1A):** empirical-Bayes beta-binomial shrinkage of per-product CTR / CTOR
     toward the category, in proportion to each product's events, before any modelling.
  2. **Within-product variation (R2A):** a panel model with product and day fixed effects on
     Fujiwa's daily data, so a lever is learned from a product's own changes (price, promotion,
     cover / title edits) rather than from differences between products; the same frame takes
     TikTok snapshot differences when they arrive.
  3. **Borrow strength (R3A):** hierarchical Bayes — shared effect + category and platform
     deviations shrunk to 0 — with priors from the D37 research and the simulated pairwise
     results, updated after each real A/B wave (D34).
  4. **Few, relative features (R4A):** a domain-chosen pool of ≈ 10–12 candidates expressed
     relative to the niche (price vs niche median, shown discount / price banner, pack stated,
     social proof shown), with sign constraints; selection by stability selection and a
     sparsity prior (horseshoe) down to 3–5 per stage; the rest only for checks.
  5. **Easier targets (R5A):** rank within niche (pairwise / learning-to-rank) or ordinal tiers;
     ordinal regression on Shopee's "k+" sold buckets.
  6. **Simulation as weak labels (R6A):** simulated pairwise outcomes enter with a low weight
     (start ≈ 0.1 of a real observation), recalibrated from real A/B agreement.
  7. **Design the next experiments (R7A):** the next A/B is chosen where the model is most
     uncertain about a lever with the most GMV at stake (bandit / optimal design).
  8. **Small-data evaluation (R8A):** GBM only as a benchmark; leave-one-shop-out and
     bootstrap; a lever counts as learned only when its sign is stable across folds, its
     interval excludes 0 and the simulation agrees in direction.

- **D41** — Acting on the D40 v0.2 / v0.3 results (grill T1–T9, product owner, 2026-10-13).
  Context: v0.2 / v0.3 (`juli-sim-pilot`, private) learned no lever; Fujiwa's CTR drifts ≈ ±15 %
  a week with nothing changed (σ week 0.15); per-product CTOR is mostly noise (91 % shrink);
  the D39.3 verdict on a 4 + 2 group raises a false alarm 18 % of the time. Findings with their
  re-measure triggers live in the pilot's `research/findings_ledger.md`; gift-with-purchase
  (negative within Fujiwa, 2 windows) is parked by the owner.
  1. **Targets unchanged until D34 #1 (T1C):** the KPI target keeps the D29 band clamp; the owner
     lowers `kpi_max_band_mult` 3 → 2 in Ops.
  2. **Shrink before the trigger (T2A, P31):** per-product CTR / CTOR are shrunk toward the
     category (empirical-Bayes beta-binomial, by each product's events) before the D39.1
     metric-first comparison with the band; tunable in Ops to switch off.
  3. **Stricter group verdict (T3A, P31):** 90 % interval instead of 80 %; a permutation test
     over the random assignment when control < 5; adjust each product's change by what its
     previous 14 days predicted (CUPED-style). "Sơ bộ" only when the group's own simulated
     false-alarm rate ≤ 10 %, otherwise "Đang đo"; checked with the v0.3 power simulator first.
  4. **D34 #1 = price-banner cover (T4A):** every eligible Fujiwa product with a real promotion
     (≈ 26, ≈ 17 treated + 9 control by the group's draw), 28 days, rule 3; purpose = calibrate
     the simulator (pre-registered), secondary = the lever. Covers rendered with Remotion; the
     owner uploads them; treated covers stay fixed for the 28 days.
  5. **Simulator fixes before D38 (T5A):** cards named X / Y, the persona notes price, sold and
     promotion of both before choosing (left-pick 69 % today); description dropped from the
     simulator (split-half −0.33); D38 runs on title and cover only, after an A/A + position
     check (left < 58 %, A/A ≈ 50 %) the owner approves.
  6. **Feature audit (T6A):** Shopee delivery (−11 %) and pack value (−6 %) re-checked with
     shop-size / unit-price controls; kept as "dig deeper" if the sign survives, fixed if a bug.
  7. **No model numbers for Ory / Shopee cards (T7A):** within-niche pairwise accuracy 50 %;
     cards use rule diagnostics and group tests only; the model is used at niche / shop level;
     reopen when within-niche pairwise accuracy > 58 %.
  8. **Next data (T8A):** FastMoss snapshot 2 ≈ 2026-10-20 (same 46 keywords); join Fujiwa's
     channel impressions with its video / live posting days (C3); niche cover images for C6,
     each download approved by the owner.
  9. **Visual distinctiveness on TikTok (T9A):** simple local image features first (colour
     distance to the niche's average cover, contrast / saturation, text-or-banner area) in the
     TikTok hierarchical model within keyword; only if there is a signal, a local image
     embedding (download approved by the owner) and a "contrast with niche" cover as a D34 #2
     candidate, read by shopper segment (simulation: discovery shoppers chose the banner cover
     73.6 % / 63.3 % vs specific-need 66.2 % / 56.2 %).
  10. **Implementation notes (fast track P31, 2026-10-13).**
      - *T2A:* `optimize_product/shrinkage.py`. Per product and window (now / the same-length
        window before, on the metric's D32 channel) CTR = clicks / impressions and CTOR = orders /
        clicks are replaced by the posterior mean (s + α) / (n + α + β) before the D39.1 1 × band
        comparison. α, β by method of moments over the shop's products of the same category, same
        channel and calendar window: m = Σs / Σn, τ² = (Σ n_i (p_i − m)² − (k − 1) m (1 − m)) /
        (Σn − Σn_i² / Σn), κ = m (1 − m) / τ² − 1 clipped to [1, Σn] (κ = Σn when τ² ≤ 0); a
        category with < 5 products uses the shop-wide prior (≥ 3 products, else raw). The band,
        GMV cost, ranking, KPI and copy keep the raw values; the card's
        `diagnosis.metric_trigger.drops[].shrinkage` records both rates and priors. Tunable
        `kpi_shrinkage` = `on` (default) | `off` in the D29.11 team row; Ops → Chẩn đoán & KPI →
        "Lọc nhiễu CTR / CTOR". Not on `gmv_first`.
      - *T3A:* `action_cards/group_stats.py`, called by `card_groups.build_verdict`. 90 % (p5–p95)
        bootstrap interval; with < 5 controls the change counts only if an exact permutation test
        over the assignment (every choice of the controls, ≤ 20 000, else 10 000 random) gives
        p ≤ 0.10 for median treated − median control AND the bootstrap grade is not noise. CUPED
        on the log scale: θ = pooled slope of ln after on ln before over all the group's products
        (clipped [0, 2]; 1 with < 3 products or no spread), adjusted change = e^((y − x̄) − θ(x − x̄))
        − 1; θ = 1 is the plain change. False alarm: 500 replays (seed = the group's) of the whole
        rule on the group's own no-effect pairs, permuted (fallback: arm-centred changes); rate
        above the gate → label "Đang đo", no strength, no seller sentence (applied to full
        verdicts too: a weaker result never gets a stronger label). Stored per comparison
        (`false_alarm`, `test`, `permutation`, `rule_strength`), at the verdict top
        (`false_alarm`, `cuped`, `null_pool`, `checks`) and in `GET /v1/ops/shops/{id}/groups`
        (`false_alarm`). No migration (verdict is JSON).
      - *T3.1 (owner, 2026-10-14, after the v0.3 power check of the P31 rule,
        `juli-sim-pilot/v03/results/20261013-191329-p31-power`):* the gate is a flat
        `FALSE_ALARM_MAX` = 15 % (no Monte-Carlo margin). At 17 + 9 × 28 days the first gate
        (10 % + 1.7-point margin ≈ 11.7 %) left 27 % of groups in "Đang đo" for good; at 15 %
        12 %, while the rule's real false-alarm rate stayed ≤ 9.6 % in every design (4+2, 5+3,
        5+5, 4+6, 17+9; 14 / 28 days). "Đang đo" is re-gated every 7 days (day 21, 28, … up to
        day 56) with the latest data: the comparison stays on days 0–13, the null pool = every
        member's pre-period pair (days −28..−15 vs −14..−1) + every control member's consecutive
        14-day pairs from day −14 that end before the seller approves its released card (−14..−1
        vs 0..13 at day 14; + 0..13 vs 14..27 from day 28) -- no lever ran on an untouched
        control, so they are no-effect by construction and the pool grows as data accrue.

- **D42** — Shopee ISV resubmission: a reviewer trial account (grill, product owner,
  2026-10-14; full record in `main`'s `docs/adr/109-shopee-isv-resubmission-reviewer-trial-account.md`,
  merged as #2134 before this branch's D4/ADR-109 numbering was noticed — that file is
  renumbered when this branch merges back). Context: Shopee rejected the Third-party Partner
  Platform profile — "unable to identify the actual service you provide via Test URL". Shopee
  §3.2 (open.shopee.com/developer-guide/12) wants a live product whose **existing** ecommerce
  integration is identifiable via a **trial account** with all features enabled; Platform Partner
  Rules §4 (developer-guide/34) penalise services that differ from the submitted description. A
  reviewer who signed in on demo.app-juli.com got a fresh account with no shop → the P13 sample.
  1. The reviewer sees the **live TikTok Shop integration**; Shopee is presented as the
     integration being applied for. No Shopee connection is built before approval.
  2. **Email + password** sign-in for reviewer accounts (the form asks username / password; a
     reviewer cannot receive our OTP). Accounts are created by the team — no password sign-up.
     Google and email-OTP sign-in for sellers are unchanged.
  3. The reviewer reads **Fujiwa, masked** (D25.6 / ADR-038 aliases: shop name, ids, titles;
     real magnitudes) through the real read path — Trang chủ, Phân tích, Quyết định.
  4. **Approval and execution are simulated and never reach Fujiwa.** The reviewer walks
     Duyệt → Thực thi and sees the change that would be sent, labelled as a trial
     simulation. The guarantee is server-side (a reviewer session cannot reach any executor,
     TikTok write or write-capable credential), proven by a test that fails on any write
     attempt for a reviewer session — hiding buttons is not the guarantee. Same spirit as
     D25.3's "all writes blocked".
  5. **One reviewer account per platform, expiring**: role `reviewer`, e.g.
     `shopee-review@app-juli.com`, default lifetime **30 days**, renew / revoke by the team,
     every reviewer session audited per platform.
  6. Public pages say Shopee's status honestly: landing names Shopee **in text** as
     "đang tích hợp qua Shopee Open Platform"; `/privacy` and `/terms` replace "Shopee support
     is in development…" with a Shopee section (which data, why, retention, Shopee's Data
     Protection Policy; effective when a seller connects a Shopee shop).
  7. Services Information text: English prose + numbered reviewer steps, no video, kept in
     `fasttrack/` for reuse by later platform reviews.
  8. TLS already meets Shopee's bar (SSL Labs A+, TLS 1.0/1.1 refused, HSTS 6 months, nosniff;
     verified 2026-10-14). Never crawl Shopee (Rules §3).

  **D42 amendment (owner, 2026-10-15)** — amends decision 3. The Shopee ISV rejection was about
  the product page and the trial sign-up, not the data, so the partner reviewer uses the
  **sample shop** ("Cửa hàng Mẫu Hoa Mai", the demo's P11/P13 no-network sample) instead of
  Fujiwa. `REVIEWER_SHOP_ID` is **optional** and is **not** set in production: unset, a valid
  reviewer session gets `GET /v1/reviewer/me` → `{reviewer: true, platform, expires_at, shop:
  null}` (no more 503), `/v1/shops` → `[]`, every shop-scoped route 403; the demo then shows
  Trang chủ / Phân tích / Quyết định over the sample fixtures under the reviewer banner ("dữ liệu
  mẫu"), no connect / invite / upload entry, and Duyệt → Thực thi as the same labelled
  simulation ("Mô phỏng · không gửi tới TikTok"), computed in the browser, nothing sent. Set,
  the Fujiwa pin + mask of decision 3 applies unchanged. Decision 4's server-side guarantee
  (allowlist, write barrier, no-write proof) is the same in both modes. (P32-D)

  **D42 amendment 2 (owner 2026-10-15): all features simulated in sample mode.** Shopee's ISV
  criteria ask for a trial account with "all features enabled for Shopee testing"; with only
  Duyệt usable the reviewer saw mostly disabled controls. In sample mode (no pin) **every** seller
  write is usable as a visible simulation computed in the browser over the sample fixtures, on one
  in-memory store kept for the browser tab (a reload, sign-out or "Đặt lại dữ liệu mẫu" starts it
  over): Từ chối with its reasons; Duyệt → Thực thi, then "Theo dõi lượt chạy (mô phỏng)" into the
  sample run — consent with "Sửa nội dung trước khi áp dụng", the cover-photo step, the Seller
  Center step, content cards "Juli soạn · bạn làm" (Soạn lại / Dùng / Tôi đã đăng, canned
  drafts); the run timeline; Đo lường with a day-7 / day-14 "tua nhanh"; Hoàn tác; Quy tắc
  (Quyết định and Cài đặt, same store); "Phân tích video" (the file is never read or sent — a
  canned analysis is shown). Labels: "Mô phỏng · không gửi tới TikTok", settings "Mô phỏng ·
  không lưu". Still hidden for a reviewer: connect / disconnect shop, invites, ops. The pinned
  (Fujiwa) mode is unchanged (read-only, API simulation). No backend change: in sample mode the
  demo calls no shop route at all, so the allowlist and write barrier are untouched; the only
  request of a reviewer session is `GET /v1/reviewer/me` (proved by `reviewer-all-features.test.tsx`).
  (P32-E)

- **D43** — app-juli.com as a business site that passes ISV review and indexes cleanly (grill,
  product owner, 2026-10-15). Inputs: an SEO expert's review (recording 2026-10-14: site too
  small, product page ~700 words and URL `/product` not descriptive, missing canonical, homepage
  should present the company while product pages sell, a demo on a subdomain must be noindex,
  heavy JS, needs a blog of long well-structured articles with internal links, Base.vn as the
  local benchmark); PageSpeed mobile 2026-10-14 (Perf 93, A11y 96, BP 100, SEO 100; LCP 2.9 s,
  SI 4.1 s; image delivery 71 KiB, legacy JS, unused JS, images without width/height, one
  contrast failure; no CrUX field data); index audit (robots + sitemap present; no canonical, no
  OG, no JSON-LD, no lastmod; demo.app-juli.com indexable); benchmark of 18 SaaS sites.
  1. **IA**: `/san-pham` (overview) + `/san-pham/phan-tich-shop`, `/san-pham/de-xuat-va-thuc-thi`,
     `/san-pham/do-luong-gmv`, `/ket-noi/tiktok-shop`, `/blog`; `/product` → 301 `/san-pham`.
  2. **Homepage = company + product overview**: H1 states the service in one sentence; marketplace
     strip (TikTok Shop live via Open API, Shopee "đang tích hợp", D42); three capability blocks
     linking to the product pages; how it works; data safety; who it is for; price "từ 500K" +
     FAQ; company identity. Detailed selling lives on the product pages.
  3. **Proof = transparency only**: method, labelled sample data, data commitments, company and
     team. No case study, no testimonial, no invented number until real customers exist.
  4. **Capability pages ~2,500 words each** (overview ~1,500), H1 → H2 → H3, one real UI
     screenshot per H2 (sample data, labelled), AVIF/WebP with width/height, FAQ.
  5. **Technical SEO**: unique title / description, absolute self canonical, OG + Twitter (1200×630
     image), JSON-LD Organization (address, MST 0319617654, ContactPoint) + WebSite everywhere,
     SoftwareApplication + Offer (500000 VND) on product pages, FAQPage only where an FAQ is shown,
     BreadcrumbList on inner pages, Article on posts; sitemap with lastmod; **demo and ops
     noindex** (`X-Robots-Tag` + meta; robots.txt keeps them crawlable so noindex is seen);
     PageSpeed fixes. Target mobile LCP < 2.5 s, Performance ≥ 95.
  6. **Hero video**: poster image (AVIF/WebP) with ▶; the video loads only on click
     (`preload="none"`); VideoObject schema.
  7. **Blog**: `/blog` index + 3 pillar posts of 3,000+ words — (1) TikTok Shop metrics
     (Hiển thị, CTR, CTOR, AOV) and how to read them, (2) optimising the TikTok Shop product card
     A–Z, (3) top tools for TikTok Shop sellers 2026 — drafted by Claude from internal knowledge,
     **owner approves before deploy**; then 2 posts / month. Internal links to product pages.
  8. **No social links** (no footer icons, no `sameAs`). **Vietnamese only** (no `/en`, no
     hreflang; privacy / terms keep their EN sections).
  9. Delivery: P33-A (technical SEO + shared helpers) first, then P33-B (homepage + overview),
     P33-C (capability pages), P33-D (blog) in parallel on top of A.
- **D43 additions** (owner, 2026-10-15, answers to P33-B's questions):
  1. **Hero video stays** as is; the caption "Số liệu trong video là minh hoạ" is enough. No re-cut.
  2. **The 3-month trial is real and free.** Every "Dùng thử miễn phí 3 tháng" CTA on app-juli.com
     (homepage hero, pricing, final CTA; `/san-pham` hero, pricing card, final CTA) goes to
     `SIGNUP_URL` = `/dang-ky`, an internal fast form page built by P33-F
     (`fasttrack/p33f-trial-signup`, with its thank-you page and backend); TikTok Pixel tracking
     stays on these CTAs. The thank-you page's "Tự kết nối shop ngay" opens the Demo at
     `/?dang-ky=dung-thu`, where the sign-in door reads "Đăng ký dùng thử miễn phí 3 tháng"
     (create the account with Google or email, then connect TikTok Shop; free 3 months, then from
     500.000đ/tháng; no payment card — verified: Juli has no payment integration, D28.4/D28.5).
     "Đăng nhập" stays for existing users; the partner password door (P32-A) is untouched. `/terms`
     §5 states the trial. No trial tracking or billing is built.
  3. **No seller disconnect button.** Public copy: to disconnect, the seller contacts Juli (email /
     `/contact`) and the Juli team disconnects the shop (Ops Admin "Huỷ kết nối", D25.13). No
     "revoke in Seller Center" instruction.
  4. **Keep** the old `public/media/juli-demo-poster-v1-*` files.
- **D43 additions — P33-F free-trial sign-up** (owner 2026-10-15: a fast sign-up form on
  app-juli.com and a backend that stores it; details below chosen by the P33-F agent, **PROPOSED**
  until the owner confirms 2, 3 and 5):
  1. `/dang-ky` (indexable) posts server-side through the landing's own `POST /dang-ky/gui` to the
     public `POST /v1/trial-signups` (no CORS change). `/dang-ky/cam-on` is noindex, out of the
     sitemap; "Tự kết nối shop ngay" opens `https://demo.app-juli.com/?dang-ky=dung-thu`.
  2. **Ops tab "Đăng ký dùng thử" needs Vận hành or Admin** (list and status change); Xem gets 403.
     Its responses are **not** buyer-PII-masked: D25.6 masks connected shops' buyers; a sign-up is a
     prospect who gave these details to be called back.
  3. **Retention (privacy text):** a sign-up that does not become a customer is kept at most
     12 months, then deleted; deletion on request within 30 days. No purge job yet (DEBT).
  4. `trial_signups` is `ops_only` (migration 091); the visitor IP is stored only as an HMAC.
     Limits: 5 stored sign-ups / IP / hour, 3 / e-mail / day, 120 site-wide / hour; honeypot hits
     are answered 201 and not stored.
  5. The landing forwards the visitor IP with a shared `TRIAL_SIGNUP_RELAY_KEY`; without it every
     sign-up counts against the landing server's own IP (5 / hour in total) — the owner must set it.

- **D44** — Public UI redesign (owner approved the mockups, 2026-10-15). Scope: every page of
  app-juli.com and the demo's sign-in / sign-up screen; NOT the demo app's inner UI. Research:
  3 agents (large SaaS marketing sites, SaaS auth screens, audit of Juli's pages and assets).
  Spec = the approved mockups, copied to `fasttrack/design/p34/*.dc.html` (canvas
  https://claude.ai/artifact/1jCTG7NxQP9fRP6Ur1o2nk; `/_blob/<id>` images there map to the repo
  files: bird-glyph, logo-wordmark, cap-* screenshots).
  1. **Type**: Be Vietnam Pro (Vietnamese-native) for the landing and the auth screen, actually
     loaded (today Inter is named but never loaded). h1 56/62 (mobile 34/41), h2 36–44, body 17/28;
     weight 600 headings / 400 body; letter-spacing never tighter than −2 % (stacked diacritics).
  2. **Colour**: ink `#121214` for primary buttons and headings; body `#4a4a52`; muted `#6b6b74`;
     hairlines `#ececf0`; alt sections `#fbfbfc`; screenshot backdrops `#f6f4f6`; pink `#f86ba5`
     is accent only (dots, the "Duyệt" step, one flourish), pink text only `#b0386a`; one dark
     band per page (pricing / final CTA). `packages/theme/tokens.css` stays byte-pinned —
     landing tokens live in the landing app.
  3. **Imagery**: real Juli UI screenshots (sample data, always captioned "Dữ liệu mẫu") in
     hairline / browser-chrome frames on a tinted backdrop, cropped to the point; mobile gets its
     own crops; block-built diagrams (funnel, 5 streams, 5-step loop); one line-icon set; the
     bird + dashed flight path as the single hero flourish. No stock photos, no invented numbers,
     no `hero-mascot.webp` (bakes in invented figures), none of the sales-video frames with figures.
  4. **Pages** follow the mockups: home (hero with product shot, marketplace strip, loop,
     zig-zag capabilities, data safety, audiences, transparency + company card, dark pricing band,
     FAQ, footer); capability pages (breadcrumb, split hero, framed shot, TOC + one image per H2,
     diagram, FAQ, next links, dark CTA); blog (featured + 3-up grid, flat tinted covers per
     category, no text in images, HTML-rendered covers also used as OG images); legal (720 px
     column, plain-language summary, numbered sections, side TOC → disclosure on mobile, VN/EN
     switch); `/dang-ky` (2-col form + "Sau khi bạn đăng ký" panel).
  5. **Auth screen** (demo): no app shell; one 400 px column; "Tiếp tục với Google" the only
     filled button, email OTP second, "Xem thử với dữ liệu mẫu" a link, "Tài khoản đối tác" a
     footer link to its own form; right panel with a product shot on desktop; trial variant
     (`?dang-ky=dung-thu`) = same layout, copy only; OTP 6-box entry with error / expired / resend
     states.

- **D45** — Putting the simulator research priorities into Ops (grill G1–G6, product owner,
  2026-10-16). Source: `~/juli-sim-pilot/research/funnel_priorities.md` (token-free segment
  funnel simulator v1 + research run `20261015-212942` + literature review). **Scope rule:**
  everything simulator-related lives in **Ops only**, for internal use and testing; the
  client-facing app is unchanged until the method is optimised and the owner decides to ship it.
  1. **Pack group (G1A):** a D34 group testing "add a 2× pack at −5 % per unit", run in parallel
     with the D34 #1 price-banner group on **different products**: 4 treated + 2 control among
     the busiest products, 4 weeks. The owner creates the SKU on TikTok; Juli never writes it.
  2. **Pack metric (G2A):** primary = AOV and items per order on **all channels**; product-card
     CTR is a guard (warn when it falls > 15 % even if AOV rises). The P31 group verdict gains
     AOV (90 % interval, false-alarm replay, pre-period adjustment). Research: all-channel order
     value SE 0.16 vs product-card GMV/impression 0.90.
  3. **Test selection (G3A):** pick the next group by knowledge gradient (6 simulated waves:
     loss vs true best 5.2 % → 3.2 %, vs 4.7 % for "top predicted"), only among proposals
     predicted no worse than the original; each group shows a one-line reason in Ops. The
     simulator suggests and the owner approves in Ops; backend selection only after 2–3 D34
     groups have results.
  4. **Drift floor (G4B):** Ops shows the weekly-drift floor of a group's 90 % interval
     (σ 0.15/week: 6 products × 2 weeks ±10.1 %, 26 × 2 weeks ±4.8 %) next to the impressions
     needed; no label, no gate.
  5. **New SKU prior (G5B):** the simulator gives a new pack option an attractiveness offset of
     −1 by default (2× pack: +15 % GMV/impression instead of +37 %), learns the real offset from
     the pack group by re-weighting posterior draws, and uses the nested quantity model
     (`--qty-nest`, nest 0.58 [0.33; 0.79]).
  6. **Pre-period adjustment (G6A):** in the same phase as item 2, Ops-only: groups with ≥ 15
     products use two pre-period windows (days −28…−15 and −14…−1; CTR variance −17 %, power at
     +40 % 58 → 70 %); groups < 15 use the plain change score (θ = 1), because the fitted θ made
     4+2 groups worse (SE 0.17 → 0.26). Applies to CTR, CTOR and AOV; re-run the P31 power check
     and keep false alarms < 15 %.
  10. **Implementation notes (fast track P36, 2026-10-16; branch `fasttrack/p35-sim-ops`).**
     Items 1, 2, 3 (Ops display only), 4, 6, 8; all Ops-only (migration `092_card_group_design`
     adds the nullable JSON `card_groups.design`).
     - *1 / 8:* Ops → "Tạo nhóm thử nghiệm" (`POST /v1/ops/shops/{id}/groups`, Operator, audited
       `card_group_create`): lever `pack_option` "Quy cách mới" (never a card), 3–60 shop products
       not in another group, seeded ≈ 1/3 control; optional "Chia tầng theo số đơn 30 ngày" =
       the busier half (rounded up) by all-channel 30-day SKU orders is `high`, the rest `low`,
       each drawn separately (3 + 3 → 2 treated + 1 control each, ≥ 6 products). The owner
       creates the SKUs on TikTok; Juli writes nothing there. No seller sentence for an Ops
       group; its products are never drawn into a card group; it is measured even with card
       groups off (`only_ops`).
     - *2:* every verdict gains `metrics` for AOV and items per order (items sold / SKU orders)
       on all channels, through the same `build_verdict` (90 % interval, false-alarm replay,
       pre-period rule). A group's `design.guard` (default on unless the primary is CTR) adds
       product-card CTR and `verdict.guard`: warning when treated − control < −15 points of %
       (`group_guard_ctr_drop`), point estimate only, worded "… dù AOV tăng …".
     - *3:* the one-line "lý do chọn thử nghiệm" (`design.reason`, ≤ 200 chars, `PATCH
       …/groups/{group_id}`, audited `card_group_reason`); selection itself not built (D45.3).
     - *4:* `group_design.drift_floor`: pooled z·√(2σ²/weeks/n) and difference
       z·√(2σ²/weeks·(1/n_t + 1/n_c)), σ = `group_drift_sigma` 0.15; traffic needed per arm for
       ±10 % (research `impressions_needed`; AOV in orders with order-value CV 0.6), with and
       without drift; shown under each group, no label, no gate.
     - *6 (amended by D47.1):* `group_stats.adjust_changes`: < `group_two_window_min` (15)
       measured products the P31 fitted θ (one window; θ = 1 was built first and dropped after
       the power check);
       from 15 OLS on ln(−14..−1) and ln(−28..−15) (θ₁ ∈ [0, 2], θ₂ ∈ [−1, 1]); from 15 without
       the earlier window the P31 θ. The replay's pool entries become triples when the window
       before is known, so the gate runs the same rule. **Scope:** a card-drawn group's primary
       verdict (behind the seller's "Kết quả nhóm") keeps the P31 rule so the client app does not
       change; its D45.6 reading is stored beside it (`verdict.ops_rule`) and shown in Ops.
       Ops groups and every extra metric use D45.6. Power check: see LOG (P36).

- **D46** — Product polish on app-juli.com (owner, 2026-10-16, Vietnamese request, paraphrased):
  1. **Header "Sản phẩm" is a dropdown** (SaaS-style, small): Tổng quan sản phẩm (`/san-pham`),
     Phân tích shop, Đề xuất và thực thi, Đo lường GMV, each with a one-line description. A
     disclosure button (`aria-expanded` / `aria-controls`, Escape returns focus, click outside and
     route change close it); the four links are always in the server HTML (hidden by CSS, so they
     stay crawlable); on phones the menu shows "Sản phẩm" as an expandable group. "Kết nối TikTok
     Shop", Blog and Giới thiệu stay top-level.
  2. **`/san-pham` hero gets a framed product screenshot** in a two-column hero (stacked under the
     copy on phones), captioned "Dữ liệu mẫu", **not** prioritised: on mobile the H1 is the LCP and
     an eager hero image regressed LCP 2.5 s → 3.4 s (P34 LOG). The same shot is not repeated
     lower on the page.
  3. **"Vòng làm việc" is a compact 5-step stepper** (number + icon, 1–3 word title, one short
     line each). Facts stay as P34-C corrected them (five traffic sources; at day 7 Juli *asks*
     whether to revert when a guarded metric leaves its band; comparison with similar unchanged
     products is being tested); the longer explanations live on the capability pages.
  4. **No em dash "—" in visible copy** (page text, alt text, `<title>`, meta / OG text, JSON-LD
     names): a comma where it reads naturally, otherwise ":" or a rephrase. `<title>` suffixes
     use " | " ("Phân tích shop | Juli AI"), never a comma. En dashes in ranges ("7–14",
     "trước–sau") stay. Code comments, CSS, READMEs and docs are not copy and are untouched.
     **Exception: `/privacy` and `/terms`** (incl. `privacy-policy-english.tsx`,
     `legal-template.tsx`) are left word-for-word as they are, because their text must match the
     signed contract and the legal markdown (memory: legal docs sync); a dash change there goes
     through the contract first.
  5. **Owner follow-up (2026-10-16):** (a) the `/san-pham` hero puts all its copy in one left
     column in reading order (eyebrow → H1 → intro → CTAs, left-aligned) with the framed shot in
     the right column, like the home hero; phones: copy, then image. The intro text is unchanged.
     (b) The homepage H1 becomes the owner's line alone, **"Trợ lý AI vận hành TMĐT: tìm chỗ cải
     thiện GMV."** (the old tail ", đề xuất cách sửa, đo kết quả." is dropped: the lead under it
     already says Juli finds, proposes and changes only after approval, and the shorter H1 no longer
     runs to 5 lines at 1440). "TikTok Shop" stays in the home `<title>` and meta description
     (unchanged). The P34 mockups in `fasttrack/design/p34/` keep the old H1 as the historical
     spec. (c) The home price card is not touched (fixed in 8c03c6a5).
  6. **Heading outline** (owner follow-up, 2026-10-16): the home marketplace strip's "Sàn Juli kết
     nối" is a label (`<p>` naming the strip region and its list), not an H2. Guard on every public
     page, both rendered (`__tests__/heading-outline.test.tsx`) and built (`check:seo`): exactly one
     H1 and it comes first, no skipped level, no empty heading, no heading inside the site header
     (incl. the dropdown), any nav, or the footer.
  7. **Positioning: TMĐT, not only TikTok Shop** (owner follow-up #3, 2026-10-16). Sentences that
     say what Juli AI *is* or *does* name e-commerce sellers ("nhà bán TMĐT"): /san-pham H1 and
     intro, "Juli AI là gì", audience line, about lead + company row, footer tagline, OG alt and a new
     OG image (`/og/juli-ai-default-v2.png`, v1 kept), VideoObject name, home / product / blog /
     signup titles and descriptions (which flow into SoftwareApplication JSON-LD), blog index lead.
     Accuracy (Shopee / TikTok partner rules): where a platform is named, only TikTok Shop is
     connected and Shopee is "đang tích hợp"; no other marketplace is named. "TikTok Shop" stays
     wherever the fact is TikTok-specific (connect page, Open API, OAuth, traffic sources, TikTok's
     formula, capability page titles / descriptions about TikTok data, the TikTok Pixel cookie text,
     blog posts about TikTok) and in the home and /san-pham `<title>` for search. `/privacy` and
     `/terms` unchanged (D46.4): /terms §2 "Juli AI là trợ lý giúp người bán TikTok Shop tăng trưởng
     …" now disagrees and goes through contract + md + site together. Outside the landing,
     `dictionary.md` `landing.footer.tagline` still reads "Trợ lý AI cho người bán TikTok Shop".
  7. **Generalise beyond Fujiwa (owner, 2026-10-16):** every simulator parameter carries a
     scope (platform / category / niche / shop / product); one shop's fitted values only set
     that shop's deviations, and a new shop starts from category / platform values. Each
     proposal type declares eligibility from product attributes (consumable vs durable, unit /
     pack structure, price vs niche, variants, order volume, platform); one lever type ≤ 40 %
     of a shop's suggested tests; a lever becomes a default only if its effect holds in ≥ 3
     categories of the cross-section; D34 results pool by lever type across shops with a
     between-shop variance (one shop = one draw). Checked by a leave-Fujiwa-out run.
  8. **Pack group membership (owner, 2026-10-16, option A):** the Ion Kiềm listings are split
     between the two groups so both have high-order products. Proposed (orders / 30 days):
     price-banner group keeps Ion Kiềm 450 mL (495) and 680 mL (153); the pack group pool is
     Ion Kiềm 300 mL (331), Ion Kiềm 1250 mL (229), Tinh Khiết 450 mL (32), Súc miệng 680 mL
     single (13), Canxi 12 túi (6), Xịt thơm 14 mL (8). Randomisation is stratified by order
     volume: high stratum (the two Ion Kiềm + Tinh Khiết) → 2 treated / 1 control, low stratum
     → 2 treated / 1 control. The owner confirms against the banner group already in Ops and
     creates the 2× SKUs on TikTok; the result is read for learning (90 % interval ≈ ±54 %),
     not as a firm verdict.
  9. **Priors follow the cross-section (owner, 2026-10-16, option A):** the leave-Fujiwa-out
     run (`funnel/results/generalise/20261016-112135`) found priors that the pooled
     cross-section (~2,400 listings) contradicts. Free ship: prior +0.20 → about 0; title
     volume: about 0 → about +0.16/SD; the quantity step for a new shop becomes more
     conservative (unit-price drop held in only 2/6 categories). Uncertainty stays wide, priors
     are versioned, and the change applies to the simulator and Ops only.

- **D47** — Follow-ups to D45 and the demo card lifecycle (owner, 2026-10-16).
  1. **Small groups keep the P31 θ (amends D45.6):** groups < 15 products go back to the
     fitted P31 pre-period θ; groups ≥ 15 keep the two windows. The P36 power check (500 reps,
     CTR) found θ = 1 lowered power (4+2 · 28 d 35 → 25 % at +40 %, false alarms ~7 % either
     way), contradicting research §4a (fitted θ worse for 4+2). Both readings are kept and
     re-checked against the first real D34 groups.
  2. **Demo sample data mirrors the real card lifecycle (Q1 A):** pending → Duyệt → running
     (run queued → running) → consent / waiting_external → completed → applied + measurement
     waiting → day 7 → final; declined consent or "Không thực hiện" → rejected + 7-day
     cooldown; Từ chối → rejected; revert → rejected; failed / cancelled / timed-out run →
     pending; 7 days untouched → expired; Seller Center / promotion runs with no recorded write
     stay running as in the real `_status`. Home and Phân tích sample views follow the same
     store.
  3. **Reviewer (Q2 yes; D42 amendments 1–2 unchanged):** production keeps the reviewer on the
     **sample shop** (REVIEWER_SHOP_ID unset, so Fujiwa's products are never shown). The reviewer
     shares the sample store, so item 2's lifecycle applies to the reviewer too; the pinned
     Fujiwa mode is not changed. Sign-in stays D42.2: team-created **email + password**
     reviewer accounts, no OTP code needed.
  4. **Shopee connection status in Ops (Q3):** not needed now.
  5. **Cancelled / timed-out runs reactivate the card (owner, 2026-10-16, option A):** like a
     failed run today, a run that ends `cancelled` or `timed_out` puts its approved card back to
     `active` (clears `approved_at`), so the seller sees "Chờ duyệt" again instead of a card stuck
     on "Đang thực hiện"; the demo sample (P37) already does this.
  6. **Partner sign-in visible at the top (owner, 2026-10-16; amends D44.5):** the demo auth
     screen shows the "Tài khoản đối tác" entry at the top of the sign-in column (above the
     heading, clearly secondary to "Tiếp tục với Google"), so a partner reviewer finds it without
     scrolling; the footer link stays.
  7. **Simulation copy is short and shows no backend internals (owner, 2026-10-16):** every
     seller- and partner-reviewer-visible screen (the simulated Duyệt → Thực thi, the run
     timeline, the queue, the reviewer's page label, Đo lường's preview, Quy tắc, Phân tích
     video, the sample runs) shows no endpoint path, HTTP method, API operation or tool name,
     model name, output format, decision id, status code or internal "mã" wording. The label
     "Mô phỏng · không gửi tới TikTok" is the single simulation disclaimer per surface, with at
     most one short line beside it; the D42 amendment 2 promises are unchanged (every write
     visibly simulated and labelled, nothing sent). The sample's canned run text matches its
     product, and a run's chip follows its events (never "Trong hàng đợi" next to a waiting
     consent). Ops pages are internal and out of scope.

  **D47 implementation note (P37, 2026-10-16, branch `fasttrack/demo-lifecycle`).** Item 2 lives in
  `apps/demo/src/lib/quyet-dinh/sample-clients.ts`: each card keeps a desk status like
  `ActionCard.status` (active / approved / dismissed / expired) and the seller status is derived
  like `card_view._status` (approved → "Đã áp dụng" only when the latest run completed with a
  recorded write, else "Đang thực hiện"; active → "Hết hạn" 7 days after `surfaced_at`). Runs start
  `queued`; Từ chối, a declined consent, "Không thực hiện" (a wait it stops ends `cancelled` /
  `cancelled_by_seller`) and Hoàn tác (at its start, like `start_revert` + `close_card`) close the
  card with the 7-day cooldown; a failed / cancelled / timed-out run puts it back to "Chờ duyệt".
  Two sample-only seams reach what a click cannot: `advanceTime` (consent lapses after 4 h →
  `confirmation_expired`, external waits after 3 days → `external_wait_expired`, expiry) and
  `failRun`. The store is the tab-wide `lib/reviewer/sample-store.ts` (signed out, no shop and the
  sample reviewer); Quyết định re-reads it on every card change (`QdClients.subscribeDecisions`,
  sample only — the real clients are unchanged) and Phân tích reads its on-desk cards. Trang chủ has
  no card surface (signed in or sample), so nothing there changes. Item 3: no code beyond the
  shared store; the pinned Fujiwa `ReviewerSimulation` is untouched; the reviewer's only request is
  still `GET /v1/reviewer/me` (`reviewer-all-features.test.tsx`). Two readings differ from the real
  backend and are in DEBT (P37): the backend reactivates the card only for `failed`
  (`cancelled` / `timed_out` stay approved → "Đang thực hiện"; fixed by item 5, P38), and content runs record no write so
  their card stays "Đang thực hiện" after "Tôi đã đăng".

  **D47.5 implementation note (P38, 2026-10-16, branch `fasttrack/run-reactivate`).** One helper,
  `services/agent/card_reactivation.py::reactivate_card_for_ended_run`, is the only writer of
  `approved` → `active` (`approved_at` cleared) and runs for `failed`, `cancelled` and `timed_out`
  (`completed` and the waiting states never). Its callers are every terminal writer of a run:
  the runner's `JsonbConversationStore.persist` (seller / Ops `cancel_requested` →
  `cancelled_by_seller`, wall clock / iteration cap → `timed_out`, errors → `failed`), the worker
  crash handler (`failed`) and the reaper sink (consent lapse `confirmation_expired` → `cancelled`,
  `external_wait_expired` → `timed_out`, and `worker_lost` → `failed`, which until now did NOT
  reactivate — closed as part of "exactly like failed"). Seller declines are unchanged: Từ chối,
  "Không thực hiện" (consent step, or a lever-flow wait via `end_wait_by_seller` → `cancelled` /
  `cancelled_by_seller`) and Hoàn tác dismiss the card through `close_card` in the decline's own
  transaction, and the helper moves only an `approved` card, so a dismissed card stays dismissed
  (also when the reaper lapses a consent the seller already declined). Idempotent; the card must
  belong to the run's shop (read under the run's RLS scope; a mismatch is logged and skipped).
  `surfaced_at` is kept: a reactivated card older than 7 days is "Hết hạn" on the next read and is
  expired by the next emission-budget pass; a younger one counts as open again (it did not while
  approved). Logged as `action_card_reactivated_after_run`.

  **D47 implementation note (P40, 2026-10-16, branch `fasttrack/partner-top`).** Item 6 lives in
  `apps/demo/src/components/auth/auth-screen.tsx`: the entry view (shared by the plain and trial
  variants, so both get it; not the OTP or partner views) opens with one link above the h1, an
  outline pill (hairline #ececf0, white, no fill so "Tiếp tục với Google" stays the only filled
  control): muted lead "Đối tác thẩm định?" + pink action "Đăng nhập bằng tài khoản đối tác →" (arrow
  `aria-hidden`; accessible name "Đối tác thẩm định? Đăng nhập bằng tài khoản đối tác"). It shares
  the footer link's href and click handler (in-page `#doi-tac` when `renderPartner` is passed, i.e.
  `/auth/email`; else `/auth/email#doi-tac`). Keyboard order is now logo → partner entry → Google →
  email. Copy `AUTH_PARTNER_TOP_LEAD` / `AUTH_PARTNER_TOP_ACTION` in `lib/auth-screen-copy.ts`, CSS
  `.auth-partner-top` in `app/auth-screen.css`; at 390 px the pill wraps to two lines (radius 20 px,
  not 999, so it still reads as one control). The footer link stays. The ISV reviewer steps
  (`fasttrack/shopee-isv-services-information.md` step 1) now give the direct URL
  `https://demo.app-juli.com/auth/email#doi-tac` and the top link.

  **D47 implementation note (P41, 2026-10-16, branch `fasttrack/sim-copy`).** Item 7. The
  simulated Thực thi (`components/quyet-dinh/simulation-dialog.tsx`) drops the request line
  (`PUT /product/202309/products/{product_id} (update_product_listing)`, or "Không có lệnh ghi lên
  TikTok…") and the second disclaimer ("Không có thay đổi nào được gửi tới TikTok Shop. Không có
  tác vụ nào được tạo."); it keeps Thao tác / Sản phẩm and the Mục / Trước / Sau table and shows
  `change.note`, now one line per executor (`_NOTES` in `services/reviewer/simulation.py`, mirrored
  by `REVIEWER_SIMULATION_NOTES` in `lib/reviewer/copy.ts`; `juli_drafts` added — content cards had
  the Seller Center text). The response still carries `request` (contract p32 §4 unchanged); only
  the screen stops showing it. The "Sau" cell without a proposal is per executor
  (`_AFTER_DEFAULT`: a promotion says "Bạn áp dụng trên Seller Center", not "Juli soạn nội dung").
  Reviewer page label → "Mô phỏng · không gửi tới TikTok · chạy trên dữ liệu mẫu"; Đo lường "Xem
  trước kết quả đo:"; Quy tắc "· chỉ giữ trong phiên này"; Phân tích video "· tệp không được tải
  lên, đây là phân tích mẫu" (the duplicate hint "Mô phỏng: tệp không được tải lên." removed);
  signed-out notice "Dữ liệu mẫu · {shop} là shop minh họa · không ghi gì lên TikTok Shop.".
  Plain wording for TikTok's flags: the backend's `tool_completed_summary` (real runs) and the
  sample say "Mô tả quá ngắn" / "A, B, C và 2 lỗi khác" / "TikTok không báo lỗi nào" (was `Có mã:
  "…"` / "Không có mã chẩn đoán"); card "Xem thêm" "TikTok báo: “…”" (was "TikTok báo mã chẩn
  đoán"); content runs "Đã soạn và kiểm tra" / "Đã soạn kịch bản (bản N) · đã kiểm tra" (was
  "gpt-5.4-nano · đầu ra JSON schema · đã kiểm tra", backend `MODEL_STEP_RESULT` too); quick-scan
  tooltip without "công thức D22"; error lines without "(lỗi {status})"; Quy tắc helps without
  "API". Sample data: each listing card carries its own keyword line (MN-015 said "son lì, đỏ
  ruby"); the video card's rules read says "2 từ cấm" (the sample rules have two). Queue: `runPhase`
  answers "queued" only while the events show no tool or consent (a polled row could still say
  `queued` after the consent was up), and the sample store re-reads the run list when a run's
  status moves. Tests: `src/components/__tests__/sim-copy-p41.test.tsx` (5; the two chip tests fail
  without the fix), `test_reviewer_access.py` +4 (note per executor), updated pins in
  `reviewer-mode`, `reviewer-sample-mode`, `sample-quyet-dinh`, `quyet-dinh-p10`,
  `test_agent_tool_product_diagnoses.py`, `test_p14_content_flow.py`. Legacy pre-P10 routes
  (`/decisions/recommendations/*`, `/settings/workflows/*`, `lib/workflows/*`) are not linked from
  the current UI and were left as they are (DEBT P41).

- **D48** — Search-intent brand priorities on app-juli.com (owner, 2026-10-16: "áp 5 brand
  priorities lên trang", using the Semrush numbers). Evidence: Semrush Keyword Magic, database
  Vietnam, free plan (10 rows per seed, 10 requests/day), 2026-10-16. Volume / KD / intent:
  `gmv là gì` 4,400 / 21 / I; `gmv` 1,600 / 25 / I; `cách bán hàng trên tiktok shop` 1,300 / 28 / I;
  `bán hàng trên tiktok shop` 1,000 / 34 / I; `cách chạy quảng cáo tiktok` 1,600 / 22 / I;
  `tiktok shop` 135,000 / 40. No Semrush data (volume too small for the VN database, but present in
  Google autocomplete): phần mềm / quản lý / phân tích / tối ưu tiktok shop, gmv max, tăng doanh số
  tiktok, không ra đơn, ctr tiktok. The five priorities and where each lands:
  1. **Phần mềm AI phân tích và vận hành TikTok Shop** (commercial) → `/san-pham` title and meta.
     Home title and H1 stay as the owner set them (D46, f7337452).
  2. **Cách tăng GMV TikTok Shop** (informational; `gmv là gì` is the biggest term) → a home FAQ
     "GMV là gì, tăng GMV TikTok Shop bằng cách nào?" (in FAQPage schema) and
     `/san-pham/phan-tich-shop` title / meta / one H2 worded around tăng GMV.
  3. **TikTok Shop không ra đơn: tìm nguyên nhân qua CTR, CTOR, AOV** → `/san-pham/phan-tich-shop`
     H2 or FAQ "Vì sao shop TikTok không ra đơn?".
  4. **Tối ưu sản phẩm TikTok Shop** → `/san-pham/de-xuat-va-thuc-thi` title / meta / H2, naming
     only what Juli actually writes (title, description) per SPEC; no claim it edits images.
  5. **ROI và ngân sách GMV Max** → **no page copy**: Juli does not run ads, and an AI tool must
     not read it as an ads manager. Blog-only, later (DEBT).
  ISV truth rules (D42, D46) hold: TMĐT-first positioning, "hiện kết nối TikTok Shop, Shopee đang
  tích hợp", no Lazada / Tiki, no invented numbers, no "—" in visible copy. Also fixes the `/terms`
  meta description, which still said "kết nối TikTok Shop và Shopee" (terms 2.1 says Shopee is in
  progress). Blog drafts stay drafts (owner approves posts). Implemented in P39.
- **D48 additions** (owner, 2026-10-16, after the Semrush Site Audit of app-juli.com, crawl
  2026-10-16 12:50, 18 pages, Site Health 91 %, ships in the same deploy as P39):
  1. **AI tiêu đề / mô tả section** on `/san-pham/de-xuat-va-thuc-thi` (competitor research:
     Sapo help ranks #3 for "viết mô tả sản phẩm shopee bằng AI"; FastMoss has an AI title tool):
     Juli drafts the title and description, writes them only after the seller approves, measures at
     day 7 / 14. No claim beyond SPEC.
  2. **Structured data error** (4 pages): `SoftwareApplication` on `/san-pham` and the three
     capability pages fails Google's required `aggregateRating` or `review`. Juli has no real
     reviews (D43.3), so ratings are **never** invented: switch the type (e.g. `Service` with
     provider + offers on `/san-pham`, capability pages reference it by `@id`), keep Organization,
     WebSite, BreadcrumbList, FAQPage.
  3. **Broken internal links / 4XX** (13 links, 1 URL): Cloudflare Email Address Obfuscation
     rewrites every `mailto:` into `/cdn-cgi/l/email-protection` (404 without JS). Fix is a
     Cloudflare setting for app-juli.com (owner action, not code).
  4. **`/llms.txt`** (notice, 404 today): add a short Vietnamese llms.txt listing the public pages.
  5. Not fixed, with reason: low text-HTML ratio (Next.js payload, not thin copy); low word count
     on `/blog` (grows as posts are published), `/contact`, `/dang-ky` (task pages); `/privacy`
     long paragraphs (legal text must stay in sync with the md and contract, juli legal sync).
  6. **Three new blog posts, in Vietnamese** (no English body text; TikTok's own Vietnamese metric
     labels such as CTR, CTOR, AOV stay as TikTok writes them), status `draft` until the owner
     approves: "GMV là gì" (Semrush VN 4,400/month, KD 21), "TikTok Shop không ra đơn", "Doanh thu
     TikTok Shop giảm: checklist". Branch `fasttrack/p39b-blog` (P39-B).
  7. **Inline images in blog posts** (owner, 2026-10-16: "Thêm hình"), starting with the three
     P39-B drafts. The body renderer gains a figure block (responsive avif/webp, width/height,
     Vietnamese alt and caption, lazy-loaded, never the LCP). Images are either real Juli
     screenshots on the sample shop captioned "Dữ liệu mẫu" (reuse `public/media/cap-*`) or
     diagrams built as HTML/SVG like the covers (GMV funnel, five traffic sources, checklists);
     any number in a diagram is labelled "Ví dụ giả định". No stock photos, no TikTok or Shopee
     screenshots or logos. P39-C, branch `fasttrack/p39c-blog-images`.
  8. **More images** (owner, 2026-10-16) in `tiktok-shop-khong-ra-don` and
     `doanh-thu-tiktok-shop-giam`: three more figures each, in the H2 sections that have none yet,
     same rules as item 7. P39-D, branch `fasttrack/p39d-more-figures`.

- **D49** — Search-led tools content and a free GMV calculator (owner, 2026-10-16). Backlinks:
  owner checked, no problem, no disavow.
  1. **GMV calculator** at `/cong-cu/tinh-gmv` (P43): runs in the browser, no sign-in, no data
     leaves the page, no tracking beyond the site's existing consent rules. Inputs Lượt hiển thị,
     CTR, CTOR, AOV (or Lượt nhấp / Đơn hàng), shows GMV, the weakest step and what +X % on each
     step does to GMV; numbers are the user's own, nothing invented. Links to the "GMV là gì"
     post and `/san-pham/phan-tich-shop`; indexable, in the sitemap and llms.txt; WebApplication
     schema is **not** used (needs ratings); `WebPage` + FAQ only.
  2. **Listicle posts that name competitors** (P44), drafts until the owner approves:
     a. "Phần mềm quản lý bán hàng đa kênh 2026" (KiotViet, Sapo, Nhanh.vn, BigSeller, Haravan,
        Pancake): **Juli not listed**, it is not in this category.
     b. "Công cụ phân tích TikTok Shop 2026" (La bàn dữ liệu, FastMoss, Kalodata and others found in
        research): Juli listed once, disclosed as our product, in its own-shop analysis niche.
     c. "Công cụ AI tạo ảnh, video sản phẩm cho nhà bán TikTok Shop" (e.g. Higgsfield, CapCut,
        Canva and others found in research): **no Juli mention** beyond the site byline.
     Rules: every vendor fact from the vendor's own public pages, dated "kiểm tra ngày …"; prices
     only where the vendor publishes them; no "tốt nhất" ranking without stated criteria; no
     rating/review schema, no invented scores, no negative claims we cannot source, names used
     only to identify the product (no logos or screenshots of their UI). The existing pillar post
     "Top công cụ cho nhà bán TikTok Shop 2026" becomes the hub that links to a–c, so the posts do
     not compete for the same query.

- **D50** — Brand identities and the keyword map (owner, 2026-10-17, after Semrush blog
  research on keyword strategy and brand / AI search). `fasttrack/keyword-map.md` is the source
  of truth: one fixed brand descriptor, six identities (stable, each carried by search words
  and proven by a page), one main keyword per URL, KD ≤ 30 ceiling while the domain is new,
  quarterly review (next 2027-01). Owner approved publishing batch 1:
  `gmv-la-gi-tiktok-shop` and `chi-so-tiktok-shop-ctr-ctor-aov` (2026-10-17). Research found
  llms.txt is unconfirmed by AI providers (kept, low priority) and no special schema is needed
  for AI Overviews; Organization `sameAs` and third-party mentions matter more.

- **D51** — Gate A for the usable simulation models (grill Q1–Q6, product owner, 2026-10-17).
  Context: juli-sim-pilot adopted a 16-step ML pipeline (owner, 2026-10-17); PIPELINE.md /
  CONTRACT.md exist only for v0.3 and the funnel simulator (with D36 as its click step); every
  existing number is validation; frozen once-only test sets are registered in
  `ml_pipeline/frozen_test.json` (`ml_guard.py`).
  1. **v0.3 Step 14 metric (Q1 A):** both ELPD (> best baseline by 2 SE → model usable as priors)
     and the D40.8 lever rule per lever (same sign, 90 % interval excludes 0), plus within-niche
     rank correlation of real sales as a plain companion.
  2. **FastMoss temporal test (Q2 A):** fit on the 2026-10-13 snapshot only, freeze, predict the
     snapshot-2 7-day sales from snapshot-2 inputs; score products in both snapshots and new
     products separately. Before the test the owner wants v0.3 and the funnel **re-run** on current
     data with the audit's fixes (in-fold selection, shop-group splits, figures, Gate B rationale),
     frozen at Gate C before snapshot 2 is opened.
  3. **Fujiwa test after 2026-10-08 (Q3 A):** products treated in a D34 group are excluded from
     their start date; only controls and untouched products are scored.
  4. **Funnel Step 14 metrics (Q4 A):** on new Fujiwa days — CTR Spearman and MAE vs the category
     median, quantity log-likelihood (1 / 2 / 3+); on D34 wave 1 — share of real effects inside the
     frozen 90 % interval, sign agreement, mean z.
  5. **D34 results are test first, training after (Q5 A):** each wave scores the frozen simulator
     once; only then may `reweight.py` / `meta.py` / `sim_calib.py` learn from it (delays the D45.5
     new-pack offset); later waves are new registered test sets.
  6. **Pre-registered predictions (Q6 A):** for each D34 group, one simulator run before the group
     ends is recorded (run id, commit, PRIORS_VERSION, predictions with 90 % intervals); only that
     prediction is scored; recording it is that wave's Gate C.

- **D52** — Ops shows an empirical-Bayes shrunk group lift next to the raw lift (owner,
  2026-10-17; fast track P45). Winner's-curse guard after Azevedo et al. 2019 ("Empirical Bayes
  Estimation of Treatment Effects with Many A/B Tests"): a group picked because its lift looks
  big is, on average, luckier than it is good.
  1. **What.** For each D34 group comparison (primary metric, the Ops-rule reading, all-channel
     AOV / items per order, card CTR): observed log-lift `y` and its SE, shrunk
     `w·y + (1 − w)·μ` with `w = τ² / (τ² + se²)`, plus a 90 % interval; stored in the verdict JSON
     next to the raw numbers (`primary.eb`).
  2. **Prior per lever type** (lever × metric × channel). With ≥ `group_eb_min_groups` (3) draws
     from measured groups of that lever across all shops (several groups of one shop are
     combined within the shop first, inverse-variance; the group being shrunk is left out):
     μ and τ by DerSimonian–Laird. Otherwise the default N(0, `group_eb_prior_sd`² = 0.15²) on the
     log-lift. Both tunable per shop in DiagTunables.
  3. **Cross-tenant read only in Ops**, through a SECURITY DEFINER function executable by
     `juli_ops` only; it returns verdict comparisons (no product rows), and only aggregate numbers
     (μ, τ, n draws) leave the backend. The stored verdict (written by the seller-scoped pipeline)
     always uses the default prior; the Ops groups page re-shrinks with the pooled prior when one
     exists and says which prior it used.
  4. **No change** to the verdict label, strength, the seller sentence ("Kết quả nhóm") or any
     seller route (D45 scope rule).

- **D53** — Gate A amendment for the simulation models: causal scope, data roles, metrics,
  objective (owner, 2026-10-17; amends D51).
  1. **Estimand:** the effect of a content change (title, description, images, price
     presentation, pack options) on per-impression rates (stop, CTR, CTOR, items per order,
     GMV per impression), holding social proof (sold, review count, stars) and exposure (rank,
     position) fixed. Causal loop recorded: sales → reviews → rank → impressions → sales, and
     sold / stars shown on the card → CTR. Cross-section content coefficients are biased by
     selection on rank (only search pages 1–3 were collected — a collider) and are weak priors only;
     content-effect evidence comes from within-product D34 tests.
  2. **Scope:** card-level simulation applies to products that are seen (tier A: enough card
     impressions to read a test within 4 weeks, or pages 1–2 for the main keyword; TikTok judged
     by real impressions per channel since most traffic is feed). Tier B (low visibility) gets
     visibility recommendations (keywords / title SEO, video / LIVE / affiliate traffic), tier C
     (almost no impressions) is monitored only. Thresholds are set from data at steps 9–12.
  3. **Data roles:** (1) ideas — de-identified review text and competitors' sales generate
     proposals; (2) priority — own sales / impressions set tier and expected GMV for test selection;
     (3) fixed context — pre-period sold / reviews as CUPED covariates and as the standardised
     context in the simulator; (4) outcome — new sales / reviews after a change. Rank is never a
     feature (tiering only). **Review text** may be a feature as a product-quality control, only
     from reviews dated before the prediction time and as shares (not counts). Hypotheses to test
     on current data: H1 — within a niche, rank is explained by review count and stars and review
     text adds nothing; H2 — time-cut review text predicts CTOR / sales beyond count and stars.
     NLP: PhoBERT run locally (owner, 2026-10-17).
  4. **Metrics:** no R² target. Use D51 metrics plus rank correlation ≥ 0.3 between predicted and
     real D34 effects (G13), 90 % interval coverage, and R² relative to the split-half noise
     ceiling for reporting only.
  5. **Objective:** for each segment, the simulator compares the original A with the change A* on
     the same page (same competitors B, C…, same position, same random numbers, plus "scroll
     past"); Score = Σ_segments share × E_page[P(click) × CTOR × AOV] = expected GMV per
     impression, compared with a 90 % interval; results reported per segment. A per-segment
     guardrail (warn when A* clearly lowers a large segment) is decided **after looking at the
     data** (segment shares and simulator noise), proposed at Gate B. "A/A" keeps its meaning (two
     identical arms); "A vs A*" is a real test. The real D34 test measures the product's absolute
     metrics, not where clicks came from.

- **D54** — Gate B approved for v0.3 and the funnel simulator (owner, 2026-10-17). Approved as in
  each `ml_pipeline/GATE_B.md`: (1) v0.3 preprocessing `train` (training-fold medians) inside CV
  and `snapshot` for the temporal test; (2) funnel selection `infold` (y_rel centring, default
  levers, empirical-Bayes priors computed on training folds only); (3) step-10 candidates —
  hierarchical CTOR pooling, KG with feasibility / cost, rank-independent content score, exposure
  tiers A/B/C, KG on absolute expected GMV; (4) segment guardrail: a segment is large at ≥ 25 % of
  the product's simulated GMV, a drop is clear when the 90 % interval is below 0 and the median
  drop ≥ 5 %, warn only; (5) review text stays out of the main specs (H1/H2 found no added value
  on current data) and is kept for idea generation and a retry with more reviews. Next: steps
  9–12 on validation folds only, then Gate C before FastMoss snapshot 2 is opened.

- **D55** — Overnight $0 research findings adopted (owner, 2026-10-17: "đồng ý tất cả"; list in
  `~/juli-sim-pilot/research/overnight_findings_proposals.md`, items 1–12).
  1. **Ops (fast-track phase):** TikTok GMV includes cancelled and refunded orders (Seller University
     definition) — group-verdict AOV / revenue use net-of-cancel/refund values where the data has
     them, else the label says so; the Ops / chi-số guides state that TikTok's "conversion rate"
     (unique buyers / unique page views) is not Juli's CTOR, and that the product-card channel is the
     remainder after LIVE and video. Ops-only; the seller-facing sentence is unchanged unless a
     separate decision says otherwise.
  2. **Simulator / v0.3 (step 7–8 changes, a new candidate configuration PRIORS_VERSION
     2026-10-17c evaluated on validation next to the D54 configuration before Gate C; Rerun log
     entries required; nothing fitted on frozen data):** exposure tiers by channel; SPS and the share
     of 1–2★ reviews as context variables (not levers) with H1 re-tested as a threshold effect;
     FastMoss creator / video counts tagged leakage-risk; price-banner prior narrowed to a small causal
     effect (log 0.02–0.20); pack options kept conservative (mix shift, not new demand; offset −1 kept);
     free-ship and social-proof priors confirmed as they are; stop-step priors replaced by the
     intent × position ranges of `stop_step_evidence.md`; spend-archetype shares narrowed around
     Cimigo 2025 leaving room for 45+.

  **D55.1 implementation note (P47, 2026-10-17, branch `fasttrack/gmv-net`).** Data check: the
  daily product analytics rows every group verdict reads (`analytics_performance_intervals`:
  `gmv`, `sku_orders`, `items_sold`) carry no cancel / refund field (the mapper drops A-34
  `total_performance.refunds` and A-33 `cancel_and_refunds`), but the shop's own orders are
  polled each cycle: `silver.orders` (`status`, `tiktok_created_at`), `order_items` (product,
  quantity, `line_total`) and `silver.returns` (`refund_amount`, `status`). So net values are
  derivable: `services/action_cards/group_net.py` turns them into per product-day shares of
  orders / units / value cancelled or refunded (order day in shop time; a refund counts against
  its order's day; partial refunds remove only their amount) and scales the analytics day by
  them (shares, not order sums, because `order_items` keeps one row per order × SKU). Used only
  when the shop's orders span days −42 … 13 of the group; otherwise TikTok's GMV, labelled. Net
  feeds all-channel AOV and items per order in `verdict.metrics`, an Ops group's primary, the
  false-alarm replay, the guard text and the EB lift, each with the TikTok-GMV reading under
  `gross`; a card group's primary (the seller's "Kết quả nhóm") stays on TikTok's GMV and its
  net reading is `verdict.net` (Ops only). Ops shows "… (đã trừ huỷ/hoàn)" with "… (gồm đơn
  huỷ/hoàn, theo TikTok)" beside it, and "Doanh thu (đã trừ huỷ/hoàn)" vs "GMV TikTok (gồm
  huỷ/hoàn)" for the 14 days before launch. The Ops chi-số guide §5.5 adds the three TikTok
  definition notes (GMV incl. cancel / refund; TikTok "conversion rate" ≠ CTOR; Thẻ sản phẩm is
  the remainder after LIVE and video). Seller copy and the seller guide unchanged; no migration.
  Open points in DEBT (P47).

- **D56** — Continuous SEO blog plan (grill G1–G7, owner, 2026-10-17; `grill-content-plan.md`).
  The plan and its rules are `fasttrack/content-plan.md`: competitors in three rings (direct ones
  named only in comparison posts and never linked; no chatbot / "AI chốt đơn" listicles);
  primary sources cited with title + link, competitor pages by name and date without a link;
  posts framed from seller pain points plus a TMĐT-changes track; 3–4 drafts a week in month 1,
  published gradually by the owner; length by intent (the 3,000-word floor is dropped except for
  pillar / comparison posts); weekly automated Search Console report and an 8-week review per
  post; brand signals (G7) deferred. Work: P46-A (source-link and length rules in code, weekly
  report), P46-B… (month-1 posts).

- **D57** — D34 for now: no group test; independent tests with a synthetic control (owner,
  2026-10-18; Gate C question (d), option B). Group tests wait until the shop is ready (the only
  readable tier-A picks are pack options, which the owner deferred). Meanwhile every content change a
  seller approves through a card (title, description, cover) is treated as an **independent test**:
  a prediction is registered before the change (D51.6), the product is compared with untouched
  products of the same shop / niche over the same days plus the CUPED pre-period adjustment, the
  result is labelled "Tham khảo" in Ops while its interval is wider than the drift floor, and
  results of the same lever type are pooled across products and shops by empirical Bayes (D52,
  `meta.py`). Step 14 for the simulator's lever effects therefore scores these pooled independent
  tests instead of a D34 wave, once enough exist. Gate C itself is not yet approved — the owner wants
  further optimisation before the FastMoss snapshot-2 freeze (~2026-10-20).

- **D58** — Rules for the no-new-data optimisation round before Gate C (grill P1–P6, owner,
  2026-10-18; method: identify a specific weakness from evidence → change one factor → test against
  pre-set criteria → record and decide).
  1. **Order (P1 A):** W6 cleaning-rule bias → W1 Shopee within-niche ranking (Spearman ≈ 0) → W3
     Fujiwa panel CTR / CTOR losing to its baseline + over-wide intervals → W5 interval calibration of
     the other funnel steps → W2 FastMoss within-niche ≈ baseline. W4 (per-product CTOR has no
     signal) is a data limit and is skipped. Weaknesses are listed in each `ml_pipeline/WEAKNESSES.md`.
  2. **Acceptance (P2 A):** accept only if the primary metric improves by > 2 shop-clustered SE, no
     secondary metric (within-niche Spearman, MAE, 90 % coverage kept within 85–95 %) worsens by
     > 1 SE, and the role / leakage checks and tests pass; 1–2 SE → experimental (flag, off by
     default); < 1 SE or a rule violation → revert.
  3. **One factor (P3 A + owner addition):** each experiment changes exactly one factor of one kind
     (cleaning rule / feature / prior / preprocessing / model structure); ≤ 3 tries per weakness,
     chosen by inner CV and reported once on outer folds; an accepted change becomes the new baseline
     (sequential, never bundled). If a factor is not accepted, another factor may be tried for the
     same weakness (within the 3 tries), and a rejected factor may be retried once for another
     weakness if there is a reason it fixes it (logged "retry from W_x").
  4. **Validation wear (P4 A):** one of the five shop folds (hash-fixed, fingerprinted) is held out as
     a development-test fold; the round uses the other four; at the end the final configuration vs
     the D54 / 17c starting point is scored once on that fold — gains that do not hold there are
     treated as overfit and dropped. It does not replace the frozen final test sets.
  5. **Decisions (P5 A):** accept / experimental / revert, each a row in `runs.csv` and the
     "Nhật ký tối ưu" section of PIPELINE.md (weakness, factor, variant, commit, primary ± SE,
     secondaries, state, one-line reason); accepted changes are frozen only through Gate C.
  6. **Time box (P6 A):** deadline evening 2026-10-19, in the P1 order; unfinished weaknesses move to
     the next round; morning of 2026-10-20: score the development-test fold once and re-present Gate
     C; FastMoss snapshot 2 is frozen on arrival and scored only after Gate C.

- **D59** — Two tiers of blog content and a unique hero per post (owner, 2026-10-18; amends D56).
  1. **Low-level = reach** (search intent, top of funnel): `format` pain and news. **No mention of
     Juli** in body, FAQ, figures or meta; no Juli UI screenshots ("Dữ liệu mẫu" `cap-*`), no
     feature descriptions, no links to `/san-pham*`, `/ket-noi/*`, `/dang-ky` or the demo. The
     page's end-of-post CTA becomes a neutral box (free GMV calculator `/cong-cu/tinh-gmv`, related
     posts); site header and footer stay. Posts: the 13 pain posts (incl. pre-D56
     `tiktok-shop-khong-ra-don`, `doanh-thu-tiktok-shop-giam`) and the 3 news posts.
  2. **High-level = conversion**: Juli how-to / feature guides, "the specific problem Juli solves"
     posts, and TMĐT expertise pillars (`gmv-la-gi-tiktok-shop`, `chi-so-tiktok-shop-ctr-ctor-aov`,
     `toi-uu-the-san-pham-tiktok-shop`), the tools hub and the analytics-tools comparison. These
     may describe Juli and show its UI, within SPEC. New `format: "guide"` for Juli how-to posts.
     The two Juli-free comparison posts (đa kênh, AI ảnh/video) stay as they are.
  3. **Hero images**: every post gets its own hero, distinct in composition and colour, not a Juli
     UI and not a shared motif; rendered with a new still in `juli-content-engine`
     (Remotion, Be Vietnam Pro with the Vietnamese subset, site tokens), then converted into the
     landing cover variants (600 / 1200 at 16:9, OG 1200 × 630).
  Work: P48-A tiers in code + neutral CTA + tests; P48-B/C strip Juli from the reach posts;
  P48-H heroes (content engine + landing); then high-level guides (P49).
- **D59 additions** (owner, 2026-10-18):
  4. **Reach → conversion link only in the end-of-post box.** Reach post bodies never link to a
     Juli page or a Juli guide. Once the matching guide exists, the neutral end-of-post box gets
     one secondary line "Đọc hướng dẫn liên quan" to that guide, with no "Juli" in its text; each
     reach post maps to one guide (P49).
  5. **Conversion posts (P49)**, eight: guides `huong-dan-ket-noi-tiktok-shop-voi-juli`,
     `doc-phan-tich-tiktok-shop-theo-luong-truy-cap`, `duyet-de-xuat-toi-uu-san-pham-tiktok-shop`,
     `do-ket-qua-ngay-7-ngay-14-hoan-tac`, `dung-thu-juli-ai-mien-phi-3-thang`; problem posts
     `tim-san-pham-keo-gmv-xuong-tiktok-shop`, `ctr-the-san-pham-thap-doi-tieu-de-anh-bia`,
     `ctor-thap-viet-lai-mo-ta-san-pham`. Facts follow the newest decisions where SPEC lags
     (quick scan 14 days / reading 60 days / history to 180 days, card limits per D24.17 and
     D25.12); cover photos only with the seller's photo (D13); nothing about control groups
     (D34), simulation (D35/D45) or the AOV lever, which are not live; competitor-price reasons
     only as optional (D22). Before writing, fresh sample-shop screenshots replace the outdated
     `cap-kn-dang-nhap`, `cap-kn-quet-nhanh`, `cap-pt-nghen`, `cap-dx-the`, `cap-dl-ngay-7`,
     `cap-pt-lich-sale`, and add a cover-photo card, a CTR card, a day-14 final label and the
     current sign-in screen (P49-S).

- **D59** — Gate C approved for v0.3 and the funnel simulator (owner, 2026-10-18), after the D58
  no-new-data round (no factor accepted; dev-test fold confirmed the starting configuration).
  Frozen: v0.3 config c (no `log_creators`), preprocessing `train` in CV / `snapshot` for the
  temporal test, panel primary = category-rate baseline, panel priors pinned to run
  `20261013-134400-v02`, `price_gift` dropped, D58.1 definitions (median point metrics,
  expected-sign lever rule, pre-registered persistence baseline); funnel PRIORS_VERSION 2026-10-17c,
  inner-fold calibrated CTR interval, selection `infold`, CTOR pooling recorded only, quantity
  report-only, D34 replaced by independent tests (D57). Step 14 runs once per frozen set through
  `ml_guard.final_test`: FastMoss snapshot 2 (~2026-10-20), Ory new-shop set, Fujiwa after
  2026-10-08, pooled independent tests when enough exist. Metric.vn and FastMoss snapshot 2 feed
  the next optimisation round only after Step 14.

- **D68** — Legal terms and data rules after the PDPL grill (owner, 2026-10-18). Research: Viettel AI
  and FPT (FPT Shop, FPT IS) privacy texts, Luật 91/2025/QH15, Nghị định 356/2025/NĐ-CP, Luật Trí tuệ
  nhân tạo 134/2025, Luật BVQLNTD 19/2023 Điều 25, BLDS 2015 Điều 405.
  1. **Customer is B2B only**: businesses, household businesses and sellers using Juli for commercial
     purposes; /terms says they are not consumers (keeps Juli outside Luật BVQLNTD Điều 25).
  2. **Improving Juli's models is a condition of use**, on de-identified data only: business data and
     seller data are de-identified before any analysis/training pipeline; identifiable personal data is
     never used for training; buyer data is never used for training and is anonymised before entering
     any pipeline. Google user data stays excluded (Limited Use). Replaces the P42 opt-out
     ("yêu cầu ngừng sử dụng… bất kỳ lúc nào") and the "chỉ ở dạng cấu trúc" limit.
  3. **Ownership**: customer data belongs to the seller; Juli holds a perpetual, irrevocable licence to
     de-identified data; models, weights and aggregates are Juli's; on deletion raw data is deleted and
     models are not retrained.
  4. **Liability: total exemption** ("không chịu trách nhiệm bồi thường dưới bất kỳ hình thức nào… dù
     trực tiếp hay gián tiếp"), enumerated losses, "kể cả khi đã được thông báo", a **separately
     accepted** clause, plus severability. Owner accepted the BLDS Điều 405.3 risk (a court may void a
     standard-form exemption); counsel to confirm.
  5. **Juli terminates only for listed breaches**; may change or retire single features with notice;
     whole-service discontinuation keeps 30 days' notice.
  6. **Rights**: in-app Cài đặt → Quyền riêng tư plus e-mail; reply within 2 working days; withdraw /
     restrict / object done within 15 days; access / correct / export 10 days; delete 20 days (NĐ 356
     Điều 5). Opt-outs: marketing, ad measurement, shop-as-case-study (opt-in).
  7. Cross-border: disclosure only; no server locations on the page.
  8. **Changes**: 15 days' notice by e-mail and in-app; continued use = acceptance. The D68 text itself
     takes effect **immediately** (owner), shown with an in-app re-acceptance strip.
  9. Disputes: negotiate 30 days, then the court where Juli is headquartered; Vietnamese law.
  10. **Retention**: after a seller stops using Juli (account deletion requested), 30 days to export,
      then deletion; invoices 10 years.
  11. Citations: Luật 91/2025/QH15 + Nghị định 356/2025/NĐ-CP (NĐ 13/2023 replaced 01/01/2026).
  12. Paid fees are never refunded.
  13. Pages show the date only, no version number.
  14. Scope: **website only** (/terms VI, /privacy VI + EN); the md v2 sources and the Ory contract are
      not touched (DEBT); the contract still prevails for the pilot shop.
  15. E-mail notices use the existing SMTP mailer (`services/ops/mailer.py`); Resend, the owner's
      pick when told no mailer existed, is deferred (DEBT).
