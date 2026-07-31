## PRD split update (ADR-047)

Analytics CDP **3.5-A** is now three slices: **A0 Foundation ([#598](https://github.com/thienphung00/Juli-AI/issues/598))**, **A1 Speed ([#601](https://github.com/thienphung00/Juli-AI/issues/601))**, **A2 Batch ([#602](https://github.com/thienphung00/Juli-AI/issues/602))**.

### Blocking dependency change

**This issue (#599) is blocked on A1 Speed (#601)** — continuous KPI envelopes from the webhook-first speed path — **not** on A2 Batch (#602) or full A0+A2.

```
A0 (#598) → A1 (#601) → B (#599 this issue)
     └──→ A2 (#602)   [parallel OK; does not block B]
```

Decisions still attach to the **same Shared Compute trigger** after serving gold is stable on the speed path. See [ADR-047](docs/adr/047-cdp-lambda-layers-prd-split.md).
