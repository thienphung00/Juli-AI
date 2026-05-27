# Architecture Context Reference

Quick reference for mapping features to the AI POS system's architectural layers.

## Layer Map

| Layer | Components | When to Involve |
|-------|-----------|-----------------|
| 1. API & Connector | FastAPI, Celery, Redis, SQLAlchemy | External POS integrations, webhooks, data sync |
| 2. AI Gateway | LiteLLM | Any AI model call, cost tracking, rate limiting |
| 3. Hybrid AI Model | Gemini Flash, Claude, GPT-4o, Ollama | Model selection, prompt design, embeddings |
| 4. Interface | Next.js, shadcn/ui, Supabase, Recharts | User-facing features, dashboards, workflows |
| 5. Caching | Redis, LiteLLM Semantic Cache, PostgreSQL | Performance, repeated queries, analytics |
| 6. Data Architecture | PostgreSQL, Redis, Cloudflare R2 | Schema changes, storage, exports |
| 7. Load Balancing & Hosting | Cloudflare, Nginx, Railway/Hetzner | Scaling, deployment topology |
| 8. Automation & Monitoring | Sentry, Grafana, Langfuse | Observability, error tracking, AI tracing |

## Cross-Layer Relationships

- Interface → AI Gateway → Model Layer (AI request flow)
- API Connectors → Data Architecture (normalized data storage)
- AI Gateway → Caching (semantic cache lookup)
- Monitoring → Gateway + Models (Langfuse traces)
- Data Architecture → Monitoring (R2 stores logs)

## Technology Stack Quick Reference

**Backend**: Python, FastAPI, Celery, SQLAlchemy
**Frontend**: Next.js, TypeScript, shadcn/ui, Recharts
**Database**: PostgreSQL (primary), Redis (cache/queue)
**AI**: LiteLLM gateway, Gemini Flash (default), Claude/GPT-4o (complex), Ollama (local)
**Infra**: Cloudflare, Nginx, Railway (MVP) → Hetzner (scale)
**Monitoring**: Sentry, Grafana + Loki + Prometheus, Langfuse
