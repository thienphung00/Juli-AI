# P98 plan — one Shopee funnel, accurate option results, then the combo / KOL / ads builders

Decisions: [ADR-122](../../docs/adr/122-one-shopee-funnel-and-option-results.md) (grill P98 C1–C10, owner
2026-11-09). Terms: `CONTEXT.md` › Shopee option estimates (Option result, Driver metric, Shopee funnel
base, Source funnel, Cashback affiliate). Builds on production `4a772039` (P97, head `125_reco_plan_groups`).
Never write Fujiwa; synthetic data only in the repo. Owner order: numbers first, then Combo → KOL → Ads.

## Steps (dependency order)

| Step | What | ADR-122 | Lane / deploy |
|---|---|---|---|
| S1 | **Source funnel table** (migration 126, expand-only, RLS, `juli_app` grants): shop × day × source and product × day × source — Lượt xem, lượt nhấp, đơn and GMV scaled to ShopMetrics, lợi nhuận, the "trong đó Quảng cáo" share (ad views, clicks, đơn, spend); residual "Chênh lệch nguồn". Filled by `materialize.after_ingest` and `scripts/backfill_shopee_metrics.py`. | d.2, d.3 | deploy A |
| S2 | **One funnel read model** `shopee_analytics/funnel.py`: window sums → CTR = lượt nhấp ÷ lượt xem, CTOR = đơn ÷ lượt nhấp, never daily averages; scope shop / product(s) / source. Tổng quan, Phân tích, Sản phẩm, Kế hoạch base and the builder read only this (replaces `traffic.scope_traffic` and `before_after._shop_base`). | d.2 | deploy A |
| S3 | **Funnel engine** `shopee_builder/engine/`: each kind declares drivers + source(s) (d.6–d.10 tables); evaluators supply cost and lợi nhuận mỗi đơn only; fixed-seed scenarios through the funnel, ranked by Δ Lợi nhuận, P10 / P50 / P90 as whole columns; build-up line; break-even; duration and the 30-day horizon. Replaces `before_after.build` and the money layer as the producer of results. | d.1, d.4 | deploy A |
| S4 | **Per-family evidence:** voucher (AOV + CTOR, cost on expected uses, scopes → sources), combo khuyến mãi (cost on every tier order incl. already-buying), price / listing / basket / gift (product history > shop > tagged prior), ads incrementality measured from on / off days (else "chưa ước tính được — cần chạy thử"), affiliate per KOL + cashback classification; ads-edit kinds hidden from the builder. | d.6–d.10 | deploy A |
| S5 | **Card + comparison UI** (demo): the five-line card (Δ Lợi nhuận money · % + range + build-up; Δ GMV; Δ Đơn; Tác động %; Chi phí + hoà vốn; Sau N ngày), Chi tiết, comparison table sorted per 30 days. | d.5 | deploy A |
| S6 | **Accuracy checks:** funnel property tests on every kind (gate), cross-screen Postgres test, daily "lệch số liệu" check in Ops, coverage of frozen predictions in Ops (ADR-121 scoring). | d.11 | deploy A (tests gate it) |
| S7 | **Combo builder:** pick products → variations → pack sizes; rules against exploding combinations (same variation per pack, sold in 30 days, at most N); Shopee per-listing limits (confirmed at recon); pricing rule for all rows (discount ladder default, target margin, price per box) with margin floor; table (price, per box, saving, margin, profit / order, floor); names, SKUs, suggested stock "không tự đồng bộ"; extra orders from matching pack variations only (d.7). Delivery: copyable table first; then record "Thêm sản phẩm" and the bulk-upload file and pick one. | d.7 | deploy B |
| S8 | **KOL builder:** pick KOLs from the KOL table, products, targeted commission %, samples (product, quantity, shipping); exact cost; break-even-led until measured. | d.9 | deploy C |
| S9 | **Ads builder:** new Hiển thị Sản phẩm setups (nhóm / đơn), compared; auto-fill of the create form after a recorded walk-through. | d.8 | deploy D |

Deploy A ships S1–S6 together (the numbers change once, behind the tests). Each deploy follows
`fasttrack/contracts/p97-deploy-checklist.md`'s shape (migrations, flags, backfill, rollback).

## Open items carried from the session (not part of ADR-122)

- Connector: keep `detail` in each reader outcome; post the orders page's own answers when a later page
  fails; fix the orders `error` once its detail is captured (owner runs the service-worker listener).
- Server: a drift flag counts only when it came from the version that last posted (owner held this to
  ship with the orders fix).
- KOL channel labels for Shopee `traffic_type` 0 / 1 / 2 (owner reads Kênh in Báo cáo chuyển đổi).
