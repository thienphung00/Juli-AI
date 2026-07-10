# Documentation Index

Read **one tier at a time.** Do not load peer files unless the routing table below says so.

## Layout

| Category | Path | Contents |
|----------|------|----------|
| Architecture | [`architecture/`](architecture/) | System design, module map, agent runtime, data sources |
| API & schemas | [`api/`](api/) | Canonical entity schemas, feature store |
| Deployment | [`deployment/`](deployment/) | CI implementation guide, troubleshooting |
| Runbooks | [`runbooks/`](runbooks/) | VPS wiring, frontend/backend deploy, smoke sign-off |
| ADRs | [`adr/`](adr/) | Architecture decision records |
| Product | [`product/`](product/) | Phase docs, feature PRDs, design system |
| ML | [`ml/`](ml/) | KPI techniques, visual layer spec |
| Integrations | [`integrations/`](integrations/) | TikTok API + platform policy docs |
| Handoffs | [`handoffs/`](handoffs/) | Agent session handoffs (operational) |

## Tier 0 — Execution (always first)

| File | Owns |
|------|------|
| [`EXECUTION.md`](../EXECUTION.md) | Phases, slices, exit gates, in/out scope, governance, **which doc to open next** |

## Tier 1 — Component context (read ONE based on task)

| If your task touches… | Read | Owns (and only this) |
|---------------------|------|----------------------|
| Subsystem behavior, pipeline stage envelopes, ML promotion thresholds | [`architecture/system-design.md`](architecture/system-design.md) | How components interact; JSON envelopes; subsystem phase matrix |
| External data availability by phase | [`architecture/data-sources.md`](architecture/data-sources.md) | Source matrix; phase gating; forbidden sources |
| Deployed modules, paths, endpoints | [`architecture/map.md`](architecture/map.md) | As-built module registry + target layout |
| Repo restructure, path mapping, migration sequence | [`architecture/migration-plan.md`](architecture/migration-plan.md) | Current → target path mapping; migration PR sequence |
| Phase 2 pipeline validation — stack, schedule | [`product/phases/phase-2-mvp.md`](product/phases/phase-2-mvp.md) | Backend pipeline; daily batch; rules copy; no production deploy |
| Phase 2.5 deployment architecture | [`product/phases/phase-2.5-deployment.md`](product/phases/phase-2.5-deployment.md) | Monorepo layout, domains, package boundaries |
| Phase 3 Landing + Interactive Demo | [`product/phases/phase-3-landing-demo.md`](product/phases/phase-3-landing-demo.md) | Mock demo IA (Home + Actions); no login |
| Phase 4.5 real-time infrastructure | [`product/phases/phase-4.5-realtime.md`](product/phases/phase-4.5-realtime.md) | Webhooks, polyglot, event-driven (when justified) |
| KPI charts, T1–T8 techniques | [`ml/ml_layer.md`](ml/ml_layer.md) | Per-KPI technique mapping |
| Home rendering, advisory signals | [`ml/visual_layer.md`](ml/visual_layer.md) | Chart + signal spec |
| Workflow → action taxonomy | [`product/execution_layer.md`](product/execution_layer.md) | Workflow IDs and routing |
| Entity schemas, features, synthetic data | [`api/data-models/`](api/data-models/README.md) | Canonical schemas only |
| TikTok API field maps | [`integrations/tiktok_api/endpoints.md`](integrations/tiktok_api/endpoints.md) | Ingestion layer only |
| TikTok API family names | [`integrations/tiktok_api/api-families.md`](integrations/tiktok_api/api-families.md) | Seller, Products, Promotion, … |
| Pre-MVP history | [`product/phases/phase-1-completed.md`](product/phases/phase-1-completed.md) | Historical summary only |
| Deploy runbooks | [`runbooks/`](runbooks/) | Step-by-step VPS, frontend, backend, smoke sign-off |
| CI gates | [`deployment/implementation-guide.md`](deployment/implementation-guide.md) | Validate pipeline, artifact contracts |

### Historical phase docs (not authoritative)

| File | Status |
|------|--------|
| [`product/phases/phase-3-vision.md`](product/phases/phase-3-vision.md) | Superseded by `phase-3-landing-demo.md` + `phase-4.5-realtime.md` |
| [`product/phases/phase-4-beta-launch.md`](product/phases/phase-4-beta-launch.md) | Superseded by `EXECUTION.md` Phase 4 |
| [`product/phases/phase-5-public-launch.md`](product/phases/phase-5-public-launch.md) | Superseded by `EXECUTION.md` Phase 5 |

## Tier 2 — Decisions (read when you need the *why*)

| File | Owns |
|------|------|
| [`adr/README.md`](adr/README.md) | ADR index |
| `adr/NNN-*.md` | Rationale, options considered, consequences for one decision |

ADRs do not repeat Tier 1 envelopes or EXECUTION slices. Tier 1 files link to ADRs by number only — they do not re-state ADR prose.

## Authority chain

```
Code  >  EXECUTION.md  >  Tier 1 (component doc for your domain)  >  Tier 2 (ADR)
```

`map.md` describes deployed reality and target layout. `migration-plan.md` owns the path mapping.
When code and EXECUTION disagree, update EXECUTION in the same PR.
