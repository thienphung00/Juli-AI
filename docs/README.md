# Documentation Index

Read **one tier at a time.** Do not load peer files unless the routing table below says so.

## Tier 0 — Execution (always first)

| File | Owns |
|------|------|
| [`EXECUTION.md`](../EXECUTION.md) | Phases, slices, exit gates, in/out scope, governance, **which doc to open next** |

## Tier 1 — Component context (read ONE based on task)

| If your task touches… | Read | Owns (and only this) |
|---------------------|------|----------------------|
| Subsystem behavior, pipeline stage envelopes, ML promotion thresholds | [`system-design.md`](system-design.md) | How components interact; JSON envelopes; subsystem phase matrix |
| External data availability by phase | [`architecture/data-sources.md`](architecture/data-sources.md) | Source matrix; phase gating; forbidden sources |
| Deployed modules, paths, endpoints | [`architecture/map.md`](architecture/map.md) | As-built module registry + target layout |
| Repo restructure, path mapping, migration sequence | [`architecture/migration-plan.md`](architecture/migration-plan.md) | Current → target path mapping; migration PR sequence |
| Phase 2 pipeline validation — stack, schedule | [`phases/phase-2-mvp.md`](phases/phase-2-mvp.md) | Backend pipeline; daily batch; rules copy; no production deploy |
| Phase 2.5 deployment architecture | [`phases/phase-2.5-deployment.md`](phases/phase-2.5-deployment.md) | Monorepo layout, domains, package boundaries |
| Phase 3 Landing + Interactive Demo | [`phases/phase-3-landing-demo.md`](phases/phase-3-landing-demo.md) | Mock demo IA (Home + Actions); no login |
| Phase 4.5 real-time infrastructure | [`phases/phase-4.5-realtime.md`](phases/phase-4.5-realtime.md) | Webhooks, polyglot, event-driven (when justified) |
| KPI charts, T1–T8 techniques | [`ml_layer.md`](ml_layer.md) | Per-KPI technique mapping |
| Home rendering, advisory signals | [`visual_layer.md`](visual_layer.md) | Chart + signal spec |
| Workflow → action taxonomy | [`execution_layer.md`](execution_layer.md) | Workflow IDs and routing |
| Entity schemas, features, synthetic data | [`data-models/`](data-models/README.md) | Canonical schemas only |
| Marketing / SEO / AEO keywords (Vietnamese) | [`marketing/keywords.md`](marketing/keywords.md) | Brand, feature, intent keywords; core ~40 set |
| Locale policy (VI user / EN dev) | [`marketing/locale-policy.md`](marketing/locale-policy.md) | Which language per surface |
| TikTok API field maps | [`tiktok_api/endpoints.md`](tiktok_api/endpoints.md) | Ingestion layer only |
| TikTok API family names | [`tiktok_api/api-families.md`](tiktok_api/api-families.md) | Seller, Products, Promotion, … |
| Pre-MVP history | [`phases/phase-1-completed.md`](phases/phase-1-completed.md) | Historical summary only |

### Historical phase docs (not authoritative)

| File | Status |
|------|--------|
| [`phases/phase-3-vision.md`](phases/phase-3-vision.md) | Superseded by `phase-3-landing-demo.md` + `phase-4.5-realtime.md` |
| [`phases/phase-4-beta-launch.md`](phases/phase-4-beta-launch.md) | Superseded by `EXECUTION.md` Phase 4 |
| [`phases/phase-5-public-launch.md`](phases/phase-5-public-launch.md) | Superseded by `EXECUTION.md` Phase 5 |

## Tier 2 — Decisions (read when you need the *why*)

| File | Owns |
|------|------|
| [`decisions/README.md`](decisions/README.md) | ADR index |
| `decisions/NNN-*.md` | Rationale, options considered, consequences for one decision |

ADRs do not repeat Tier 1 envelopes or EXECUTION slices. Tier 1 files link to ADRs by number only — they do not re-state ADR prose.

## Authority chain

```
Code  >  EXECUTION.md  >  Tier 1 (component doc for your domain)  >  Tier 2 (ADR)
```

`map.md` describes deployed reality and target layout. `migration-plan.md` owns the path mapping.
When code and EXECUTION disagree, update EXECUTION in the same PR.
