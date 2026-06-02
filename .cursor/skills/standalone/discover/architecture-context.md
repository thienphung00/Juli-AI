# Architecture Context Reference

Quick reference for mapping features to Juli-AI layers. The canonical module
list and dependency graph live in [`docs/architecture/map.md`](../../../../docs/architecture/map.md).
External data constraints live in
[`docs/architecture/data-sources.md`](../../../../docs/architecture/data-sources.md).

## Layer Map

| Layer | Path(s) | When to Involve |
|-------|---------|-----------------|
| **Integrations** | `src/integrations/tiktok/` | TikTok API client, OAuth, signing, rate limits, resource clients |
| **Services** | `src/services/webhook/`, `src/services/polling/` | Webhook ingest, background sync workers |
| **Intelligence** | `src/intelligence/scoring/` | Post-stream scoring, anomalies, sentiment (read-only vs `src/data`) |
| **Data** | `src/data/` | Models, repos, Alembic migrations, shop scoping |
| **Auth** | `src/auth/` | Supabase JWT, TikTok OAuth lifecycle |
| **API** | `src/api/` | Versioned FastAPI routes, shop-scoped handlers |
| **Interface** | `web/`, `ios/` | Dashboard and native app (Vietnamese UX, phone OTP) |
| **Alerts** (planned) | _TBD_ | Zalo OA, Telegram, FCM delivery |
| **Infrastructure** (planned) | _TBD_ | Railway, Vercel, GitHub Actions |

## Cross-Layer Flows

```
TikTok API / webhooks
  → integrations/tiktok + services/webhook|polling
  → src/etl (validation → dedup → persist)
  → src/data (Supabase)
  → src/api ← web / ios
  → src/intelligence/scoring (read-only analytics)
```

## Technology Stack

| Concern | Choice |
|---------|--------|
| Backend | Python 3, FastAPI, Celery, httpx |
| Database | Supabase Postgres, SQLAlchemy async, Alembic |
| Ingest | In-process handoff → `EtlConsumer` (v1.5) |
| Cache / queue | Redis + Celery (v2.0 only) |
| Auth | Supabase phone OTP + TikTok OAuth |
| Web | Next.js (`web/`) |
| iOS | SwiftUI (`ios/`) |
| AI (post-MVP) | OpenAI / rules engine per execution plan — not LiteLLM gateway in repo today |

## Discovery Outputs

Feature specs produced by `discover` live under `docs/features/<feature-name>/`
(see `discover/SKILL.md`). Domain-wide TikTok integration docs remain under
`docs/tiktok_api/`.
