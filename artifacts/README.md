# CI/CD Artifacts

Machine-readable outputs for the AI-native skill chain ([ADR-003](../docs/decisions/003-ai-native-cicd-policy.md)).

| Directory | Producer | Consumer |
|-----------|----------|----------|
| `reviews/` | `review` skill, `generate_review_artifact.py` | `validate` skill, `pr.yml` |
| `validation/` | `validate` skill, `generate_validation_artifact.py`, nightly audits | `ship` skill, `pr.yml` |
| `releases/` | `ship` skill, `release.yml`, `generate_release_artifact.py` | Rollback / hotfix agents |

Schemas: [`docs/ci/implementation-guide.md`](../docs/ci/implementation-guide.md).

Commit artifacts on feature branches so CI can verify them. Do not edit a review artifact
from the `validate` skill — regenerate via `review` if findings change.
