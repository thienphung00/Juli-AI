# Feature Specifications

Per-feature discovery output from the `discover` skill lives in
`docs/features/<feature-name>/`:

| File | Purpose |
|------|---------|
| `PRD.md` | Business requirements and acceptance criteria |
| `architecture.md` | System design for the feature |
| `api-contracts.md` | HTTP/API schemas (when applicable) |
| `db-changes.md` | Migrations and data model notes |
| `edge-cases.md` | Failure modes and mitigations |
| `ai-eval-plan.md` | Model evaluation plan (AI features only) |

Cross-cutting architecture: [`docs/architecture/map.md`](../architecture/map.md).
Data source constraints: [`docs/architecture/data-sources.md`](../architecture/data-sources.md).
