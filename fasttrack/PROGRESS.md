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
| P9-B Hand a shop connected by the Juli team over to the seller's own Juli account (invite / transfer) | 9.2 | done in P16 (D25.7) on `fasttrack/p16-ops` (not merged, not deployed) | P16 agent (Opus) |

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

## P15 — content analysis of seller uploads (D24.19, D24.20; contract `contracts/p15-content-analysis.md`)

| Task | ACs | Status | Owner |
|---|---|---|---|
| Migration `082_content_analysis` (`content_analyses`, tenant_direct, RLS, juli_app S/I/U), upload slot + chunked PUT (signed `X-Upload-Token`, 32 MB chunks, resumable, first-box sniff, size/type/in-flight limits), list/get routes, temporary disk storage + 24 h sweep | 15.1, 15.2 | done on `fasttrack/p15-content-analysis` (not merged, not deployed) | P15 agent (Opus) |
| Pipeline on queue `content_analysis` (idempotent, per-shop lock, retries, cost per stage): ffprobe/ffmpeg (`-f mov`, file-only), ASR (`whisper-1`, vi, glossary, word timestamps), LIVE windows from ASR mentions (−2/+5 min, ≤ 3), cuts (port of `reference_analyze.py`), keyframes / 2 s, `gpt-5.4-nano` vision (on-screen text + product on screen), ONE structured-output scoring call; file deleted after | 15.3, 15.4 | done | P15 agent (Opus) |
| Monthly OpenAI cap per shop (default $5, `shop_rules.openai_monthly_cap_usd` override for P16) before every paid step and at upload | 15.5 | done | P15 agent (Opus) |
| Juli soạn reads the best / weakest analysed upload of the product (prompt v2) | 15.6 | done | P15 agent (Opus) |
| UI "Phân tích video" block in the content run and Phân tích › Nội dung row detail; sample = canned analysis, no network (no artboard — owner review) | 15.7 | done | P15 agent (Opus) |
| Ops: worker `-Q` + nginx chunk location + runbook `docs/runbooks/content-analysis-runbook.md` + env example | 15.8 | done; owner to install ffmpeg on the VPS before deploy | P15 agent (Opus) |

## P16 — Juli Ops, the internal console (D25) + P9-B

| Task | ACs | Status | Owner |
|---|---|---|---|
| Migration `083_ops_console` (role `juli_ops`, 5 ops tables, consent column, 3 DEFINER functions), staff / audit / overrides / scenarios / invites, overrides read by emission / content / OpenAI | 16.1, 16.2 | done on `fasttrack/p16-ops` (not merged, not deployed) | P16 agent (Opus) |
| `/v1/ops/*` API: Access JWT + staff role (fail closed), masking, overview, settings, Quy tắc (D25.14), runs, read-only view-as (D25.3 amended), simulation (D25.10–11), scenarios, invites + accept (P9-B), Huỷ kết nối (D25.13), permission status (D25.15) | 16.3–16.9 | done on `fasttrack/p16-ops` | P16 agent (Opus) |
| Ops pages in apps/demo on `ops.app-juli.com` (middleware host split, noindex): Tổng quan, Cài đặt shop, Xem như shop, Mô phỏng (**artboard not yet owner-reviewed — review requested**), Nhân viên, Nhật ký; seller `/nhan-shop`; reconnect strip | 16.10 | done on `fasttrack/p16-ops` | P16 agent (Opus) |
| Infra files + runbook (owner applies): nginx vhost, opt-in provisioning, env example, `docs/runbooks/ops-console-runbook.md` | 16.11 | done (files only) — owner steps pending | owner |
| Privacy: staff-access sentence (VN + EN) + connect-shop notice + consent timestamp | 16.12 | done on `fasttrack/p16-ops` | P16 agent (Opus) |
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

## P32 — Shopee ISV reviewer access (D42)

| Task | ACs | Status | Owner |
|---|---|---|---|
| P32-A Contract + reviewer access: password sign-in, reviewer role / expiry / provisioning, Fujiwa pin + mask, server-side write barrier, simulated Duyệt → Thực thi, audit, banner + UI | 32.1–32.8 | done, merged into `fasttrack/optimize-product` 2026-10-15 — not deployed; migration `090_reviewer_accounts` | P32-A agent (Opus) |
| P32-B Landing / privacy / terms: Shopee status in text (VN + EN) | 32.9 | done on branch `fasttrack/p32b-shopee-copy` (d5b1c276, 767e9797) — merged into `fasttrack/optimize-product` 2026-10-15, not deployed | P32-B agent (Sonnet) |
| P32-D D42 amendment (owner 2026-10-15): reviewer uses the sample shop; `REVIEWER_SHOP_ID` optional (unset → `/v1/reviewer/me` `shop: null`, no 503); demo sample mode with banner "dữ liệu mẫu", no connect strip, offline simulated Duyệt → Thực thi | 32.5, 32.7 | done on branch `fasttrack/p32d-reviewer-sample` (from f3c84b55) — not merged, not deployed | P32-D agent (Opus) |
| P32-E D42 amendment 2 (owner 2026-10-15): every seller feature usable as a labelled browser-side simulation for the reviewer in sample mode (Từ chối, run after Thực thi, consent edits, photo, Seller Center, content cards, Hoàn tác, Đo lường day 7 / 14, Quy tắc, Phân tích video, "Đặt lại dữ liệu mẫu"); only request `GET /v1/reviewer/me`; no backend change | 32.5, 32.7, 32.10 | done on branch `fasttrack/p32e-reviewer-all-features` (from 9d6352b3) — not merged, not deployed | P32-E agent (Opus) |
| P32-C Services Information text + reviewer steps | 32.10 | done — `fasttrack/shopee-isv-services-information.md` (sample shop per D42 amendment) | orchestrator |
| P32 integration + deploy + provision `shopee-review@app-juli.com` + resubmit | 32.11 | todo | orchestrator + owner |

## P33 — app-juli.com business site and indexing (D43)

| Task | ACs | Status | Owner |
|---|---|---|---|
| P33-A Technical SEO + shared helpers, redirects, demo/ops noindex, PageSpeed fixes | 33.1–33.4 | done on branch `fasttrack/p33a-seo-foundation` (875fb83b..HEAD, pushed) — not merged, not deployed; helper API in `apps/landing/src/lib/seo/README.md` | P33-A agent (Opus) |
| P33-B Homepage + `/san-pham` overview | 33.5, 33.6 | done on branch `fasttrack/p33b-homepage` (2f16f2eb..HEAD, pushed) — not merged, not deployed; links C/D pages, so integrate with C and D | P33-B agent (Opus) |
| P33-C Three capability pages + `/ket-noi/tiktok-shop` | 33.7 | done on branch `fasttrack/p33c-capabilities` (9f8a03b4..HEAD, pushed) — not merged, not deployed | P33-C agent (Opus) |
| P33-D Blog + 3 pillar drafts (owner approves) | 33.8 | done on branch `fasttrack/p33d-blog` (7ef53a7a..HEAD, pushed) — not merged; 3 drafts noindex, **owner approval pending** (`apps/landing/src/content/blog/README.md`) | P33-D agent (Opus) |
| P33-E Search Console monitoring scripts + de-index procedure | 33.10 | done on branch `fasttrack/p33e-gsc-monitor` — not merged; owner: GSC Domain property + OAuth client | orchestrator |
| P33-F Free-trial sign-up `/dang-ky` + `/dang-ky/cam-on`, `trial_signups` (091), public endpoint, Ops tab "Đăng ký dùng thử", privacy paragraph | 33.11 | done on branch `fasttrack/p33f-trial-signup` (cut from P33-A f55809fd, pushed) — not merged, not deployed; owner sets `TRIAL_SIGNUP_*` env | P33-F agent (Opus) |
| P33 integration + deploy + PageSpeed re-run | 33.9 | todo | orchestrator + owner |

## P34 — public UI redesign (D44)

| Task | ACs | Status | Owner |
|---|---|---|---|
| P34-A Foundation: font, tokens, shared components | 34.1 | done 2026-10-15, branch `fasttrack/p34a-ui-foundation` (not merged) | P34-A agent (Opus) |
| P34-F Demo auth screen | 34.6 | done on branch `fasttrack/p34f-auth-screen` (from 64f7f913, pushed) — not merged, not deployed | P34-F agent (Opus) |
| P34-B Homepage | 34.2 | done 2026-10-15, branch `fasttrack/p34b-home` (from P34-A c95231e0, not merged) | P34-B agent (Opus) |
| P34-C Product pages | 34.3 | done 2026-10-15, branch `fasttrack/p34c-product-pages` (not merged; based on P34-A c95231e0) | P34-C agent (Opus) |
| P34-D Blog + covers | 34.4 | done 2026-10-15, branch `fasttrack/p34d-blog` (not merged) | P34-D agent (Opus) |
| P34-E Legal, about, contact, sign-up | 34.5 | done 2026-10-15, branch `fasttrack/p34e-legal-signup` (not merged) | P34-E agent (Opus) |
| P34 integration + deploy | 34.7 | todo | orchestrator + owner |

## P37 — demo sample mirrors the real card lifecycle (D47.2, D47.3)

| Task | ACs | Status | Owner |
|---|---|---|---|
| P37 Sample store lifecycle (queued → running → applied / rejected / pending / expired), Quyết định + Phân tích on one tab-wide store, reviewer sample shares it | D47.2, D47.3 | done on branch `fasttrack/demo-lifecycle` (from 5b1a85f5) — not merged, not deployed | P37 agent (Opus) |

## P38 — cancelled / timed-out runs reactivate the card (D47.5)

| Task | ACs | Status | Owner |
|---|---|---|---|
| P38 One shared helper (`services/agent/card_reactivation.py`) puts an approved card back to `active` when its run ends `failed`, `cancelled` or `timed_out` (runner persist, crash handler, reaper); seller declines / reverts stay `dismissed` | D47.5 | done on branch `fasttrack/run-reactivate` (from 175e85ef, `fasttrack/optimize-product` merged in) — not merged, not deployed | P38 agent (Opus) |

## P39 — search-intent brand priorities on the pages (D48)

| Task | ACs | Status | Owner |
|---|---|---|---|
| P39 Titles, meta, H2s and FAQs for D48 items 1–4; `/terms` meta fix | D48 | done, merged into `fasttrack/optimize-product` (a8916adb), owner approved the copy 2026-10-16; not deployed | P39 agent (Opus) |
| P39 additions: AI tiêu đề/mô tả section, structured data type, llms.txt | D48 additions 1, 2, 4 | done, merged (a8916adb); not deployed | P39 agent (Opus) |
| P39-B Three Vietnamese blog posts (draft) | D48 additions 6 | done, merged (c5772320, 1988f93d); posts stay `draft` until the owner approves | P39-B agent (Opus) |
| P39-C Inline images in the three P39-B drafts | D48 additions 7 | done on branch `fasttrack/p39c-blog-images` (4a4f2826, 4939fd7b, 0085cf12, 522aceb1), not merged; posts stay `draft` | P39-C agent (Opus) |
| P39-D Three more figures each in không-ra-đơn and doanh-thu-giảm | D48 additions 8 | done on branch `fasttrack/p39d-more-figures` (9b69bbb0, 7a4ec86b), not merged; posts stay `draft` | P39-D agent (Opus) |
| Owner: turn off Cloudflare Email Address Obfuscation for app-juli.com | D48 additions 3 | done 2026-10-16 (live /contact has no cdn-cgi links) | owner |

## P40 — partner sign-in entry at the top of the auth screen (D47.6)

| Task | ACs | Status | Owner |
|---|---|---|---|
| P40 "Đối tác thẩm định? Đăng nhập bằng tài khoản đối tác →" above the auth heading (plain + trial), footer link kept; ISV reviewer step 1 | D47.6 | done on branch `fasttrack/partner-top` (from 12e692a1) — not merged, not deployed | P40 agent (Opus) |

## P41 — short simulation copy, no backend internals (D47.7)

| Task | ACs | Status | Owner |
|---|---|---|---|
| P41 Simulated Thực thi without endpoint / second disclaimer; short reviewer labels; plain TikTok-flag wording (demo + backend summaries); sample runs match their product; queue chip follows events | D47.7 | done on branch `fasttrack/sim-copy` (from 12e692a1) — not merged, not deployed | P41 agent (Opus) |

## P42 — legal pages: data rights and processing layers (owner, 2026-10-16)

Reason: the website legal text lacked layer 1 (data rights) and layer 2 (processing, processors, AI provider, cross-border). Website only; the md sources and the Ory contract are out of scope for this task (owner).

| Task | ACs | Status | Owner |
|---|---|---|---|
| `/terms` 2.2 §8 "Dữ liệu của bạn"; `/privacy` 2.1 §1, §4, §6, §7, §8 (VI + EN); processor list and OpenAI inputs verified in code; `legal-data-layers.test.tsx` | owner brief 2026-10-16 | done on branch `fasttrack/legal-data` (6ef17dbf) — not merged, not deployed | P42 agent (Opus) |
| Owner: confirm the unverifiable facts in LOG P42 (sign-in email sender, OpenAI data-sharing setting, Viettel-CA, counsel on cross-border basis) | — | todo | owner |

## P43 — free GMV calculator (D49.1)

| Task | ACs | Status | Owner |
|---|---|---|---|
| P43 `/cong-cu/tinh-gmv` page, client-side calculator, links, sitemap, llms.txt | D49.1 | done on branch `fasttrack/p43-gmv-calculator` (6d595c27, e172df7d, 014b4e69) — not merged, not deployed | P43 agent (Opus) |

## P44 — tools listicles naming competitors (D49.2)

| Task | ACs | Status | Owner |
|---|---|---|---|
| P44 Three draft posts a–c, hub links from the existing tools post | D49.2 | done on branch `fasttrack/p44-tools-listicles` (78db1734, 7c1109f8, eaabd2c1; not merged), drafts await owner approval | P44 agent (Opus) |

## P45 — EB-shrunk group lift in Ops (D52)

| Task | ACs | Status | Owner |
|---|---|---|---|
| P45 `primary.eb` in every group comparison (default prior), pooled per-lever-type prior on the Ops groups page via `ops_group_lift_draws()` (migration 093, `juli_ops` only), Ops UI line + tooltip, tunables `group_eb_prior_sd` / `group_eb_min_groups` | D52 | done on branch `fasttrack/eb-lift` (fb0b0b7b, 2974482d + docs) — not merged, not deployed | P45 agent (Opus) |

## P46 — continuous SEO blog, month 1 (D56)

| Task | ACs | Status | Owner |
|---|---|---|---|
| P46-A Blog rules in code: competitor sources unlinked, length by post type, weekly Search Console post report | D56 G2, G5, G6 | done on branch `fasttrack/p46a-blog-rules` (3e075a9b, ededf556, 3a6a9d18), owner merges | P46-A agent (Opus) |
| P46-B Month-1 posts 1–4 (week 1) | D56 | done: posts 1–2 (`video-tiktok-nhieu-view-khong-ra-don`, `live-tiktok-shop-khong-ra-don`, branch `fasttrack/p46b1-week1-video-live`) and 3–4 (`san-pham-tiktok-shop-khong-co-luot-hien-thi`, `thue-ban-hang-tiktok-shop`, branch `fasttrack/p46b2-week1-hienthi-thue`), merged; drafts, not deployed | writer agents |
| P46-C Month-1 posts 5–8 (week 2) | D56 | done, merged, drafts: 5 `khach-xem-nhung-khong-mua-tiktok-shop`, 6 `tang-gia-tri-don-hang-trung-binh-tiktok-shop`, 7 `ty-le-hoan-hang-tiktok-shop`, 8 `phi-san-tiktok-shop-2026` | writer agents |
| P46-D Month-1 posts 9–12 (week 3) | D56 | done, merged, drafts: 9 `dat-ten-san-pham-tiktok-shop`, 10 `anh-bia-san-pham-tiktok-shop` (fixed to D13: Juli uploads the seller's photo after confirmation), 11 `mo-ta-san-pham-tiktok-shop`, 12 `quy-dinh-livestream-ban-hang` | writer agents |
| P46-E Month-1 posts 13–14 (week 4) | D56 | done, merged, drafts: 13 `do-hieu-qua-sau-khi-sua-san-pham-tiktok-shop`, 14 `doanh-thu-sau-sale-tiktok-shop` (publish before 03/11) | writer agents |

## P47 — group-verdict money metrics net of cancelled / refunded orders (D55.1)

| Task | ACs | Status | Owner |
|---|---|---|---|
| P47 `group_net` (shop orders → per product-day cancel / refund shares → net analytics rows); Ops group AOV / items per order / replay / guard / EB on net values when the shop's orders cover days −42 … 13, TikTok-GMV reading stored beside (`gross`); card-group primary + seller sentence unchanged (`net` beside it); Ops labels "đã trừ huỷ/hoàn" / "gồm đơn huỷ/hoàn, theo TikTok", plan line "Doanh thu (đã trừ huỷ/hoàn)" vs "GMV TikTok (gồm huỷ/hoàn)"; Ops guide §5.5 (three TikTok definition notes). No migration | D55.1 | done on branch `fasttrack/gmv-net` — not merged, not deployed | P47 agent (Opus) |

## P48 — reach vs conversion tiers, unique heroes (D59)

| Task | ACs | Status | Owner |
|---|---|---|---|
| P48-A `tier` in code, neutral end-of-post CTA for reach posts, tests | D59.1, D59.2 | done on branch `fasttrack/p48a-tiers` (not merged); `REACH_JULI_PENDING` holds the 16 reach slugs for P48-B/C | agent |
| P48-B/C Remove Juli from the 16 reach posts (body, FAQ, figures, links) | D59.1 | done, merged: P48-B (8 posts) and P48-C (8 posts); `REACH_JULI_PENDING` empty | agents |
| P48-H Unique hero per post: content-engine still + landing covers | D59.3 | done on branch `fasttrack/p48h-heroes` (not merged); content engine `blog-heroes` d980b58 + c81b11c (not pushed) | agent |

## P49 — conversion posts: Juli guides and problem posts (D59 additions 4, 5)

| Task | ACs | Status | Owner |
|---|---|---|---|
| P49-S Fresh sample-shop screenshots for the guides | D59 add. 5 | done on branch `fasttrack/p49s-screenshots` (798afcfc; lich-sale skipped, see LOG) | agent |
| P49-F Demo copy fixes from P49-S + recapture | D46.4, D59 add. 5 | done on branch `fasttrack/p49f-demo-copy` (5e981b18 demo, 57260f97 landing) | agent |
| P49-A Five guide posts | D59 add. 5 | done, merged, drafts: C1–C4 (P49-A1) and C5 (P49-A2) | writer agents |
| P49-B Three problem posts | D59 add. 5 | done, merged, drafts: C6–C8 (P49-A2) | writer agents |
| P49-L End-of-post box "Đọc hướng dẫn liên quan" for reach posts | D59 add. 4 | done, merged: `guide` field on all 16 reach posts, `guideFor()`, tests | orchestrator |

## P51 — five product and sample-data fixes (D60)

| Task | ACs | Status | Owner |
|---|---|---|---|
| P51-A Demo sample data: lever ↔ target, Kéo xuống sums; recapture | D60.1 | done on branch `fasttrack/p51a-sample-data` (2247eb13 demo, 5bad50fa landing, 524da0d6 recapture) | agent |
| P51-B Landing: Đề xuất page (AOV lever, cover wording), Đo lường page (control groups), price wording | D60.2, D60.3, D60.5 | done on branch `fasttrack/p51b-product-copy` (not merged) | agent |
| Retention approved, purge job in DEBT | D60.4 | done | orchestrator |

## P52 — no algorithm or model details in public content (D61)

| Task | ACs | Status | Owner |
|---|---|---|---|
| P52-A Product pages, home, shared blocks, calculator, SEO / llms.txt; leak-pattern test | D61 | in progress, branch `fasttrack/p52a-leaks-pages` | agent |
| P52-B Eight Juli guides (body, FAQ, figure captions) | D61 | done on branch `fasttrack/p52b-leaks-guides` (recapture of 5 demo shots pending, P51-A) | agent |
| P52-A Product pages, home, shared blocks, calculator, SEO / llms.txt; leak-pattern test | D61 | done on branch `fasttrack/p52a-leaks-pages` (not merged) | agent |
| P52-B Eight Juli guides (body, FAQ, figure captions) | D61 | in progress, branch `fasttrack/p52b-leaks-guides` | agent |
| P52-C Reach posts, pillars, tools posts (body, FAQ, captions) | D61 | done on branch `fasttrack/p52c-leaks-posts` (not merged); 3 diagrams re-rendered | agent |
| Demo app + backend card copy, recapture (with P51-A) | D61 | in progress, branch `fasttrack/p51a-sample-data` | P51-A agent |
| P52-C Reach posts, pillars, tools posts (body, FAQ, captions) | D61 | in progress, branch `fasttrack/p52c-leaks-posts` | agent |
| Demo app + backend card copy, recapture (with P51-A) | D61 | done on branch `fasttrack/p51a-sample-data` (84dfaa0f copy, 524da0d6 recapture) | P51-A agent |
| P52-D Leftovers: figure / page alts match the recaptured shots, sample reasons without peer median, SM-012 CTOR card proposes Mô tả only, 4 shots recaptured | D60.1, D61 | done on branch `fasttrack/p52d-leftovers` (not merged) | agent |

## P53-C2 — remove the three legacy demo routes (owner C2, 2026-10-18)

| Task | ACs | Status | Owner |
|---|---|---|---|
| Remove `/decisions/in-progress/[executionId]`, `/decisions/recommendations/[recommendationId]`, `/settings/workflows/[workflowKey]` and their import-graph closure; demo-shell run framing; tests / e2e | C2 (audit apps.md items 6–7, TOP 15 #2, #3, #7–#11) | done on branch `fasttrack/rm-legacy-routes` (not merged) | agent |

## P53-A — cleanup A: real faults, safe cleanup, archive (D62, 2026-10-18)

| Task | ACs | Status | Owner |
|---|---|---|---|
| A1 Register `product_history` on a fresh worker; beat test in a fresh interpreter | D62 | done on branch `fasttrack/cleanup-a` (turns the P23 fan-out on in prod — DEBT P53-A) | agent (Opus) |
| A2 8 deep imports through `services.ops` / `services.action_cards`; boundary baseline re-derived (54 rows) | D62 | done on branch `fasttrack/cleanup-a` | agent (Opus) |
| A3 Repo-pinned tests: trial_signups tail from the tree, ratchet suppressions retired, reaper TZ, module_md allowlist, quality figures | D62 | done on branch `fasttrack/cleanup-a` except the #1682 prior-figure drift check (owner, DEBT P53-A) | agent (Opus) |
| A4 `JULI_TEST_DATABASE_DISPOSABLE` on the deploy check step | D62 | done on branch `fasttrack/cleanup-a` | agent (Opus) |
| B3 Delete `services/etl/topics.py` | D62 | done on branch `fasttrack/cleanup-a` | agent (Opus) |
| B4 Untrack `apps/dashboard/tsconfig.tsbuildinfo` | D62 | done; `package-lock.json` and `done.md` kept (still read by pr.yml — DEBT P53-A) | agent (Opus) |
| B6 LEGACY markers: `ios/`, `agent-runtime/`, `EXECUTION.md`, `Design-md/`, test-only backend modules | D62 | done on branch `fasttrack/cleanup-a` | agent (Opus) |
| B7 Archive LOG / DECISIONS / closed DEBT before 2026-10-12 to `fasttrack/archive/` | D62 | done on branch `fasttrack/cleanup-a` | agent (Opus) |

## P53-C1 — delete apps/dashboard (owner C1, 2026-10-18)

| Task | ACs | Status | Owner |
|---|---|---|---|
| Delete `apps/dashboard` + its CI job, dev scripts, review/provision scripts, guarding tests; docs marked historical | audit C1 | done on branch `fasttrack/rm-dashboard` (not merged) | agent |

## P54 — Dependabot pip bumps applied (D63)

| Task | ACs | Status | Owner |
|---|---|---|---|
| Nine pip bumps in one constraints regeneration; pyproject / requirements floors in sync; pydantic-core deferred | D63 | done on branch `fasttrack/pip-bumps` (not merged) | agent |

## P55 — deploy gates (D64, 2026-10-19)

| Task | ACs | Status | Owner |
|---|---|---|---|
| A Detector: imported / conftest / method / third-party assertion helpers; #1682 prior-figure claim over a recorded fixed set (106, drift 9) | D64.4 | done on branch `fasttrack/deploy-gates` (not merged) | agent (Opus) |
| B Unit suite green with no database (wiring seam stub, 2 tests `requires_postgres`, cross-tenant stream factory, scan timeouts) | D64.2 | done on branch `fasttrack/deploy-gates` | agent (Opus) |
| C `frontend`, `backend-unit`, `static` jobs; `deploy` needs them; `.nvmrc`; README job table | D64.1–3 | done on branch `fasttrack/deploy-gates`; first exercised by the next deploy | agent (Opus) |

## P50 — PDPL legal terms and the features they promise (D68)

Reason: owner grill 2026-10-18; the pages must promise only what the product does, so the features ship with the text. API contract: `fasttrack/contracts/p50-privacy.md`.

| Task | ACs | Status | Owner |
|---|---|---|---|
| P50-L `/terms` VI + `/privacy` VI/EN rewritten to D68; no version shown; tests | D68.1–14 | done on branch `fasttrack/p50-legal-pdpl` (490dc852) | agent (Opus) |
| P50-B Backend: migration 094 privacy prefs + consent columns, `/v1/me/privacy`, `/v1/me/consents`, `/v1/me/export`, `/v1/me/deletion`, nightly purge task | D68.6, .10 | done (c7590c7b, 12982b66, f783d204; merged b4503d55) | agent (Opus) |
| P50-U Demo: Cài đặt → Quyền riêng tư tab, terms re-acceptance strip with the separate Điều 11 checkbox, demo pixel gated on ad-measurement opt-out | D68.4, .6, .8 | done (bbbaeee8..e4d2f599; merged 73dc51eb) | agent (Opus) |
| P50-P De-identification at the LLM boundary (`core/privacy/deidentify.py`) | D68.2 | done (530ec8b5, c4bf6e97; merged 7a9cc99f) | agent (Opus) |
| P50-E Terms-change e-mail via the SMTP mailer (one-off task) | D68.8 | done (3f546f54); owner runs it after deploy | agent (Opus) |
| Owner: deploy tag, then `python -m juli_backend.services.ops.terms_notice --sent-list PATH` (dry run) and `--send` | D68.8 | todo | owner |

## P56 — first `backend-unit` deploy-gate failure fixed (D65, 2026-10-19)

| Task | ACs | Status | Owner |
|---|---|---|---|
| Gate sweep runs every gate under one pinned CI-flow context (`gate_env`); tag-push regression test | D65.1 | done on branch `fasttrack/ci-fix` (not merged) | agent (Opus) |
| Dissolved PR #1472 commits declared with their archive ref; deploy job fetches `refs/pull/1472/head` and requires the rows to resolve | D65.2 | done on branch `fasttrack/ci-fix` | agent (Opus) |

## P58 — production bugs from the 2026-10-19 worker log (D67)

| Task | ACs | Status | Owner |
|---|---|---|---|
| A `epoch_to_naive_utc` reads s / ms / µs / ns and never raises; one bad promotion is logged + skipped (SAVEPOINT), not the sweep | D67.1–2 | done on branch `fasttrack/prod-bugs` (not merged) | agent (Opus) |
| B Missing `shop_cipher` backfilled via Get Authorized Shops (binding-checked); unresolvable → `needs_reauth`, fan-out stops; TikTok error URLs lose their signed query | D67.3–4 | done on branch `fasttrack/prod-bugs` (not merged) | agent (Opus) |

## P57 — rollback works again (D66, 2026-10-19)

| Task | ACs | Status | Owner |
|---|---|---|---|
| A Remove `juli-web` from scripts, units, env template, IAM template; tests assert it is gone | D66.1 | done on branch `fasttrack/rollback-fix` (not merged) | agent (Opus) |
| B `rollback-release.sh`: all-lane rollback to an earlier deploy, live health checks, PASS/FAIL summary, `--plan` / `--verify` | D66.2–4 | done on branch `fasttrack/rollback-fix` | agent (Opus) |
| C `rollback.yml` for fast-track (tag + dispatch, no `git checkout main`, deploy concurrency group) | D66.5 | done on branch `fasttrack/rollback-fix`; first exercised by the owner | agent (Opus) |
| D Simulation harness + workflow tests; `celery_unit_queues` comment fix | D66.6 | done on branch `fasttrack/rollback-fix` | agent (Opus) |
| E Runbook (VI) incl. one-time live drill | D66 | `docs/runbooks/rollback-runbook.md`; drill not run | owner |

## P59 — Search Inventory 12019008 no longer wedges bootstrap (D69, 2026-10-19)

| Task | ACs | Status | Owner |
|---|---|---|---|
| Deleted / draft products not sent to Search Inventory; unknown status kept | D69.1 | done on branch `fasttrack/inventory-ids` (not merged) | agent (Opus) |
| 12019008 page bisected; rejected ids skipped + logged; 10-call cap + own 10/60 s bucket; other errors still raise | D69.2–4 | done on branch `fasttrack/inventory-ids` | agent (Opus) |
| TikTok exceptions picklable (Celery result backend) | D69.5 | done on branch `fasttrack/inventory-ids` | agent (Opus) |
| Owner: merge, deploy tag, then check the VPS log for `shop_bootstrap_fast_done` / `sync_inventory_product_skipped` | D69 | todo | owner |

## P60 — data platform (D70, 2026-10-20)

Plan of record: `docs/product/data-platform/GRILL_LOG.md` (D16 order) corrected by
`GAP_MAP_FASTTRACK.md` (what this branch already has).

| Task | ACs | Status | Owner |
|---|---|---|---|
| P60-0a TikTok webhook coverage for seller-side changes | D70.11 (2) | done (c413d448, `P0_TIKTOK_WEBHOOKS.md`) | agent (Sonnet) |
| P60-0b Gap map D1–D16 vs this branch | D70 | done (`GAP_MAP_FASTTRACK.md`) | agent (Sonnet) |
| P60-0c `fujiwa_db_coverage.sql` on production (read-only) | D70.16 | todo | owner |
| P60-0d Max history depth per endpoint, measured on Fujiwa (read-only) | D70.3 | todo | owner + agent |
| P60-ADR ADR-112..115 + ADR-107 amendment + notes on 029 / 046 / 077 / 104 / 105 | D70 | done (owner flags open — LOG 2026-10-20) | agents (Opus) |
| P60-1a `card_events` minimum + RLS + writer + backfill from existing tables | D70.9 | done, merged (ff 9bbd313a; full unit suite 7764 passed, 245 skipped); owner: deploy + run card_events_backfill_fanout — LOG 2026-10-20 P60-1a | agent (Opus) |
| P60-1b Content hashes on `run_write_values`; `external_changes` source juli / seller_revert / seller_change → `card_events` | D70.11 (1)(3) | done, merged (P60-1b); migration 096; owner: deploy + run card_events_backfill_fanout — LOG 2026-10-20 P60-1b | agent (Opus) |
| P60-1c `valid_from` / `valid_to` + current view over `product_snapshots`; confirm `product_history_fanout` live for Fujiwa | D70.4 | todo | — |
| P60-1d Raw Get Product body as product bronze | D70.4, D70.8 | todo | — |
| P60-1e One `gold.ml_feature_snapshots` row per proposal | D70.12 (2) | todo | — |
| P60-1f `persisted` no longer counts DLQ rows (#1950) | D70.8 | todo | — |
| P60-2..8 platform, adapter, D6 group, cold start, action loop, training, Shopee | D70.16 | todo (after P60-1) | — |

## P61 — any shop end to end, no hardcoding, streaming (D71, 2026-10-20)

| Task | ACs | Status | Owner |
|---|---|---|---|
| P61-A Agent reads per shop (hotfix) + two-shop no-leak test | D71.1 | done, merged (ff c6bc698b) | agent |
| P61-B Production write per shop (P5), flags off; honest sandbox UX; measurement ignores sandbox runs | D71.2 | done, merged (dispatched path only; agent-run production leg = P61-F); flags off | agent |
| P61-C Token streaming: adapter → `assistant.text.delta` → SSE → demo caret; ADR-071 amendment | D71.3 | done, merged (ff 9470ffb7); owner after deploy: one live run, check `assistant.text.delta` then `assistant.text` rows; off switch `LLM_STREAMING=off` | agent |
| P61-D Hardcode / beat / flag cleanup, startup env check, reject route, delete `fujiwa_poll_beat` | D71.4 | done, merged (P61-D); superseded by P61-G: no merchant env vars | agent |
| P61-G Merchant identity from the connect flow, no env/hardcode (owner 2026-10-21) | D71.6 | done, merged (587cdcce); migration 099; env vars removed — owner: unset/remove both TIKTOK_*_MERCHANT_ID on the VPS | agent |
| P61-G2 Sandbox collision = other shop's credential only (owner 2026-10-21, production fact: sandbox shop has sandbox_write + seller_connect, one cipher) | D71.6a | done on branch fasttrack/p61-g2-same-shop (not merged); migration 100; blocks the production deploy | agent |
| P61-F Agent-run production leg (resume resolves capability + one-time authorization for the pending write; refuse live when the image is sandbox-staged; revert reads the real listing) + migration data step marking pre-097 sandbox-written runs `write_mode='simulated'` (owner 2026-10-21) | D71.2 | todo (after P62 merges) | — |
| P61-E End-to-end two-shop test OAuth → `card_events`; live `shown` / `expired` writers | D71.5 | todo (after A–D and P60-1b merge) | — |
| Owner: confirm production env (`AGENT_WORKFLOWS_ENABLED`, `TIKTOK_APP_KEY/SECRET`, `REDIS_URL`); later flip `PRODUCTION_WRITE_ENABLED` per shop | D71 | todo | owner |

## P62 — Supabase egress (D72, 2026-10-21)

| Task | ACs | Status | Owner |
|---|---|---|---|
| P62-A Fewer dumps: pending-migration-only pre-migrate dump, backup job only with a migration (+ `force_backup`), scheduled VPS dump timer (every 72 h, `BACKUP_MIN_INTERVAL_HOURS`) | D72.1 | done, merged (587cdcce) | agent |
| Owner: after the P62-A deploy, install + enable `juli-db-backup.timer` on the VPS (fasttrack/README.md "Database dumps") and read the first `DUMP_SIZE` line | D72.1 | todo | owner |
| P62-B `processed_events` retention; scoped `analytics_performance_intervals` / `silver.orders` reads; pooled worker engine | D72.2–4 | done, merged 3579de71 (pooling D72.4 deferred to DEBT; migration 098 on 096 — lead fixes the chain with P61-B's 097). D72.4 pooled worker engine NOT done (reported, DEBT) | agent |
| Owner: after deploy, re-check Usage → Egress per day and `pg_stat_statements` (reset first: `select pg_stat_statements_reset();`) | D72 | todo | owner |
| P63 get_shop_identity agent tool (owner 2026-10-21): TikTok Get Authorized Shops as a READ tool (product domain, optional playbook step 0.5), run shop's own credential, sanitized name/region/seller type/`shop_matches`, mismatch = refusal result + warning | D71 | done, merged (587cdcce) | agent |

## P2–P6

Not started. See SPEC §4. P3 no longer waits on FastMoss (D22): next after P7. P2 (FastMoss) is optional and still waits on the API trial (owner).

## Owner actions (not for agents)

- P57: deploy, then delete AWS secret `juli/web/production` (only after the deploy), drop its
  ARN from the live IAM policy, remove the `juli-web` unit + `/etc/juli/web.env` on the VPS, and run
  the one-time rollback drill (docs/runbooks/rollback-runbook.md §6–7).
- FastMoss REST API trial + 1,000-request minimum (P2, optional since D22).
- Confirm Fujiwa's TikTok authorisation allows product writes (blocks P5).
- Consent screen #2061 (launch, not this branch).
- Dependabot keeps reopening PRs because its config is read from `main`
  (frozen). Either accept periodic closes, or allow a one-line change on `main`
  setting `open-pull-requests-limit: 0`.
