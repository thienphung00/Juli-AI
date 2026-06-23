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
| Agent harness phases, agent ownership, executor domains, optimization loop | [`architecture/agent-runtime.md`](architecture/agent-runtime.md) | Agent-oriented runtime model; supersedes workflow-chain language in skills |
| Runtime artifact schemas, persistence, ADR-003 field mapping | [`architecture/agent-runtime-artifacts.md`](architecture/agent-runtime-artifacts.md) | Execution feedback JSON; producer/consumer routing; commit policy |
| Agent runtime benchmarks, task types A–D, scoring protocol | [`architecture/agent-runtime-benchmarks.md`](architecture/agent-runtime-benchmarks.md) | Unified benchmark framework; repeated-run protocol for optimization |
| Phase 2 pipeline validation — stack, schedule, Celery | [`phases/phase-2-mvp.md`](phases/phase-2-mvp.md) | Target stack; daily batch schedule; Celery execution |
| KPI charts, T1–T8 techniques | [`ml_layer.md`](ml_layer.md) | Per-KPI technique mapping |
| Home rendering, advisory signals | [`visual_layer.md`](visual_layer.md) | Chart + signal spec |
| Workflow → action taxonomy | [`execution_layer.md`](execution_layer.md) | Workflow IDs and routing |
| Entity schemas, features, synthetic data | [`data-models/`](data-models/README.md) | Canonical schemas only |
| TikTok API field maps | [`tiktok_api/endpoints.md`](tiktok_api/endpoints.md) | Ingestion layer only |
| Phase 3 first user testing (10 shops) | [`phases/phase-3-vision.md`](phases/phase-3-vision.md) | User behavior validation; PostHog; execution rate |
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

`map.md` describes deployed reality; `agent-runtime.md` describes harness routing and agent phases.
When code and EXECUTION disagree, update EXECUTION in the same PR.
