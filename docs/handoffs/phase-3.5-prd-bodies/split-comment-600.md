## PRD split update (ADR-047)

Analytics CDP **3.5-A** split into **A0 ([#598](https://github.com/thienphung00/Juli-AI/issues/598))**, **A1 Speed ([#601](https://github.com/thienphung00/Juli-AI/issues/601))**, **A2 Batch ([#602](https://github.com/thienphung00/Juli-AI/issues/602))** per [ADR-047](docs/adr/047-cdp-lambda-layers-prd-split.md).

### Track B unchanged — parallel OK

**This issue (#600) remains parallel** with Backend CDP work:

- **Contract-shaped fixtures/mocks** may ship until **A1** populates live `gold.kpi_envelopes.payload.kpis` (five Demo KPI keys per ADR-049/046).
- **Do not block** on A2 Batch (#602) or 3.5-B Decisions (#599).
- A0 (#598) establishes serving gold **shape**; A1 (#601) delivers live envelope data for B′ five KPIs.

```
A0 (#598) → A1 (#601) → live envelope swap for Analytics cards
#600 Track B  ∥  fixtures until A1 contract
```
