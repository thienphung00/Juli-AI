# System Design

> Single technical-design doc for Juli-AI. Sections map directly to the phase gates
> in [`../EXECUTION.md`](../EXECUTION.md). For deployed reality see
> [`architecture/map.md`](architecture/map.md); for data status see
> [`architecture/data-sources.md`](architecture/data-sources.md).
>
> **Authority:** `EXECUTION.md` > this file > `map.md`. If this file disagrees with
> EXECUTION.md, EXECUTION.md wins and this file is corrected in the same PR.

## North star

Juli-AI helps TikTok Shop sellers **make and keep more money** via three agentic
workflows: **New Seller Copilot**, **Revenue Leakage Detection**, **Growth Copilot**.
The product is built UI-first (Phase 1), then ML (Phase 1.5), then live data (Phase 2).

---

## Phase capability matrix

Each subsystem evolves across phases. This table is the index; details follow below.

| Subsystem | Phase 1 (UI) | Phase 1.5 (ML) | Phase 2 (APIs) |
|-----------|--------------|----------------|----------------|
| **Agent decision tree** | Rules-based seller-stage detection | ML classifier | Live daily scoring |
| **Data pipeline** | Mock JSON | Backtest data (parquet) | TikTok API polling |
| **ML models** | none | Trained, serialized | Production inference |
| **Copy layer** | Hardcoded mock copy | Rules-only templates from signals | Ollama (local) + rules fallback |
| **Executor** | UI approval flow (no-op) | (no changes) | Real task triggers |

---

## Subsystems

### 1. Agent decision tree

Routes a seller to the right workflow and the right next action.

| Phase | Behavior |
|-------|----------|
| **Phase 1** | Rules-based seller-stage detection from mock seller profile (e.g. order count, shop age thresholds → New Seller vs Growth). Deterministic, hand-tuned. |
| **Phase 1.5** | Replace rules with the trained **seller stage classifier** (see Models); run against backtest data offline to compare against the rules baseline. |
| **Phase 2** | Live daily scoring — classifier runs on real polled seller data each morning; decision tree consumes model output to select workflow + tasks. |

### 2. Data pipeline

| Phase | Source | Mechanism |
|-------|--------|-----------|
| **Phase 1** | Mock JSON | Hardcoded seller profiles, sample orders / returns / ads loaded from fixtures. No network. |
| **Phase 1.5** | Backtest data (parquet) | Q4 / Q1 historical TikTok Shop orders (or synthetic). Batch-loaded for offline training and validation only. |
| **Phase 2** | TikTok API polling | Orders, Products, Affiliate, Ads polled into Postgres; **seller account health** polled **if exposed** (VP/AHR/withholding/violations), otherwise computed via proxies or marked unavailable (see `data-sources.md`). Daily batch feeds inference. Platform policy signals from [`tiktok_platform/`](tiktok_platform/README.md) implementation hooks. |

Pipeline jobs (feature build → train → inference) are kept as **separate,
runner-agnostic jobs** so the Phase 2 scheduler is a runner swap, not a rewrite.
Phase 2 uses a simple daily scheduler (cron / APScheduler). Celery / Kafka are
**out of scope** (Phase 3+, see EXECUTION.md → Explicitly out).

### 3. ML models

Three model suites. **Not built in Phase 1.** Trained + serialized in Phase 1.5;
served in Phase 2.

| Suite | Purpose | Powers workflow | Validation (Phase 1.5) |
|-------|---------|-----------------|------------------------|
| **Seller stage classifier** | Classify seller lifecycle stage | New Seller Copilot, decision tree routing | Precision/recall vs labeled historical stages |
| **Anomaly detector** | Detect returns / affiliate fraud / commission disputes / balance withholding | Revenue Leakage Detection | Precision/recall vs **known fraud cases** + documented return patterns; platform-policy signals (VP milestones, SFCR/LDR/SNAD, commission dispute holds) as deterministic rule inputs |
| **Ad performance analyzer** | Diagnose spend efficiency, flag scale/cut | Growth Copilot | Backtest ROAS predictions vs realized |

**Backtest protocol (Phase 1.5):** train on a historical window, evaluate on a
held-out Q4 / Q1 window; report precision/recall (and ROAS error for the ad model)
against ground truth. Record target thresholds **here** before promoting to Phase 2.

> Targets (fill in during Phase 1.5):
> - Seller stage classifier: precision ≥ _TBD_, recall ≥ _TBD_
> - Anomaly detector: precision ≥ _TBD_, recall ≥ _TBD_ on known fraud set
> - Ad performance analyzer: MAPE ≤ _TBD_ on backtest ROAS

**Outputs:** serialized models (pickle / joblib), feature specs, inference
signatures. Each artifact carries metadata: train date, row count, feature schema
hash, metrics snapshot.

```
models/
  seller_stage/{version}/model.joblib + metadata.json
  anomaly/{version}/model.joblib + metadata.json
  ad_performance/{version}/model.joblib + metadata.json
```

### 4. Copy layer

Turns structured ML/rules output into seller-facing copy for the UI and alerts.
The LLM **never** decides what to recommend — it only summarizes and localizes
copy from deterministic signals.

```
ML / rules → structured signals
        → lightweight LLM (summarize + localize copy)
        → UI / alerts
        → rules fallback if LLM fails or budget exceeded
```

| Phase | Behavior |
|-------|----------|
| **Phase 1** | Hardcoded mock copy in fixtures; no LLM. |
| **Phase 1.5** | Rules-only templates generated from backtest signals; validates copy quality offline. |
| **Phase 2** | **Ollama** (local) renders copy from live signals — summarize + localize (Vietnamese); **rules fallback** on timeout, error, or daily token budget exceeded. |

**Ollama implementation (Phase 2):**

- Runs on a **local inference node** (cost-optimized; no cloud GPU required for copy).
- Input: structured signal JSON from ML/rules (signal type, severity, metrics, recommended action).
- Output: localized task title, body, and CTA for UI / alerts.
- The model **never** decides recommendations — only rewrites deterministic signals.
- Enforce a per-shop (or global) daily token budget; log `copy_source: ollama | rules_fallback`.

**Rules fallback:** Pre-authored templates keyed by signal type (e.g. `anomaly:return_spike`,
`ad:scale_candidate`). Same structured input Ollama receives; no silent degradation to
generic text. Missing Ollama must not block API writes or task execution.

### 5. Platform policy signals (Phase 2)

Deterministic rules derived from TikTok Shop seller/creator policy — not ML.
Sourced from [`tiktok_platform/seller/implementation-hooks.md`](tiktok_platform/seller/implementation-hooks.md)
and [`tiktok_platform/creator/implementation-hooks.md`](tiktok_platform/creator/implementation-hooks.md).

**Data availability contract (Phase 2):** Policy thresholds (VP/AHR/withholding/appeal windows) are
authoritative in platform docs, but **API exposure is not assumed**. Phase 2 must track
`health_data_source: api | proxy | unavailable` (per [`architecture/data-sources.md`](architecture/data-sources.md))
and degrade explicitly — no Seller Center scraping.

| Signal | Threshold | Workflow | Action |
|--------|-----------|----------|--------|
| Seller VP warning | VP ≥ 7 | Revenue Leakage / Alerts | Warn before 12-VP affiliate block |
| Seller VP milestone | VP ≥ 12 | Revenue Leakage | Block affiliate enrollment recommendations; alert 7-day suspension |
| Seller VP severe | VP ≥ 24 | Revenue Leakage | Alert listing/LIVE suspension; prioritize stabilization tasks |
| Seller AHR Orange | AHR ≤ 199 | Revenue Leakage / Alerts | Post-July 2026; dual-read with VP during transition |
| Seller AHR Red | AHR ≤ 150 | Revenue Leakage | Escalate to critical-risk band |
| Balance withholding | Enforcement active | Revenue Leakage | Treat balance as `frozen` (not `pending`); alert seller |
| Commission dispute hold | Order in dispute | Revenue Leakage | Flag affiliate commission as leakage signal |
| Appeal window | ≤ 7 days to deadline | Alerts | Surface appeal urgency in UI |
| Creator KYC incomplete (VN) | No CCCD + tax code | Revenue Leakage (affiliate context) | Flag linked creators blocking commission payout |

**Affiliate enrollment gate (seller):** Suppress affiliate recruitment in New Seller Copilot
when VP ≥ 12 (or AHR unhealthy post-July 2026). Commission priority: Targeted Collaboration
overrides Open Collaboration rate ([`cross-cutting.md`](tiktok_platform/cross-cutting.md)).

**VP → AHR transition:** If VP/AHR fields are exposed via official APIs, dual-read both systems
May–July 2026; feature-flag switch to AHR-only after July 2026
([ADR-009](decisions/009-dual-read-vp-ahr-transition.md)). If not exposed, remain in
`proxy`/`unavailable` mode and do **not** fabricate numeric VP/AHR.
Milestone alerts must fire on threshold hits — not silent degradation
([ADR-008](decisions/008-alert-vp-ahr-milestones.md)).

**Out of Phase 2:** Creator CHR scoring, creator matching filters, LIVE commerce
attribution — Phase 3+ per EXECUTION.md. VN-specific thresholds (follower count,
tax code, CHR zones) are region-variant config ([ADR-010](decisions/010-vn-regional-platform-config.md)).

### 6. Executor

Turns an approved recommendation into action.

| Phase | Behavior |
|-------|----------|
| **Phase 1** | UI approval flow is a **no-op** — seller approves/dismisses a task; nothing executes. Captures intent + engagement only. |
| **Phase 1.5** | No changes — UX still mocked. |
| **Phase 2** | **Real task triggers** — an approved task fires the corresponding action against TikTok APIs / seller tooling. |

---

## End-to-end flow (Phase 2 target)

```
[TikTok API: Orders · Products · Affiliate · Ads · (optional) Shop Account health]
        │  daily poll (health if exposed; else proxy/unavailable)
        ▼
   Postgres (seller signals + policy state)
        │  06:00–07:00 UTC feature build
        ▼
   feature tables (+ platform policy rule inputs)
        │  08:00 UTC daily batch inference
        ▼
   model outputs (stage · anomalies · ad diagnosis)
        │  + deterministic policy signals (VP/AHR · disputes · withholding)
        ▼
   agent decision tree → workflow + ranked tasks
        │
        ▼
   structured signals → copy layer (Ollama summarize + localize · rules fallback)
        │
        ▼
   UI / alerts (real inferences replace mock)
        │  seller approves
        ▼
   executor → real task trigger
        │  outcome
        ▼
   revenue-impact metrics (recovered refunds · avoided cancellations · ROAS lift)
```

Phase 1 runs the same shape with **mock JSON** standing in for everything left of
the copy layer, **hardcoded copy** standing in for the LLM, and the executor as a
no-op.

---

## Metrics by phase

| Phase | What we measure | Why |
|-------|-----------------|-----|
| **Phase 1** | UX engagement — task clicks, approval-flow completions | Validate workflows resonate before building ML |
| **Phase 1.5** | Model performance — precision/recall on backtest | Confirm models are accurate enough to ship |
| **Phase 2** | Revenue impact — recovered refunds, avoided cancellations, improved ROAS | Prove the product makes sellers money |

---

## Dependencies (Phase 1.5+)

| Library | Use | Version policy |
|---------|-----|----------------|
| scikit-learn | Classifier, anomaly detection, preprocessing | pin in requirements |
| xgboost | Ad performance regressor (if used) | pin in requirements |
| pandas / pyarrow | Backtest parquet handling | pin in requirements |
| ollama (Python client) | Phase 2 copy layer — local LLM inference | pin in requirements |

Confirm versions via Context7 / PyPI at implementation time. Ollama server runs
alongside the app stack on the local inference node (`OLLAMA_HOST`, model tag in env).

---

## Out of scope (see EXECUTION.md)

Celery / multi-node workers, Kafka streams, creator↔shop matching, vendor scrapers,
Seller Center scraping, buyer PII, realtime unofficial streams, `src/` folder
reshaping. The Phase 2 target architecture (real APIs + inference pipeline) is
detailed in `architecture/target-v2.md`, **published at the end of Phase 1.5**.
