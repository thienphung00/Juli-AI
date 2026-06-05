# Feature Specifications

Per-feature folders under `docs/features/<feature-name>/` are **optional historical
attachments** — not the output of the `discover` skill.

## Where specs live today

| Need | Canonical source |
|------|------------------|
| Phases, slices, gates, in/out scope | [`EXECUTION.md`](../../EXECUTION.md) |
| Technical design (agent tree, pipeline, ML, executor) | [`docs/system-design.md`](../system-design.md) |
| Module graph | [`docs/architecture/map.md`](../architecture/map.md) |
| Data sources | [`docs/architecture/data-sources.md`](../architecture/data-sources.md) |
| Architecture decisions | [`docs/decisions/`](../decisions/) |
| Vendor API reference | `docs/<vendor>_api/` (`api-docs` skill) |
| Platform features & policy | `docs/<vendor>_platform/` (`platform-docs` skill) |
| PRD for implementation | GitHub issue from `to-prd` skill |

`discover` updates the canonical docs above. `to-prd` files the PRD as a GitHub issue.
Copying a PRD into `docs/features/<name>/PRD.md` is optional and only when explicitly requested.

## Legacy feature folders

| Feature | Status | Docs |
|---------|--------|------|
| mvp_1.0 | Pre-rescope artifact | [`mvp_1.0/`](mvp_1.0/) — superseded by `EXECUTION.md` + `system-design.md` |
| Nav redesign | Historical / pre-rescope | Removed — out of scope per `EXECUTION.md` |

The product is scoped to **seller-money** workflows (New Seller Copilot, Revenue Leakage
Detection, Growth Copilot). Cross-cutting architecture:
[`docs/architecture/map.md`](../architecture/map.md).
