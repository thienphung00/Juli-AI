# Blueprint Examples

## Example 1: AI Inventory Forecasting

### User Request
> "Add AI inventory forecasting."

### Clarifying Questions Asked

1. Which POS systems provide inventory data? → KiotViet (primary), GrabFood (secondary)
2. Real-time or batch forecasting? → Batch (daily), with on-demand refresh
3. Forecast horizon? → 7-day and 30-day
4. How accurate must predictions be? → MAPE < 20% for top 80% SKUs
5. Human approval required? → Yes, for auto-reorder suggestions
6. Which AI model tier? → Tier 1 (Gemini Flash) for predictions, Tier 2 for anomaly explanation
7. What happens on AI failure? → Fall back to simple moving average, alert owner

### Generated Docs

```
/context/features/ai-inventory-forecasting/
  PRD.md
  architecture.md
  api-contracts.md
  db-changes.md
  edge-cases.md
  ai-eval-plan.md
```

### Key Architecture Decision

- Batch pipeline via Celery scheduled tasks
- Predictions cached in PostgreSQL (analytics store)
- Dashboard widget via Recharts time series
- Langfuse traces for prediction quality monitoring

---

## Example 2: GrabFood Order Sync

### User Request
> "Connect GrabFood orders."

### Clarifying Questions Asked

1. Webhook or polling? → Webhook (GrabFood pushes)
2. Which order fields map to unified schema? → Documented in mapper
3. Duplicate detection? → Idempotency key on GrabFood order ID
4. What if webhook delivery fails? → GrabFood retries 3x, we implement dead-letter queue
5. Real-time sync to dashboard? → Yes, via Supabase realtime

### Generated Docs

```
/context/features/grabfood-order-sync/
  PRD.md
  architecture.md
  api-contracts.md
  db-changes.md
  edge-cases.md
```

---

## Example 3: Customer Segmentation

### User Request
> "Segment customers by behavior."

### Clarifying Questions Asked

1. What behaviors? → Purchase frequency, average order value, recency
2. How many segments? → AI-determined (3-7 clusters)
3. Update frequency? → Weekly batch
4. Output format? → Dashboard view + API for campaign targeting
5. Which data sources? → Order history (PostgreSQL), customer profiles

### Key Decisions

- RFM model first (simple), then AI clustering (Tier 3 embeddings)
- Segments stored as customer attributes in PostgreSQL
- Exposed via REST API for external campaign tools
