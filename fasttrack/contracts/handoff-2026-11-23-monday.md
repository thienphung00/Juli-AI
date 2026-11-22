# Monday 23/11 hand-off — Juli tab, keywords + reviews, Connector sync, Excel

Written 22/11 by the Claude session that built the Juli tab (#2341, #2344, #2346, #2347), for the owner's Cursor
agent. **This file is the whole brief: the agent cannot read the owner's local notes.** The repo is public — no client
names, shop ids, product ids or sales numbers in code, commits, PR text or this file. "Pilot shop A" = the Shopee pilot
shop; "pilot shop B" = the TikTok pilot shop.

## 0. Rules (read first)

- Process: `fasttrack/PIPELINE.md` (fast-track) — batch branch from `origin/fasttrack/optimize-product`, shared state
  `python3 fasttrack/state.py check --session <you> --branch <batch>` before every push, `state.py claim-migration N`
  before writing a migration (head today: `138_juli_agent_spend`; next free number: check `state.py show`).
- **Grill before building** (owner rule): restate every domain term + in/out scope in 3–5 bullets, wait for the owner's
  OK. Terms: `fasttrack/GLOSSARY.md` (Juli-tab terms were added 20/11: chain, stop reason, within_noise, draft card, Jev).
- **Ask before any paid run** (LLM / Jev / eval) with what + estimated $. Ask before any production write or browser use.
- Owner merges PRs and pushes deploy tags (`fasttrack/bin/tag-deploy.sh <full sha> --session <you> --push`).
- Tests: TDD; never weaken a test; no new `noqa` / `type: ignore` (the suppression ratchet `tests/unit/test_ratchets.py`
  fails CI); new test modules move the test-quality count — run `python -m eval.quality_detectors reconcile --write`.
  A Postgres-only bug will not show locally without a DB: the PR gate (`fasttrack-pr.yml`, five jobs) runs them.
- Frontend: run `eslint .` + `tsc --noEmit` + vitest (`NODE_OPTIONS=--no-webstorage`) in `apps/demo` before pushing.
- Everything automatic (owner): no manual steps, no shop ids in code or config — features work for every shop that
  connects by OAuth.

## 1. State on 22/11

| what | where |
|---|---|
| Juli tab (4th tab, both platforms), analytics agent, migrations 137 + 138 | live (#2341, hotfix #2344) |
| Thực hiện → Đo lường: imported cards skip read-back, deadline verdicts final, stale "Đối chiếu ngay" expires after 15 min, "Mở Seller Centre" opens the card's page, the Thực hiện list follows the tab rule | live (#2346); #2347 merged, tag pending |
| Title cards for a new product (bento box, single + combo) made by hand with Tự tạo → Connector fill → save → read-back → Đo lường | done 21/11, measuring until 05/12 |

Code map: engine `backend/src/juli_backend/services/analytics_agent/` (MODULE.md), API + storage
`services/juli_agent_api/` + `api/routes/juli_agent.py`, gate doors `services/llm_gate/vendors.py`, UI
`apps/demo/src/app/juli/`, `components/juli/`, `lib/juli/`, contracts `packages/contracts/src/juli-agent.ts`, ADR-123.

## 2. Workstreams (in priority order)

### W1 — Connector: daily sync first (owner priority)

Observed on pilot shop A (Connector 0.3.30 popup, 21/11): most readers end "Hết lượt đọc hôm nay"; "Phân Tích Bán Hàng ›
Truy cập" and "Quảng Cáo Shopee › từng chiến dịch nhóm" read but post only partly ("Seller Centre có thể đã đổi giao
diện"); "Đơn hàng › chi tiết từng đơn đã hoàn thành" opens but does not load; "Sản phẩm › Tất cả sản phẩm" has no result;
31-day backfill "0/31 · cần mở Seller Centre"; "Đăng nhập lại Phân tích bán hàng" blocks 4 datacenter readers.

Tasks:
1. **Budget**: `apps/connector/src/core/config.ts` — `DAILY_REQUEST_BUDGET = 800`, `TODAY_REQUEST_RESERVE = 250`,
   `BACKFILL_REQUEST_SHARE = 150`, `READER_PAGE_LOAD_COST = 10`. Proposed (owner to confirm in the grill): 1.500 /
   450 / 300. Risk: more CAPTCHA prompts (the Connector already stops and asks; never bypass).
2. **Stop wasting budget**: a reader that fails twice in a day waits until the next day
   (`apps/connector/src/platforms/shopee/background/scheduler.ts`, `READER_REREAD_MAX_PER_DAY`).
3. **Order of reads**: today's readers (incl. the 8 Tiếp Thị Liên Kết pages and Sản phẩm › Truy cập) before backfill days.
4. **Partial posts**: re-capture the two "partly sent" pages and fix the mappers; order-detail page not loading — find
   the wait condition.
5. **Product list reader** ("Sản phẩm › Tất cả sản phẩm" empty) — needed for variants and prices (W3).
6. Card sync Thực hiện → Đo lường: the steps are Đã duyệt · Connector điền · Bạn lưu · Khớp Seller Centre. After #2347
   check the live counts; a card waiting on read-back must get its verdict within the 48 h deadline
   (`services/card_events/verification.py`, beat task `card_change_verification`, 4× a day).
7. Ship as Connector 0.3.31 (manifest + build `node scripts/build.mjs`); the owner reloads the extension.

Known gaps outside the Connector, same area: `services/agent/abuse_limits.py` INCR/EXPIRE has no self-heal (copy the
fix in `services/juli_agent_api/reviewer_limits.py`); `api/routes/agent_runs.py` SSE slot not released when a stream is
never iterated (copy the `BackgroundTask(slot.release)` fix in `api/routes/juli_agent.py`).

### W2 — Keyword library + review text (owner decisions 21/11; grill first)

Decided:
- `CONNECTOR_MARKET_SEARCH` **always on**: flip the default in `services/ingest/market.py` `enabled()` (unset = on,
  `0` = off); keep `CONNECTOR_MARKET_SHOP_IDS` empty (= every shop).
- Market lane retention: `market_listing_snapshots` rolling **8 weeks**; `market_keyword_snapshots` aggregates kept
  forever. Build the prune as a scheduled job (no manual step).
- **Competitor reviews**: new Connector reader for public Shopee product pages (top listings of each main keyword):
  rating breakdown + latest N review texts, no buyer identity kept. New table(s) in the public market lane
  (`collector = extension`), migration needed.
- **shopeeanalytics.com** (no API, no export): read by the **Connector** from the owner's logged-in browser at human
  pace (pages: keyword tool `/vn/search/keyword?keyword=…` — volume, CPC, độ khó, cạnh tranh, cơ hội per keyword; market
  block per keyword). Never bypass a bot check. Check the site's terms first and record them in the grill log.
- **TikTok Shop**: same shared design, tailored source = FastMoss (production API, not the MCP).
- **Per-product template "Tối ưu từ khóa"** in the Juli tab (not a launch-only template): keyword scores → page-1
  competitors (price, rating, sold, title pattern) → review themes → 2–3 titles + one description via the existing
  `POST /builder/drafts/title|description` → one card with versions → seller sends to Đề xuất. Juli never edits listings.

Verified 21/11: the market-search reader exists (`apps/connector/src/platforms/shopee/market.ts`, page 1, relevancy,
1–3 keywords per product, weekly; endpoint "to verify on a real capture",
`docs/integrations/shopee/market-search-recon.md`) but **has never produced a row in production**. Do the first-capture
check (`fasttrack/contracts/p92-deploy-checklist.md` §5 step 3) before relying on it. Keyword seeds exist
(`shop_keyword_seeds`); there is **no search volume or score** anywhere in Juli yet — that is what shopeeanalytics.com
and Shopee Ads keyword suggestions add.

Manual run that proves the flow (21/11, pilot shop A, sugarcane-fibre bento box): the top keyword was the generic
material term (highest volume and opportunity), the square-shape variant second; page-1 competitors all name the use
("đựng bánh kem, bánh bento, hamburger"); reviews praise thickness/sturdiness and complain about boxes crushed in
shipping. Those three signals made the title. Encode that order in the template.

Grill agenda: which shopeeanalytics pages, cadence, layout-change detection; review fields, N, retention; one keyword
score formula (volume × relevance ÷ competition + review terms); where scores show (Dữ liệu shop › Từ khóa, product
page, Juli tab); storage across many shops (keywords are shared, one read per keyword per week).

### W3 — Builder bug: price cards on multi-variant products (blocker for price work)

Tự tạo › Giá bán + Flash sale on a product with several variations (e.g. Combo 20/30/40/50 hộp) shows **one row**
labelled with the first variation and its current price, but previews from **another variation's price** (the last /
largest). Saving a "−20 %" version would raise the first variation's price. Juli's catalogue (`platform_items`) has
every variation. Fix: one price row per variation, each with its own current price and its own new price / %;
the fill job writes each variation's price. Tests on a synthetic 4-variation product. Do not ship price cards for
multi-variant products until this is fixed.

Related: the builder shows "Chưa ước tính" / "Chưa ước tính được" — the owner banned "ước tính" on screens; replace the
wording (`apps/demo/src/components/shopee-decisions/`).

### W4 — Excel exports vs the owner's design

Design (4 groups): shop-level revenue, profit, costs and % of revenue vs last month and vs target; orders and AOV by
month; channels Organic / Ads / Affiliate share and efficiency; product/SKU share of revenue, profit and cost; growth and
decline with cause and fix; stock, sales speed, reorder; affiliate share and per-KOC revenue, orders, profit, trend,
best product, cost and efficiency; every group = actual → comparison → cause → action.

Gaps found in the Tổng quan export (`services/exports/tong_quan_xlsx.py`, `collect.py`):
1. "vs mục tiêu" is "—" when the shop has no Kế hoạch goal.
2. Theo kênh: GMV Quảng cáo is "—" (no ads attribution in traffic rows) → ads share and channel profit incomplete;
   Theo ngày channel columns all "—".
3. KOC sheet: no count of effective KOCs, no ROI per KOC, previous-period columns "—".
4. Phân tích & đề xuất: one row per card (49 rows for 8 issues) — dedupe to one row per issue listing its cards;
   "Dự kiến Δ" all "—".
5. Theo sản phẩm: no per-product cause / fix column.
Kế hoạch export: `SOURCE_LABELS` now includes "agent" → "Từ tab Juli" (#2344). "Lô 2" items still not built: a
"Nguồn dự đoán" column (dữ liệu shop / Juli / typical level — the owner picks the label replacing "ước tính"), Chi phí
dự kiến / thực tế / Hiệu quả (needs actual spend per card), ROAS Tùy chỉnh / chi phí mỗi đơn.

### W5 — Juli tab answer quality (from live template runs 20/11)

1. "Giảm chi phí" (`cost_change`) takes > 110 s on a real shop → ends "busy" at the 120 s run cap. Profile on the server;
   the chain now reads each scope once as a window pair — find the remaining slow reads.
2. No card version is marked `recommended` → the UI has no ★ preselected (`analytics_agent/cards.py`, Jev version
   choice).
3. Cost template text prints the ratio as "0 → 0" — format as %.
4. Margin answer blocks a card with "Đã có thẻ đang làm việc này" but no existing card code — show the card or do not
   block without one.
5. Shares above 100 % shown to sellers (parts moving in opposite directions) — show top parts in the same direction.
6. Two templates still fall back to the plain template after the numbers check — read `done.routing` writer step.
7. Screen chips: Juli-tab cards show nothing in seller Đề xuất and "Juli" in the Ops list — show "Từ tab Juli"
   (`components/shopee-decisions/top-cards.tsx`, `ops-list.tsx`).

### W6 — Platform knowledge (not urgent; grill)

Local corpus only, no live web search. TikTok corpus exists on the owner's machine (not in the repo); a Shopee Seller
Education corpus does not exist yet (pages are client-rendered: collect with a browser). Design: read-only knowledge
index (chunk + source URL + date), refreshed by a scheduled job, a new Juli-tab lookup kind that quotes the passage with
its link; Jev picks the passage from backend-retrieved candidates.

## 3. Owner questions to settle in the grill
1. Connector budget numbers (W1.1).
2. shopeeanalytics.com: pages, cadence, terms of use.
3. Review reader: fields, N per listing, retention.
4. Keyword score formula and where it shows.
5. Label replacing "ước tính" in Excel ("Nguồn dự đoán").
6. Whether a mismatched card in Đo lường should offer "Điền lại".
