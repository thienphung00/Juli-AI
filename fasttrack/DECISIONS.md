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
