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
| Deployed modules, paths, endpoints | [`architecture/map.md`](architecture/map.md) | As-built module registry |
| MVP architecture diagram, daily UTC schedule, deployment stack | [`phases/phase-2-mvp.md`](phases/phase-2-mvp.md) | Target stack picture; batch schedule; Redis/Postgres roles |
| KPI charts, T1–T8 techniques | [`ml_layer.md`](ml_layer.md) | Per-KPI technique mapping |
| Home rendering, advisory signals | [`visual_layer.md`](visual_layer.md) | Chart + signal spec |
| Workflow → action taxonomy | [`execution_layer.md`](execution_layer.md) | Workflow IDs and routing |
| Entity schemas, features, synthetic data | [`data-models/`](data-models/README.md) | Canonical schemas only |
| TikTok API field maps | [`tiktok_api/endpoints.md`](tiktok_api/endpoints.md) | Ingestion layer only |
| Post-MVP real-time / polyglot / LIVE API | [`phases/phase-3-vision.md`](phases/phase-3-vision.md) | Phase 3 forward scope |
| Pre-MVP history | [`phases/phase-1-completed.md`](phases/phase-1-completed.md) | Historical summary only |

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

`map.md` describes deployed reality; when code and EXECUTION disagree, update EXECUTION in the same PR.
