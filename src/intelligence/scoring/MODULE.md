# Module: intelligence/scoring

## Responsibility
Post-stream intelligence layer that scores livestream sessions, detects
revenue/cost anomalies, derives estimated viewer retention curves, and
classifies Vietnamese comment sentiment. All scoring is computed from
post-stream summary data available via the TikTok Shop Official API (#3) —
no realtime in-stream telemetry is consumed (see `data-sources.md` row #7).

## Public Interface

### Scoring
- `score_livestream(session, livestream_id) -> LivestreamScore` — 0–100 weighted
  grade using revenue-per-viewer, conversion rate, revenue-vs-shop-avg, and
  duration efficiency. Comparable across sessions for the same shop.
- `LivestreamScore` — dataclass with `grade: int` and `breakdown: dict[str, float]`

### Anomaly Detection
- `detect_anomalies(session, shop_id) -> list[Anomaly]` — detects ≥2σ deviations
  in revenue, order count, and viewer count vs. historical norms. Uses population
  stddev with ≥30 data points; falls back to 7-point moving-average window below
  that threshold.
- `Anomaly` — dataclass with `metric`, `current_value`, `mean`,
  `deviation_sigma`, `livestream_id`

### Retention Curve
- `get_stream_retention(session, livestream_id) -> list[RetentionPoint]` — minute-
  by-minute estimated viewer retention derived from post-stream summary data using
  exponential decay (λ set for ~30% retention at stream end).
- `RetentionPoint` — dataclass with `minute: int`, `viewers: int`

### Sentiment Analysis
- `analyze_comments(comments) -> SentimentResult` — lexicon-based Vietnamese
  sentiment classification with NFC Unicode normalization for diacritic handling.
- `SentimentResult` — dataclass with `total`, `positive_count`, `negative_count`,
  `neutral_count`, `overall` (one of `"positive"`, `"negative"`, `"neutral"`,
  `"mixed"`)

## Dependencies
- `sqlalchemy[asyncio]` — async DB queries (reads only; this module does not write)
- `src.data.models.Livestream` — post-stream summary data

## Invariants
- All functions are **read-only** against `src/data` — no writes, no migrations
- Scoring is **post-stream only** — never consumes live websocket data (forbidden
  per `data-sources.md` rows #7, #8)
- Anomaly detection uses population stddev (not sample) to avoid over-sensitivity
- When stddev=0 and current value differs from mean, deviation is treated as
  infinite (always flagged)
- Retention curves are **estimates** — labeled as derived, not measured
- Audience demographics are limited to shop-scoped data (no cross-shop view)
- Sentiment lexicon is Vietnamese-focused; no external NLP service dependency

## Owners
- domain: intelligence
- code: src/intelligence/scoring/
