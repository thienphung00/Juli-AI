# AI POS System Architecture - Mermaid Graph

Cross-layer relationship diagram showing how each architectural layer connects and communicates.

```mermaid
graph LR
    %% Core
    ROOT["AI POS System<br/>Event-driven Architecture"]

    %% Layer 1: API & Connector
    subgraph L1["1. API & Connector Layer"]
        L1_CONN["Connectors<br/>(KiotViet, GrabFood)"]
        L1_MAPPER["Mapper → Unified Schema"]
        L1_TECH["FastAPI + Celery + Redis + SQLAlchemy"]
    end

    %% Layer 2: AI Gateway
    subgraph L2["2. AI Gateway Layer"]
        L2_LITE["LiteLLM"]
        L2_FEAT["Model Abstraction<br/>Retries / Fallback<br/>Cost Tracking / Rate Limiting"]
    end

    %% Layer 3: Hybrid AI Model
    subgraph L3["3. Hybrid AI Model Layer"]
        L3_T1["Tier 1: Gemini Flash<br/>90-95% requests"]
        L3_T2["Tier 2: Claude / GPT-4o<br/>Complex reasoning"]
        L3_T3["Tier 3: Ollama / vLLM<br/>Local embeddings"]
    end

    %% Layer 4: Interface
    subgraph L4["4. Interface Layer"]
        L4_DASH["A. AI Dashboard<br/>Summaries, Alerts"]
        L4_WORK["B. Guided AI Workflows<br/>Pre-packaged Skills"]
        L4_CHAT["C. Chat<br/>Secondary Interface"]
        L4_TECH["Next.js + shadcn/ui<br/>Supabase + Recharts"]
    end

    %% Layer 5: Caching
    subgraph L5["5. Caching Layer"]
        L5_REDIS["Redis<br/>In-memory Cache"]
        L5_LLMCACHE["LiteLLM Semantic Cache"]
        L5_PG["PostgreSQL<br/>Long-term Analytics"]
    end

    %% Layer 6: Data Architecture
    subgraph L6["6. Data Architecture"]
        L6_PG["PostgreSQL<br/>Orders, Customers, Reports"]
        L6_REDIS["Redis<br/>Queues, Sessions"]
        L6_R2["Cloudflare R2<br/>Exports, Logs, AI Artifacts"]
    end

    %% Layer 7: Load Balancing & Hosting
    subgraph L7["7. Load Balancing & Hosting"]
        L7_CF["Cloudflare"]
        L7_NGINX["Nginx Load Balancer"]
        L7_WORKERS["FastAPI Workers"]
        L7_MVP["MVP: Railway"]
        L7_SCALE["Scale: Hetzner VPS"]
    end

    %% Layer 8: Automation & Monitoring
    subgraph L8["8. Automation & Monitoring"]
        L8_SENTRY["Sentry<br/>Error Tracking"]
        L8_GRAFANA["Grafana Loki + Prometheus"]
        L8_LANGFUSE["Langfuse<br/>AI Traces"]
        L8_FLOW["Error → Sentry → Cursor → Draft PR → Human Review"]
    end

    %% Hierarchical connections from root
    ROOT --> L1
    ROOT --> L2
    ROOT --> L3
    ROOT --> L4
    ROOT --> L5
    ROOT --> L6
    ROOT --> L7
    ROOT --> L8

    %% Internal connections
    L1_CONN --> L1_MAPPER
    L7_CF --> L7_NGINX --> L7_WORKERS

    %% Cross-layer relationships
    L1 -- "normalized data" --> L6
    L1 -- "task queue" --> L5_REDIS
    L4 -- "AI requests" --> L2
    L2 -- "routes workloads" --> L3
    L2 -- "semantic cache" --> L5_LLMCACHE
    L3 -- "responses cached" --> L5
    L4 -- "reads data" --> L6
    L4 -- "realtime via Supabase" --> L6_PG
    L5_PG -- "same store" --> L6_PG
    L5_REDIS -- "same store" --> L6_REDIS
    L7 -- "hosts" --> L1
    L7_WORKERS -- "processes" --> L1_TECH
    L8_SENTRY -- "monitors" --> L1
    L8_LANGFUSE -- "traces" --> L2
    L8_LANGFUSE -- "traces" --> L3
    L8_GRAFANA -- "monitors" --> L7
    L6_R2 -- "stores logs for" --> L8

    %% Styling
    classDef root fill:#6366f1,stroke:#4f46e5,color:#fff,font-weight:bold
    classDef layer1 fill:#3b82f6,stroke:#2563eb,color:#fff
    classDef layer2 fill:#06b6d4,stroke:#0891b2,color:#fff
    classDef layer3 fill:#10b981,stroke:#059669,color:#fff
    classDef layer4 fill:#f59e0b,stroke:#d97706,color:#000
    classDef layer5 fill:#ef4444,stroke:#dc2626,color:#fff
    classDef layer6 fill:#ec4899,stroke:#db2777,color:#fff
    classDef layer7 fill:#6366f1,stroke:#4f46e5,color:#fff
    classDef layer8 fill:#14b8a6,stroke:#0d9488,color:#fff

    class ROOT root
    class L1_CONN,L1_MAPPER,L1_TECH layer1
    class L2_LITE,L2_FEAT layer2
    class L3_T1,L3_T2,L3_T3 layer3
    class L4_DASH,L4_WORK,L4_CHAT,L4_TECH layer4
    class L5_REDIS,L5_LLMCACHE,L5_PG layer5
    class L6_PG,L6_REDIS,L6_R2 layer6
    class L7_CF,L7_NGINX,L7_WORKERS,L7_MVP,L7_SCALE layer7
    class L8_SENTRY,L8_GRAFANA,L8_LANGFUSE,L8_FLOW layer8
```

## Cross-Layer Relationships

| From | To | Relationship |
|------|-----|-------------|
| Interface (4) | AI Gateway (2) | Sends AI requests |
| AI Gateway (2) | Model Layer (3) | Routes workloads by tier |
| AI Gateway (2) | Caching (5) | Semantic cache lookup |
| API Connectors (1) | Data Architecture (6) | Stores normalized data |
| API Connectors (1) | Caching (5) | Task queue via Redis |
| Interface (4) | Data Architecture (6) | Reads operational data |
| Load Balancing (7) | API Layer (1) | Hosts and routes traffic |
| Monitoring (8) | Gateway (2) + Models (3) | Langfuse traces AI calls |
| Monitoring (8) | Hosting (7) | Grafana monitors infra |
| Data Architecture (6) | Monitoring (8) | R2 stores logs |
| Caching (5) | Data Architecture (6) | Shares Redis + PostgreSQL |
