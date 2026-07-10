# Agent runtime

Meta Agent optimization loop — harness configuration, CI artifact generators, validate
gates, and versioned runtime JSON ([ADR-003](../docs/adr/003-ai-native-cicd-policy.md)).

## Layout

| Path | Purpose |
|------|---------|
| [`config/`](config/) | `agent-runtime.config.yml`, `harness-editable.yml`, `harness-safelist.yml` |
| [`artifacts/`](artifacts/) | Review, validation, implementation, optimization, release JSON (committed) |
| [`scripts/`](scripts/) | `build_runtime.py`, `harness_config.py`, `harness_optimizer.py`, `ci/`, `validate/` |
| [`docs/`](docs/) | Architecture, artifact contracts, benchmarks, JSON schemas |
| [`templates/`](templates/) | `context-plan-template.md` (harness-editable target) |

**Not included:** `backend/src/juli_backend/ai/artifacts/` — ML model training output (separate domain).

## Quick commands

```bash
# Build effective runtime from config
python agent-runtime/scripts/build_runtime.py

# List harness-editable fields
python agent-runtime/scripts/harness_config.py list-targets

# Dry-run optimization proposal for an issue
python agent-runtime/scripts/harness_optimizer.py propose --issue <n>

# Generate validation artifact (runs all validate gates)
python agent-runtime/scripts/ci/generate_validation_artifact.py --issue <n>
```

Canonical architecture: [`docs/agent-runtime.md`](docs/agent-runtime.md).
