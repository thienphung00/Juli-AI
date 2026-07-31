## Verdict Decisions #599

**overall:** PARTIAL

The #599 PRD correctly frames Decisions as a **scalability/cadence** problem (shared compute, dual cadence, anti-spam emission budget, dry-run isolation)—not a latency problem. Against as-built code and DB, almost all 3.5-B deliverables are **unimplemented**; only Phase 2 foundations exist (rules scoring pipeline, `action_cards` upsert, auth-gated manual refresh). The PRD itself is directionally sound but missing concrete AC for mutex, emission schema, cooldown indexes, and dry-run isolation—gaps that would misroute an Executor toward speed/cost optimizations.

### Objectives matrix

| Objective | Status | Evidence |
|-----------|--------|----------|
| **Shared compute trigger** — same shop job runs KPI precompute + rules scoring after material webhook / reconcile | **missing** | PRD: issue-599 Solution §1, Deep modules “Shared Compute Orchestrator”. Code: no Shared Compute Orchestrator; webhook handoff stops at ETL (`webhook.py` — no post-ETL enqueue). Scoring only via `POST /v1/action-cards/refresh` → Celery (`action_cards/dispatch.py`, `workers/tasks/action_card_refresh.py`). |
| **Rules scoring wire on continuous jobs** (not manual-only) | **partial** | PRD: themes §2, user stories 1–2, 12. Code: `run_daily_scoring_for_shop` + `persist_scoring_result` exist and work (`scoring/pipeline.py`, `action_cards/persist.py`); triggered only by manual refresh. `DAILY_SCORING_CRON_UTC` defined but unused (`scoring/schedule.py`; `action_cards/MODULE.md` L32). |
| **Decision emission budget** — max 5 active, 7-day workflow cooldown, weekly novelty 3; surfacing ≠ recomputation | **missing** | PRD: ADR-038 §6 defaults, user stories 3–4, 9–11, 17–19. Code/DB: zero emission module; no tests (`tests/**` — no “emission” matches). `list_active` returns all `status=active` rows with no cap (`repos.py` ActionCardsRepo). `persist_scoring_result` marks every recommendation `status="active"`. Live DB: 0 `action_cards` rows. |
| **Candidate vs surfaced separation** — recompute when budget suppresses surfacing | **missing** | PRD: user story 11, testing AC 19. Schema: single `status` column, no `candidate`/`surfaced`/`suppressed_reason` (`014_action_cards.py`, `db-key-tables.txt`). No promotion timestamps. |
| **Action Card persistence on compute** — idempotent `(shop_id, workflow_key)` upsert | **partial** | PRD: theme §2, user story 14. Code: `uq_action_cards_shop_workflow` + `ActionCardsRepo.upsert` + tests (`test_action_cards_contract.py`). Wired to manual refresh only; not compute-job triggered. |
| **Public Demo Decisions read API** — unauthenticated, server-bound reference shop, emission-gated | **missing** | PRD: theme §5, user stories 16–17, 21–22. Code: only auth-gated `GET /v1/action-cards` (`action_cards.py` — requires `get_active_shop`). No demo/public route under `backend/src/juli_backend/api/routes/`. |
| **Demo dry-run execution** — local records only, no Partner writes | **missing** (backend) | PRD: theme §4, user stories 5, 15, 20. Backend: `executions.py` + `execution/worker.py` enqueue real Celery tools via `run_tool_async` — no demo/dry-run gate. Demo app: client-side `localStorage` executions (`demo-state.tsx`, `lib/executions.ts`); `apps/demo/MODULE.md` — “no network requests”. |
| **Decision feed freshness metadata** — `computed_at`, promotion timestamps | **partial** | PRD: deep module + user story 16. Code: `metadata_json.computed_at` + payload `computed_at` on persist (`persist.py` L92–113); no promotion/surfacing timestamps; no public API exposure. |
| **Redis read-through for Decision envelopes** | **missing / inconsistent** | PRD interactions (issue-599 L90): “emission filter → Redis read-through → public Demo Decisions GET”. `action_cards/MODULE.md` L30–31: “No Redis; Postgres is the sole store.” No Decision cache layer in code. |
| **Observability** — scoring duration, emission drops (reason codes), dry-run starts | **missing** | PRD: user stories 23, Further Notes L119. Code: basic refresh/poll logs only; no emission drop reason codes. |
| **Graceful degradation** — last-good envelopes on scoring failure | **missing** | PRD: user story 24, testing negative paths. No cache/fallback path for Decisions. |
| **Rules-only; ML deferred Phase 4** | **covered** | PRD assumptions + user stories 25, 27. Code: rules pipeline only (`scoring/pipeline.py`); no ML inference in scoring path. |
| **Exit gate: continuous Fujiwa spine proven** | **missing** | PRD blocking notes. Live DB (`external-refs.md`, `db-key-tables.txt`): no medallion schemas; 1936 `webhook_raw_events`, 0 `processed_events`, 0 `action_cards`; flat `public.analytics_performance_intervals`. |
| **Hourly Mock + daily staggered reconcile refresh Decision candidates** | **partial (PRD only)** | PRD user story 30 includes daily staggered reconcile. Exit blocked on **A1 only** (Comment 1); A2 batch reconcile healing is architectural follow-on, not exit—**ambiguous in PRD body**, not in split comment. |

### dependency_graph: PASS (+ notes)

**Aligned across:** ADR-047 §3, ADR-048 L22–23, `split-comment-599.md`, issue-599 Comment 1, CONTEXT.md L103, A0/A1/A2 PRD bodies — graph is:

```
A0 (#598) → A1 (#601) → B (#599)
     └──→ A2 (#602)   [parallel; does not block B]
#600 Track B ∥ fixtures until A1 contract
```

**Stale text (does not override Comment 1 / ADR-047):**
- Issue-599 **body** L7–8, L82, L102, L117 still say “**Phase 3.5-A must exit first**” / “blocked on Phase 3.5-A Analytics spine” without naming **A1 (#601)** explicitly.
- JSON export mirrors stale body; Comment 1 is the authoritative ADR-047 amendment.

**Implicit A0 dependency:** #599 is blocked on A1, which requires A0 medallion + serving gold shape — correct, not over-blocking on A2.

### scalability_gaps

1. **No emission budget persistence model** — PRD requires dual cadence (recompute vs surface) but `action_cards` has no `surfaced_at`, `suppressed_reason`, weekly novelty counter, or separate candidate/serving tables.
2. **No cooldown indexes** — 7-day per-`workflow_key` cooldown needs efficient lookup on terminal actions (`approved_at`/`executed_at`/dismiss); only `ix_action_cards_shop_status` exists.
3. **No shop compute mutex AC in #599** — ADR-038 §5a mandates per-shop mutex + #68 15-min debounce; A2 (#602) has speed/batch mutex AC; **#599 silent** on inheriting mutex for KPI+scoring shared jobs → webhook bursts could stampede scoring.
4. **Redis vs Postgres SoT conflict** — #599 interaction diagram implies Redis read-through for Decisions; ADR-021/action_cards module is Postgres-only with no envelope cache contract.
5. **No public Demo API** — Track B (#600) and #599 backend contract disconnected; no swap path spec beyond “stable envelope shapes.”
6. **Dry-run not isolated from production execution** — `tool_executions` + `enqueue_approved_tool` → `run_tool_async` is the only backend execution path; no demo guard.
7. **Reconcile scope ambiguity** — User story 30 mentions daily staggered reconcile (A2) without stating it is post-exit enhancement; agents may block #599 on A2.
8. **As-built poll coupling in refresh** — `run_action_card_refresh` optionally runs full Fujiwa poll (`maybe_poll_tiktok_data`) — opposite of A1 “targeted fetch, not full poll” scalability shape.

### agent_misroute_risks

| Risk | Why |
|------|-----|
| Optimize **A1 “Speed” latency** instead of **emission cadence** | “Speed layer” naming + no explicit “do not throttle KPI compute” AC in #599 body |
| **Skip scoring** on webhook coalesce to “save cost” | Emission budget applies to **surfacing only** (user story 11) — easy to misread as “don’t score” |
| **Cap DB rows at 5** instead of dual-layer candidate/surfaced | `list_active` + persist-all-active pattern invites wrong fix |
| Wire dry-run through **`/v1/executions`** | Existing auth execution API calls Partner tools; #600 UI is local-only today |
| **Block #599 on A2** for user story 30 reconcile healing | Daily staggered reconcile is A2; exit is A1-only |
| Treat **Redis as Decision SoT** | Conflicting PRD interaction vs ADR-021 MODULE |
| **Separate Decision ingest pipeline** | Explicitly out of scope, but manual refresh + poll path exists as temptation |
| Implement emission in **Demo UI** (#600) | #600 owns UX only; emission is backend #599 — no AC preventing UI-side caps |

---

## Verdict Demo UI #600

**overall:** PASS

**objectives_matrix:**

| Objective | Status | Evidence |
|-----------|--------|----------|
| Parallel with Backend CDP; do not block on #599 | **covered** | issue-600 L142–143, split-comment-600; Decisions UX ships on fixtures |
| Consume **serving gold** `payload.kpis` when A1 ready | **covered** | Assumptions L26–27, coupling table L141; interim contract-shaped fixtures allowed |
| **Do not block** on A2 or #599 | **covered** | split-comment-600 L10; issue-600 L174 Out of Scope |
| Five Demo Main KPIs (ADR-049) | **partial (PRD locked, code lagging)** | PRD/user stories 1–8. Code: `main-kpis.ts` still ADR-023 six keys (SPS, net-revenue, ROAS…); `mock-data.ts` fixtures |
| Decisions automation UX (glow, no confidence, Juli-handles-all, progress cards) | **covered in PRD** | Deep modules table; implementation tracked in #600, not backend |
| Dry-run only, no Partner writes | **covered** | User story 32; client-side executions; review copy explicitly states no TikTok API |
| No backend scope bleed into A0–A2 | **covered** | Out of Scope L173–174; “consume read API contracts only” L197 |
| Fixture layer swappable for live API | **covered** | Interim fixture module; `decisions-recommendations.test.tsx` asserts no `fetch` calls |

**dependency_graph:** PASS — `#600 ∥ A0/A1/A2/#599`; live Analytics swap after A1; fixtures until then.

**scope_bleed:** Minimal and intentional — #600 owns **UI dry-run router** (local records, URL resolution); #599 owns **backend** public read API + server-side dry-run when wired. No A0–A2 implementation in #600.

**scalability note:** #600 correctly avoids implementing emission caps in UI (backend #599 responsibility). Risk: if Track B ships before #599, sellers see static fixture list with no emission-gated count — PRD acknowledges (issue-599 risks L120).

---

## Decisions roadmap integrity (598–602 graph impact on #599)

| Node | Impact on #599 |
|------|----------------|
| **A0 (#598)** | Required indirect prerequisite — medallion + `gold.kpi_envelopes` contract before A1 can populate KPIs that scoring must stay aligned with. Does **not** block #599 directly. |
| **A1 (#601)** | **Hard gate** — shared compute speed path + five Demo KPIs must exit before #599 starts. Correct: Decisions attach to same orchestrator after serving gold is live on webhook path. |
| **A2 (#602)** | **Does not block #599** — fleet batch reconcile + dual budgets parallel after A0. When A2 lands, same orchestrator should run scoring branch too (user story 30), but #599 exit should not wait on fleet reconcile. |
| **#600 Track B** | Parallel — fixture-backed Decisions UX; feed freshness waits on #599. |

**Graph integrity:** PASS — ADR-047 split resolves the prior monolithic #598 blocker that would have forced #599 to wait on batch fleet scope.

**Integrity gaps for #599:**
- Issue body still references monolithic “3.5-A” blocking language.
- A1 mentions #68 debounce as risk but not as shared-job AC; A2 has mutex AC that #599 should inherit for KPI+scoring jobs.
- Medallion not migrated (`external-refs.md`) — entire graph is pre-implementation.

---

## Recommendations (max 8)

1. **Amend #599 issue body** — replace “Phase 3.5-A must exit first” with “**blocked on A1 Speed (#601)** per ADR-047”; sync Further Notes blocking line.
2. **Add explicit AC: shop-scoped compute mutex** — one in-flight shop job for KPI+scoring; inherit ADR-038 #68 debounce; scoring branch must not create a second Decision-only enqueue path.
3. **Specify emission persistence schema** — e.g. `candidate` vs `surfaced` status (or `gold.decision_envelopes` + `action_cards` candidates); document promotion timestamps and weekly novelty counter storage.
4. **Add cooldown indexes** — composite index on `(shop_id, workflow_key, approved_at DESC)` or terminal-action table for 7-day gate queries at scale.
5. **Resolve Redis contract** — Postgres SoT for candidates; Redis read-through **only** for public emission-gated GET envelopes; amend #599 interactions diagram to match ADR-021.
6. **Add dry-run isolation AC** — public Demo approve/execute must **not** call `/v1/executions`, `enqueue_approved_tool`, or `run_tool_async`; separate demo execution module with CI guard.
7. **Clarify user story 30** — batch reconcile (A2) refreshes Decision **candidates** when orchestrator runs, but is **not** a #599 exit gate; exit remains A1 speed path only.
8. **Publish public Demo Decisions envelope contract** (for #600 swap) — emission-gated list shape, `computed_at`, masked fields, max-5 active — mirror ADR-046 `payload.kpis` pattern so Track B fixture swap requires no IA change.
