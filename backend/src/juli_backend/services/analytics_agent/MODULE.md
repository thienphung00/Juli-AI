# backend/src/juli_backend/services/analytics_agent

## Purpose

The analytics agent engine (batch-1120 T1): a Vietnamese seller question, or one of 5 templates,
becomes an intent, a Jev routing decision, a deterministic chain or data answer, a gated card draft
from Juli's recommendation engine, an explanation, and a stream of events. Public API:
`run(req, *, read_session_factory, llm, jev, sink, labels)`; contract in the batch notes
(`CONTRACT.md`). Pure read-only.

## Layers

| Module | Role |
|---|---|
| `types` | `AskRequest`, `Template` / `TEMPLATES`, ports (`LLMPort`, `JevPort`, `EventSink`, `DataPort`, `CardEnginePort`), `LabelTable`, `AnswerResult` |
| `routing` | intent parse (strict tool schema, restatement guard, cap 3), Jev routing questions, thresholds, cross-checks, lookup rules, `needs_choice` + resume from `pending`, product resolution |
| `chains` | orders / CTR / CTOR / GMV / profit+margin / ads / `cost_change`; step 0 freshness + coverage, formula (LMDI, rate/mix), scope, time, bottom-up fallback; `within_noise` decided at the bottom |
| `lookup` | data answers rendered by code (metric_total, top_products, daily_trend, channel_breakdown) |
| `advisor`, `levers` | the advise loop (#52/#53): `emit_plan` = lead + actions {lever, card_ref, why}; `levers` is the finding -> lever table as data (enum from `kinds.py` minus the out-set, tool-result tags); code validates schema, refs, card kind == lever and numbers only |
| `advisor_tools` | the advisor's tools (C1): `metrics`, `rank`, `opportunities`, `open_cards`, `calendar`, `draft_card(opportunity_id)`, `compare`; schemas generated from `metrics.registry` ids and the kinds table; every number is what `DataPort.metrics` (= `metrics.query.query`) returned |
| `compare` | C6: the `compare` block (event kind `compare`): exactly 4 priced options from OPP's `compare` / stored opportunities, one pick (highest Δ lợi nhuận as returned), lead names the figure; question type `compare_options` |
| `cards` | G1-G5, Jev picks actionable / kind / product / version, engine values via `CardEnginePort` |
| `writer` | writer prompt, alignment check, sanitiser, code template |
| `present` | path row, stop labels, status lines |
| `fmt`, `windows`, `mathx`, `labels` | Vietnamese formats + direction, comparison windows, formulas, per-platform labels |
| `data_service`, `cards_service` | the real adapters over the analytics services and the recommendation engine |
| `engine` | `run`: wires everything and emits the events |

## Rules

- Read-only: no write, no materialize, no `choose` / `create_manual`; sessions come from the caller's
  read-only factory and are rolled back. A card is a draft until T3's send creates it.
- No second formula: money and rates come from `shopee_analytics` (overview, channel split,
  metric-view, critical) and `shopee_recommendations` (generators, versions, result store).
- NULL is never 0; a source with data on < 50 % of the days is missing; unknown `o:*` sources render "Khác".
- The LLM only writes the explanation from pre-formatted values; every explanation passes the sanitiser;
  seller-facing numbers use `fmt` (8.728.160đ, 42,8%, 3,07%).
- Stock-outs are mentioned, never a card. COGS, fees, shipping and packaging are mentioned in
  `cost_change`, never a card.
