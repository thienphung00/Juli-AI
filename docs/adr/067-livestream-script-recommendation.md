# ADR-067: Livestream script recommendation — rule-based stage classification + LLM-personalized script catalog

**Status:** Accepted
**Date:** 2026-08-03
**Deciders:** grill-with-docs (Architect)

**Builds on:** [ADR-063](063-t10-inventory-reorder-engine.md)/[064](064-product-performance-classifier.md)/[066](066-t9-fee-adjusted-price-rule.md)
(real-algorithm-on-real-data posture, lazy-compute pattern).
**Does not change:** `ai/ranking/scorer.py::score_livestream` (reused as-is);
`copy_layer.py`'s Phase-4-deferred cloud LLM policy for **KPI advisory reasoning copy**
— that restriction is scoped to `build_workflow_reasoning_copy` (the T1–T10 visual-layer
signal explanations), not to this workflow-scoped script feature. Different surface,
different decision.

## Context

Live Room APIs are read-only for Juli (no execution surface exists or is planned —
confirmed: no `workflow_key` for Livestream anywhere in `WORKFLOW_TOOL_CATALOG`). So
"execution" here cannot be an API write; it has to be a human-followable script.

Verified real, populated data: `Livestream.viewer_count`, `.order_count`, `.revenue`,
`.start_time`/`.end_time` (via already-wired `LivestreamsResource` → `normalize_livestream`).
Verified dead columns: `peak_concurrent_viewers`, `click_count` (declared, never mapped —
same pattern as ADR-065's Settlement columns). Verified `ai/ranking/scorer.py::score_livestream`
only reads the real fields — safe to reuse unmodified. Verified a richer real-time data
family exists (`analytics/live_rooms/*` — Core Stats, View Trends with real per-minute
`TREND_ONLINE_VIEWER` points, Product Stats) but requires Creator OAuth
(`creator.data.live.read.public`) Juli hasn't built — logged as a future upgrade, not a
v1 blocker, consistent with ADR-063/066's posture on reachable-but-unbuilt data.

**Critical finding from the Academy corpus** (`nhan-phan-tich-hieu-sau-do-ai-tao-trong-live-4898053111744273.md`):
TikTok already ships a **real-time, in-LIVE AI coaching feature** (launched 2026-06-24,
currently limited-rollout), built around an official **6-stage structured sales cycle**,
each stage triggered by real-time metrics with a scripted action:

1. **Hâm nóng không khí** (Warm-up) — slow early traffic → opening script / gift event
2. **Lợi điểm bán hàng & ghim sản phẩm** — low PDP click-through → voice selling points, pin product
3. **Ưu đãi giá & ghim voucher** — high PDP interest/comments → pin voucher
4. **Thúc đẩy đơn hàng** — cart-adds without checkout → Flash Sale urgency
5. **Chuyển sản phẩm** — sold out + viewer requests → pin next product
6. **Lưu lượng giảm** — post-30-min drop-off → auto gift event

TikTok cites an internal SEA 2025 result: sellers using recommended scripts saw up to a
**7.38% GMV lift**. This is real, sanctioned platform content — not something to reinvent,
and not something Juli should compete with on its own turf (Juli has no real-time data
access; TikTok's tool does).

## Decision

**Juli's differentiation is pre-stream prep and post-stream retrospective, using
TikTok's own 6-stage vocabulary, personalized to the shop's own cross-session history —
which TikTok's reactive, session-local tool does not do.**

- **Score:** reuse `score_livestream` unmodified (shop-relative sigmoid scoring, real data).
- **Classify:** same Scale (≥70) / Fix (40–69) / Explore (<40 or insufficient history)
  tiers as ADR-064, applied to the most recently completed livestream for the shop.
- **Stage mapping** (weakest `score_livestream` sub-score → official TikTok stage):

  | Weak sub-score | Maps to | Script focus |
  |---|---|---|
  | `duration_efficiency` | Hâm nóng không khí (Warm-up) | Opening hook, pacing discipline |
  | `revenue_per_viewer` | Lợi điểm bán hàng & ghim sản phẩm | Sell harder on featured product |
  | `conversion_rate` | Thúc đẩy đơn hàng | Urgency cue (scripted line only — Juli cannot launch a real Flash Sale, read-only) |
  | `revenue_vs_avg` (overall) | Full-session review | Checklist across all stages |

  Scale-classified streams get the *strongest* sub-score's stage, framed as "keep doing this."

- **Rule-based + LLM hybrid generation**, mirroring the already-built (but orphaned)
  pattern in `ai/recommendations/engine.py::get_stream_optimization` — reused
  design, not new architecture:
  1. **Rule (deterministic):** weak/strong sub-score → stage → category lookup in a
     static script catalog (same shape as `kpi_catalog.py`'s `WORKFLOW_DISPLAY_NAMES` —
     a Python dict, not a DB table): `CATALOG[stage][category] -> list[template]`.
     Selection is deterministic (e.g. rotate by `livestream_id` hash) — always resolves
     to a concrete candidate line, never empty.
  2. **LLM (optional, quota-capped):** the selected template + real context (product
     name, shop name, the actual metric value that triggered it) is passed to an LLM to
     personalize the line. Reuses the existing daily-cap mechanism
     (`_count_daily_llm_calls`/`max_calls_per_day`) already coded in `engine.py`. On LLM
     unavailable, quota exhausted, or any generation error: **fall back to the raw
     catalog template verbatim** — never blocks, never returns empty.
  3. Catalog seed content prefers verbatim/adapted examples already present in the
     Academy corpus where TikTok published one (e.g., the engagement-stage example
     "Các bạn có câu hỏi nào không? Bình luận cho mình biết nhé!"); stages without a
     published example need Juli-authored seed lines — that authoring is an
     implementation-time task, not specified in this ADR.

- **New workflow_key, no API call:** one new key (naming/number TBD at `to-issues`) whose
  handler performs no TikTok API request — it only records that the seller
  received/acknowledged the script (same non-API precedent as `noop.ping`). Triggered
  standalone off the shop's most-recently-completed livestream — not folded into
  `VisualLayerDomain`/`ScoringSignals`, same minimal-blast-radius posture as ADR-063/064.

## Consequences

- This is the first live feature to use LLM-personalized copy outside the
  Phase-4-deferred KPI reasoning layer — explicitly scoped here to avoid confusion with
  that policy; `copy_layer.py`'s `CopySource = Literal["rules"]` constraint is unaffected.
- Real-time in-stream coaching (TikTok's own feature) is explicitly out of scope — Juli
  has no real-time data path and shouldn't build a worse copy of a feature TikTok already
  ships. If TikTok's feature reaches full rollout, Juli's differentiation narrows further
  to purely the cross-session historical view — worth revisiting then.
- `get_stream_optimization`/`ai/ranking` remain formally "legacy" (per their own
  MODULE.md framing, Creator-matching pivot) but this ADR reuses their *pattern*
  (rules+LLM quota fallback), not their code verbatim — the new implementation lives in
  the same lazy-compute, standalone-trigger shape as ADR-063/064/066, not inside the
  orphaned `ai/recommendations` module.
- Upgrading to real per-minute retention (`Get Live Room View Trends`) and richer
  Core Stats requires Creator OAuth — a real, larger integration project, logged here as
  future work, not blocking this ADR.

## Options considered

| Option | Outcome |
|--------|---------|
| Build real-time in-stream coaching to match/replace TikTok's tool | Rejected — no real-time data access; TikTok already ships this, better positioned |
| Rules-only script generation (no LLM), matching the Phase-4-deferred KPI copy policy | Rejected per user direction — rule-based + LLM hybrid explicitly requested for this workflow-scoped surface, distinct from the KPI reasoning layer |
| Invent original script content instead of grounding in the Academy corpus | Rejected — TikTok's own proven, sanctioned phrasing/framework exists and should be reused/adapted first |
| **Rule-selected catalog entry + optional quota-capped LLM personalization, TikTok's 6-stage vocabulary, pre/post-stream only (chosen)** | Real data, proven content model, clear differentiation from TikTok's native feature |
