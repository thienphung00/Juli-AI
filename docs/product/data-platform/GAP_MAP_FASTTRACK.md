# Gap map — grill D1–D16 vs `fasttrack/optimize-product` (2026-10-20)

The grill's "Hiện trạng" was surveyed on `main`. This map re-checks every decision against the
fast-track branch (head `c413d448`). `BE` = `backend/src/juli_backend`, `MIG` =
`BE/database/migrations/versions` (head 094). Read-only survey by an agent (Sonnet), checked by
the lead before use.

## A. "Hiện trạng" claims on this branch

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1a | Poll only for the configured shop (`shop_id=None`) | **Stale — fixed** | `BE/workers/tasks/shop_ingestion.py` (P1-B): `shop-poll-fanout` every 15 min → `bootstrap_shop` / `poll_shop` / `shop_history_backfill` / `shop_history_extend` per shop, Redis per-shop mutex; `BE/workers/services/polling/orchestrate.py` (#1995) takes `shop_id`. State: `shop_ingestion_state` (MIG/074). `shop_id=None` survives only in legacy `fujiwa_poll_beat.py`. |
| 1b | `DEMO_REFERENCE_SHOP_ID` hardcode | **Still true** | `BE/workers/tasks/analytics_backfill_topup.py`, `BE/workers/tasks/mock_analytics_reconcile.py`, beat entries in `BE/workers/celery_app.py`, `BE/api/routes/demo_analytics.py:33`; `impact_reader.py` docstring still says other shops are "suppressed". |
| 2 | `products` current-only, no product bronze | **Partly stale** | `product_snapshots` (MIG/087, P23, D30.1a): append-only versions keyed (shop, product, day, `state_hash`); no `valid_from`/`valid_to`, `platform`, `bronze_id`. No raw bronze for products / promotions / video. |
| 3 | Intervals lack clicks / add-to-cart / channel | **Partly stale** | MIG/075 added `clicks`, `traffic_breakdown`, `sales_breakdown` (JSON). No add-to-cart; channel is JSON, not key. Also `shop_daily_streams` / `shop_daily_products` (MIG/085), `platform_daily_metrics` (MIG/088). |
| 4 | No `card_events`; `gold.ml_feature_snapshots` unwritten; no intervention table | **True** | ADR-107 still Proposed. `gold.ml_feature_snapshots` (MIG/021, RLS MIG/046) has no writer. Related: `external_changes`, `run_baselines` (MIG/087), `run_write_values` (MIG/078), `run_lever_flows`, `run_measurement_finals`, `lever_calibrations` (MIG/080), `impact_readings` (MIG/033), `workflow_run_events` (MIG/035). |
| 5 | No partitioning / retention; `persisted` counts DLQ (#1950) | **True** | No Postgres partitioning (`analytics_backfill_partitions` is a checkpoint table). Retention only `ops_audit_retention`, `privacy_account_purge`. `persisted` bug documented in `BE/workers/services/polling/sync.py` (handoff discards `ProcessOutcome`). ADR-105 verdict fields on `tiktok_sync_state` (MIG/071). |
| 6 | Redis fixed window (app, shop, endpoint) | **True** | `BE/integrations/tiktok/rate_limiter.py` (INCR+EXPIRE), shared by `shop_diagnosis_daily/pacing.py` and `product_history`. No priority queue, no token bucket per (platform, group). |

## B. Decisions

| D | Status | Built by | Remaining gap |
|---|---|---|---|
| D1 | Partial | `shops.platform`, `ingest_raw_payloads`, `platform_daily_metrics`, `ingest_dataset_status` (MIG/088, D31.3/P24) | `platform` on `tiktok_credentials` (MIG/001), `tiktok_sync_state` (MIG/009), `webhook_raw_events` (MIG/016); `endpoint` on bronze; channel-neutral silver. |
| D2 | Missing | Redis per-shop locks; Celery queues `ingest_priority` / `ingest_backfill`; `_CycleDeadline` | `ops` job table, per-(platform, app, shop, group) token bucket, 429 back-off, round-robin, P2 reserve. |
| D3 | Partial | `shop_ingestion_state` (60 d on connect, 180 d nightly; D25.12 / P17) | L1/L2/L3 levels, measured endpoint depth, "sơ bộ" label. |
| D4 | Partial | `product_snapshots`, `store.record_read`, `external_changes` (`juli_write` via `run_write_values`), `product_history_fanout` beat (D30.1a / P23) | `valid_from`/`valid_to` + current table; hash lacks image order / category; prod fan-out only enabled by P53-A (confirm live). |
| D5 | Partial | `analytics_performance_intervals` (MIG/017/018/075), `shop_daily_*` (MIG/085), silver orders/returns (MIG/025) | `(shop, product, day, channel)` key, add-to-cart, SKU×day, 7-day re-pull + `last_revised_at`, covering index. |
| D6 | Partial | Promotions (D30.1b); live hours / CTOR bronze (MIG/029); `shop_diagnosis_reports` (MIG/076) | Video / live list, daily inventory history, review distribution. |
| D7 | Missing | — | Monthly partitions, pre-create job, 13-month bronze, Parquet export. |
| D8 | Partial | Bronze `order_raw_payloads` / `return_raw_payloads` (MIG/023), silver (MIG/025), `services/etl/*`, ADR-101 fixtures | `bronze_id`, `mapper_version`, replay; #1950. |
| D9 | Missing | Nearest: `workflow_run_events`, `action_cards` revisions (ADR-087), `impact_readings`, `run_lever_flows`, `run_measurement_finals` | `card_events` table + writer + freeze at proposal. |
| D10 | Missing | `ops_group_lift_draws` (MIG/093, D52/P45) | `experiments`, `experiment_assignments`. |
| D11 (1) | Done (no hash) | `run_write_values` (MIG/078, P8-C), `services/run_changes/recorder.py` | Content hash column. |
| D11 (2) | Done | Webhooks 15/16/18/63/39 → `services/product_history/webhooks.py`; `update_time` reconcile in `job.py`; `replay.py` (D30.4 / P23) | Price / SKU / delete / coupon need poll — see `P0_TIKTOK_WEBHOOKS.md`. |
| D11 (3) | Partial | `store.matches_juli_write` | Per-field `juli` / `seller_revert` / `seller_change`; `card_events` rows. |
| D11 (4) | Done | `services/run_changes/{live,revert,planner}.py` (P8-C) | — |
| D11 (5) | Partial | `product_history/overlap.py` annotates; day-7 guardrail | Cut verdict at revert date; `reverted` / `confounded` labels. |
| D11 (6) | Partial | Promotion timeline; price via SKU-price diff | As (3). |
| D12 | Missing (1 partial) | `received_at`, snapshot day, `run_baselines.captured_at` (D30.1c) | Uniform known-at, feature snapshot writer, manifest, holdout registry, variable-role catalogue. |
| D13 | Missing | D30.3 prediction ranges (internal) | All four steps. |
| D14 | Partial | Per-shop fan-out replaced `shop_id=None` poll | Remove `DEMO_REFERENCE_SHOP_ID`; parallel write + daily reconcile vs A-34. |
| D15 | Partial | ADR-101 fixtures, ADR-089 two-tenant RLS pattern, ADR-104/105 verdicts, Ops console (MIG/083) | Replay test, partition / version tests, 50-shop scheduler test, kill-worker test, sandbox contract, leakage, reconcile, SLOs, runbooks. |

## C. D16 phases now

| Phase | State |
|---|---|
| P0 | Webhooks answered (`P0_TIKTOK_WEBHOOKS.md` + D30.4). Endpoint depth and `fujiwa_db_coverage.sql` open. |
| P1 | Partial — see corrected list below. |
| P2 | Missing (only `shops.platform`). |
| P3 | Partial (per-shop poll, silver orders). |
| P4 | Partial (promotions only). |
| P5 | Partial (per-shop bootstrap; no readiness levels; hardcode remains). |
| P6 | Partial (revert, baselines; no attribution values, no experiments). |
| P7 | Missing. |
| P8 | Partial (ISV application, extension gateway — ADR-111, D31, MIG/088). |

**Corrected P1** (do not rebuild product versions, before/after values or webhooks):

1. `card_events` minimum — migration + RLS (append-only), writer; backfill `proposed` / `accepted` /
   `executed` / `final` from `action_cards`, `workflow_run_events`, `impact_readings`,
   `run_measurement_finals`.
2. Content hashes on `run_write_values`; `external_changes` source `juli` / `seller_revert` /
   `seller_change`; emit `seller_change` into `card_events`.
3. D4: `valid_from` / `valid_to` + current view over `product_snapshots`; confirm
   `product_history_fanout` is live in production for Fujiwa (DEBT P53-A).
4. Raw Get Product body as product bronze beside the snapshot.
5. One `gold.ml_feature_snapshots` row per proposal.
6. Fix `persisted` counting (#1950) in `services/ingestion/handoff.py`.

## D. Existing ADRs that cover parts of D1–D16

009 canonical model (D1) · 029 analytics backfill, call budget (D2/D5/D6) · 046 medallion,
cutover by domain (D7/D14) · 077 DiD impact (D10/D11-5) · 089 fleet work under tenant isolation
(D2, RLS) · 101 fixtures (D8/D15) · 104 / 105 poll outcomes and verdict (D8/D15) · 106 outcome
labels · 107 `card_events` (D9, Proposed) · 108 shop diagnosis (A-34 channels) · 111 Shopee ISV
(D1/P8). Fast-track decisions to cite: D24, D25.12 / D26, D30, D31.
