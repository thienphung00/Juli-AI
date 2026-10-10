# Progress

Status: `todo` / `doing` / `done` / `blocked`. Owner = who's on it.

## P0 — setup

| Task | ACs | Status | Owner |
|---|---|---|---|
| Cut branch + worktree | 0.1 | done | orchestrator |
| Write fasttrack/ docs | 0.2 | done | orchestrator |
| Disable edit hooks + executor-cache pre-commit gate | 0.3 | done | owner |
| `check.sh` + manual deploy workflow | 0.4, 0.5 | done (dispatch caveat) | P0 agent (Opus) |
| Close Dependabot PRs | 0.6 | done | orchestrator |

## P1 — data layer

| Task | ACs | Status | Owner |
|---|---|---|---|
| P1-A Mapper fixes (analytics breakdowns, CVR, price, category) + migration | 1.8, 1.9 | done | P1-A agent (Sonnet) |
| P1-B Bootstrap on connect, per-shop schedule, cadence split, date-range backfill, parallel calls, latency events | 1.1–1.7, 1.10, 1.12 | done | P1-B agent (Opus) |
| P1 integration: merge A + B, full test pass, check.sh | 1.11 | done | orchestrator |

## P7 — Quyết định + Phân tích on the demo (D21)

| Task | ACs | Status | Owner |
|---|---|---|---|
| Sync main (ADR-106/108 code) into the branch | — | done (7c31a0a4) | orchestrator |
| P7-A Phân tích backend: daily shop diagnosis report per shop + `/v1/demo/analysis` | 7.1, 7.2 | done (6a8e2324) | P7-A agent (Opus) |
| P7-B Quyết định backend: ADR-106 Optimize Product cards per shop | 7.3, 7.4 | done (df673ced) | P7-B agent (Opus) |
| P7-C UI restyle to index.html + Quyết định / Phân tích screens | 7.5–7.8 | done (8a857b04) | P7-C agent (Opus) |
| P7-D Deploy builds the demo lane | 7.9 | done (d76e11bf) | P7-D agent (Sonnet) |
| P7 integration: merge A–D, align UI to P7-B, funnel layout, repay P7-A lock + rate-limit debt, full test pass, check.sh | — | done (c446bb2d..HEAD; e2e: 8 restyle failures open in DEBT) | P7 integration agent (Opus) |

## P8 — the app follows the sales demo video (ADR-109)

| Task | ACs | Status | Owner |
|---|---|---|---|
| P8-A Rankings job, DB only, read on demand | 8.1 | done (merged d7e0e19f) | P8-A agent (Opus) |
| P8-B Per-video 30/30 data | 8.2 | done (merged 2abcd168) | P8-B agent (Opus) |
| P8-C Before/after + Hoàn tác, rule store, day-7 guardrail | 8.3 | done (merged 06a95d38, 078 re-chained onto 077) | P8-C agent (Opus) |
| P8-G `get_product_diagnoses` playbook tool | 8.4 | done (merged f4740ceb) | P8-G agent (Sonnet) |
| P8-D App shell + Home | 8.5 | done (merged 41584c55) | P8-D agent (Opus) |
| P8-E Phân tích UI | 8.6 | done (merged) | P8-E agent (Opus) |
| P8-F Quyết định UI | 8.7 | done (merged 8e873ffc) | P8-F agent (Opus) |
| P8 integration + deploy | — | doing (verified; awaiting deploy tag) | orchestrator |

## P9 — seller access

| Task | ACs | Status | Owner |
|---|---|---|---|
| P9-A Email sign-in (OTP code / magic link) beside Google | 9.1 | doing | P9-A agent (Opus) |
| P9-B Hand a shop connected by the Juli team over to the seller's own Juli account (invite / transfer) | 9.2 | todo — needs a grill | — |

## P10 — Quyết định card and flows, 100 % to the approved design (ADR-109 Amendment 1)

| Task | ACs | Status | Owner |
|---|---|---|---|
| P10-A Card payload, reasons + 7-day cooldown, consent edits | 10.1 | done (merged 6bac0366) | P10-A agent (Opus) |
| P10-B Cover-image flow, promotion flow, measurement endpoint | 10.2 | done (merged d45313fa) | P10-B agent (Opus) |
| P10-C UI to the artboards in docs/product/design/quyet-dinh-flows | 10.3 | done (merged e42a9568) | P10-C agent (Opus) |
| P10 integration (wiring 8ba4e9ff, 9849f24a; contract f54ada3b, 0aaba190; guards 90aec127) | — | done — deploy is the owner's | integration agent (Opus) |

## P11 — signed-out sample and lasting sign-in

| Task | ACs | Status | Owner |
|---|---|---|---|
| P11 Signed-out Quyết định = P10 design over sample fixtures (no network); sign-in in localStorage | — | done on `fasttrack/p11-sample-mode` (not merged, not deployed) | P11 agent (Opus) |

## P12 — Phân tích redesign to the approved artboards (ADR-109 Amendment 2)

| Task | ACs | Status | Owner |
|---|---|---|---|
| P12 backend additive fields (report `daily_gmv`, `seller_skus`, `promo_products`, `Band.product_count`; ranking rows `seller_sku`, `product_ids`) — contract `contracts/p12-phan-tich.md`, no migration | 12.1 | done on `fasttrack/p12-phan-tich` (not merged, not deployed) | P12 agent (Opus) |
| P12 UI: streams, cells, ranking, rows, Khuyến mãi / Lịch sale, Nội dung, mobile, LinkA | 12.2 | done on `fasttrack/p12-phan-tich` | P12 agent (Opus) |
| P12 two-way links Phân tích ↔ Đề xuất (`the=`, `nhom=`, "Xem phân tích ›") | 12.3 | done on `fasttrack/p12-phan-tich` | P12 agent (Opus) |
| P12 signed-out sample = the Quyết định sample's shop, no network | 12.4 | done on `fasttrack/p12-phan-tich` | P12 agent (Opus) |

## P13 — signed in without a shop sees the sample; one sample shop everywhere

| Task | ACs | Status | Owner |
|---|---|---|---|
| P13 no-shop → sample + "Kết nối TikTok Shop ›" strip on Trang chủ / Phân tích / Quyết định; Home sample = the cosmetics shop; Phân tích header left-aligned; reason-box debt accepted | 13.1–13.4 | done on `fasttrack/p13-no-shop-sample` (not merged, not deployed) | P13 agent (Opus) |

## P14 — recommendation pipeline (D24)

### P14-C/F — cost data and rule fields for what TikTok does not give us

| Task | ACs | Status | Owner |
|---|---|---|---|
| P14-C price detail + finance transactions per order, read-only (D24.13): client + allowlist, migration `081_order_cost_data` (3 tables, RLS), bounded rate-limited step in `run_shop_cycle`, `sku_deductions` accessor — contract `contracts/p14-rules-and-cost.md` | 14.C1–14.C3 | done on `fasttrack/p14-data` (not merged, not deployed) | P14-C/F agent (Opus) |
| P14-F rule fields Juli cannot read from TikTok (giá vốn SKU, biên LN gộp mặc định, trần giảm giá shop, phí chương trình, chiến dịch sàn + ghi chú, ROAS mục tiêu, ngân sách GMV Max, khung giờ LIVE): store + validation + GET/PUT, typed `shop_economics` accessor, demo rules editor (sample read-only) | 14.F1–14.F3 | done on `fasttrack/p14-data` (not merged, not deployed) | P14-C/F agent (Opus) |

### P14-A/B/D — card limits, learning, "Hành động" (D24.17, D24.6, D24.2)

| Task | ACs | Status | Owner |
|---|---|---|---|
| P14-A card limits: 5 new/day, 25/week, 30 open; first-day executor mix; 7-day validity → `expired` + 7-day return; 3-day stay; top 30 nightly | 14.1–14.5 | done on `fasttrack/p14-cards` (not merged, not deployed) | P14 agent (Opus) |
| P14-B ranking × calibration factor × seller-reason penalty; `adjusted_by_history` | 14.6 | done on `fasttrack/p14-cards` | P14 agent (Opus) |
| P14-D "Đòn bẩy" → "Hành động" in demo UI copy and design canvas | 14.7 | done on `fasttrack/p14-cards` | P14 agent (Opus) |

### P14-E — "Juli soạn · bạn làm" content cards (D24.4, D24.17–D24.19)

| Task | ACs | Status | Owner |
|---|---|---|---|
| Contract `contracts/p14-content-cards.md`; artboards ContentCards / ContentRun copied to `docs/product/design/quyet-dinh-flows/` | 14E.1 | done (b668231c) | P14-E agent (Opus) |
| Backend: candidates from `metric_rankings` (video CTR / LIVE CTOR), nightly emission (7-day validity + cooldown, ≤ 5 new/week, 3-day stay, reason cooldown), card block, content run (reads → ONE `gpt-5.4-nano` structured-output call → choice → publish → detect), seller routes, poll beat, measurement + calibration; no migration | 14E.2–14E.5 | done on `fasttrack/p14-content` (2f7692b3 + follow-up; not merged, not deployed) | P14-E agent (Opus) |
| UI: content card variant, content group, `content-run-panel`, client calls, signed-out / no-shop sample (MN-015 video, SM-012 LIVE, canned scripts) | 14E.5 | done on `fasttrack/p14-content` (1534786b) | P14-E agent (Opus, UI fork) |
| Emission budget counts content cards for the day-1 content slot | 14.2 | done on `fasttrack/p14-integration` (aace1159): budget `CONTENT_WORKFLOW_KEYS` = P14-E's `content_video` / `content_live`, payload `card_executor: "juli_drafts"` claims the slot; a budget-expired content card keeps its 7-day return | integration agent (Opus) |

### P14 integrated

| Task | ACs | Status | Owner |
|---|---|---|---|
| P14 integrated: `fasttrack/p14-data` + `fasttrack/p14-cards` + `fasttrack/p14-content` merged (in that order, `--no-ff`) on `fasttrack/p14-integration` from ddef3245; content cards obey the D24.17 limits / validity / 3-day stay with P14-E's ≤ 5/week as a sub-limit; head `081_order_cost_data`, deferred phone cleanup last; full suites + `check.sh --since ddef3245` green (see LOG) | 14.1–14.7, 14.C1–14.F3, 14E.1–14E.5 | done on `fasttrack/p14-integration` (not merged into `fasttrack/optimize-product`, not deployed) | integration agent (Opus) |
| D24.21 owner choices on `fasttrack/p14-integration` (merged 3836bf2a docs): strict 7-day return after Từ chối / Không thực hiện / Hoàn tác for Optimize, content and legacy cards; "Số thẻ mở cùng lúc" 5–30 (default 30); fixed daily slots 3 Juli / 1 Seller Center / 1 content, empty slot stays empty, every day; "Giọng văn" / "Từ không được dùng" rules read by content runs and enforced on listing writes; content ≤ 5/week in the shop week; 081 grants trimmed; full suites + `check.sh --since 3836bf2a` green (see LOG) | 14.R1–14.R6 | done on `fasttrack/p14-integration` (not merged, not deployed) | integration agent (Opus) |

## P17 — onboarding speed (D26, D25.12, P14-C pacing)

| Task | ACs | Status | Owner |
|---|---|---|---|
| Contract `contracts/p17-onboarding-speed.md` | — | done (81f3b543) | P17 agent (Opus) |
| 429 in the daily diagnosis: jittered capped backoff, skip the video tables (no whole-window fallback), skip counter | 17.5 | done (e40a5634) | P17 agent (Opus) |
| Faster cost reads: orders of the last 30 days up to 60 / pass / cycle, waiting for the rate-limit window (≤ 600 s); older at 10 | 17.6 | done (58b225d5) | P17 agent (Opus) |
| Migration `084_onboarding_speed` (5 nullable columns on `shop_ingestion_state`, after 081 here; re-chain after 083) | 17.7 | done (2ed5e4c0) | P17 agent (Opus) |
| Quick scan (D26): `shop_quick_scan` on `ingest_priority` beside the fast phase; 14-day A-34 + TikTok diagnoses → 1–3 cover/title/description cards, D22 on 14 days, "Đề xuất nhanh · dựa trên 14 ngày" / "Tham khảo", day-1 Juli slots; full run re-scores same-lever quick cards in place, withdraws the rest | 17.1, 17.2 | done (74aefe3c, 55d9aeec) | P17 agent (Opus) |
| `GET /v1/shops/me/onboarding` (3 steps, percent / ETA, `history_days_available` for P16) | 17.3 | done (74aefe3c) | P17 agent (Opus) |
| History to 180 days (D25.12): look-back 180; connect chain stops at 60 days; nightly `shop-history-extend` 2 × 15 days, resumable, per-shop lock | 17.4 | done (74aefe3c) | P17 agent (Opus) |
| Demo: onboarding strip on Trang chủ / Quyết định / Phân tích, 15 s poll while active, cards re-read; quick-card chip + "Độ tin cậy: Tham khảo" | 17.8 | done (60f89874, dd52f8b5) | P17 agent (Opus, UI fork) |
| Two-tenant proof on PG16, guards (surface inventory, beat set, quality corpus, import boundaries, MODULE.md) | 17.7 | done (336122aa, 9214acc8, 4549b98a) | P17 agent (Opus) |

Branch `fasttrack/p17-onboarding-speed` from 09960b20 — not merged, not deployed.

## P2–P6

Not started. See SPEC §4. P3 no longer waits on FastMoss (D22): next after P7. P2 (FastMoss) is optional and still waits on the API trial (owner).

## Owner actions (not for agents)

- FastMoss REST API trial + 1,000-request minimum (P2, optional since D22).
- Confirm Fujiwa's TikTok authorisation allows product writes (blocks P5).
- Consent screen #2061 (launch, not this branch).
- Dependabot keeps reopening PRs because its config is read from `main`
  (frozen). Either accept periodic closes, or allow a one-line change on `main`
  setting `open-pull-requests-limit: 0`.
