# Machine Learning reference

Curated patterns for the 80% path. For library API details and churn-prone behavior,
use the **Context7 CLI** at Executor time when Focus/Meta selects it (see **Sources /
live Context7 pointers**). Load on demand — not always injected in full.

---

## 1. Module map (`backend/src/juli_backend/ai/`)

| Subpackage | Purpose |
|------------|---------|
| `dataset/` | Synthetic backtest parquet + manifest assembly |
| `features/` | Feature engineering from manifest paths |
| `seller_stage/` | Rules baseline + RandomForest trainer/inference |
| `anomaly/` | Buyer-behavior anomaly trainer/inference |
| `ad_performance/` | Ad ROAS trainer/inference |
| `artifacts/` | joblib publish/load, smoke tests, promotion gates |
| `ranking/`, `forecasting/`, `recommendations/` | Scoring/ranking helpers (phase-dependent) |

Each subpackage has a `MODULE.md`. Top-level overview:
[`backend/src/juli_backend/ai/README.md`](../../../backend/src/juli_backend/ai/README.md).

**Not in scope for ML executor:** `backend/src/juli_backend/api/` product routes,
`integrations/` vendor fetch, Postgres migrations/repos.

---

## 2. Dataset and feature pipeline

- **Assemble:** `assemble_backtest_dataset(output_dir, seed=…)` writes parquet +
  `manifest.json` with train/eval split boundaries.
- **Validate:** `validate_backtest_dataset` fail-fast on schema/enum drift.
- **Features:** `build_seller_stage_features(manifest, …)` and suite-specific builders;
  column contracts in `features/schema.py` (`SELLER_STAGE_FEATURE_COLUMNS`, etc.).
- **Determinism:** always pass explicit `seed` to dataset assembly and trainers.
- **No leakage:** eval rows must come from manifest eval partition only; never fit
  scalers/encoders on eval data inside tests meant to mirror production.

CLI: `python -m juli_backend.ai.dataset.cli assemble-backtest-dataset` (see MODULE).

---

## 3. Training, metrics, and golden fixtures

- **Trainers:** `train_seller_stage`, `train_anomaly`, `train_ad_performance` return
  `TrainResult` with `model`, `metrics`, `metrics_path`.
- **Stack:** pandas/numpy + sklearn (`RandomForestClassifier`, metrics helpers) in
  seller_stage/anomaly/ad_performance; rules baseline in `seller_stage/rules.py`.
- **Golden fixtures:** `seller_stage/fixtures.py` (`STAGE_BOUNDARY_FIXTURES`), similar
  patterns in `anomaly/fixtures.py` — port boundary cases from TS fixtures where noted.
- **Smoke:** `artifacts.run_smoke_test(suite, version)` loads joblib + runs golden
  inference; `run_all_smoke_tests` for CI breadth.

Example test pattern: `tests/unit/test_model_artifacts.py` — `tmp_path`, `seed=141`,
assemble → train → publish → load → smoke.

---

## 4. Artifact hygiene (joblib)

**Layout** (`models/` root, configurable via `models_root`):

```
models/
  seller_stage/{version}/model.joblib + metadata.json + metrics.json
  anomaly/{version}/model.joblib + metadata.json + metrics.json
  ad_performance/{version}/model.joblib + metadata.json + metrics.json
```

**Rules**

- Publish only through `artifacts.publish_model`; load only through `artifacts.load_model`.
- `metadata.json` carries `feature_schema_hash`, `promotion_status`, metrics snapshot.
- Tests use `tmp_path` — never write artifacts into repo `models/` during unit tests.
- Do not pickle train parquet paths or eval labels into metadata consumed at inference.
- On load failure raise `ArtifactLoadError` — tests should assert typed errors.

---

## 5. Leakage prevention and promotion gates

**Train/eval separation**

- Split is recorded in dataset manifest — trainers must respect `train_rows` / eval keys.
- Feature builders must not peek at eval labels when building train features.
- Wrong pattern (from sklearn docs): feature selection on full dataset before split.

**Promotion**

- `evaluate_promotion_status(suite, metrics)` → `promoted` | `experimental`
- Thresholds: `artifacts/thresholds.py` + per-suite `thresholds.py` (provisional until #142)
- Do not mark promoted in artifacts when metrics fail gates or phase forbids promotion
  (`EXECUTION.md`, `system-design.md`).

**Phase constraints**

- Phase 2: rules-based copy only; cloud LLM deferred (see `ai/README.md`).
- Offline backtest path only — no live TikTok inference in ML unit tests.

---

## 6. Test surfaces in repo

| Test file | Covers |
|-----------|--------|
| `tests/unit/test_model_artifacts.py` | publish/load/smoke/promotion |
| `tests/unit/test_seller_stage_trainer.py` | seller stage training |
| `tests/unit/test_anomaly_trainer.py` | anomaly training |
| `tests/unit/test_ad_performance_trainer.py` | ad performance training |

Run: `pytest tests/unit/test_model_artifacts.py -q` (and suite-specific files).

Prefer deterministic pytest; mock external I/O at public boundaries only.

---

## 7. Context7 curated extracts

### pytest — `tmp_path` fixture (`/pytest-dev/pytest`)

```python
def test_with_tmp_path(tmp_path):
    file_path = tmp_path / "my_file.txt"
    file_path.write_text("Hello")
    assert file_path.read_text() == "Hello"
```

Use for isolated artifact dirs in trainer/publish tests.

### joblib — dump/load (`/joblib/joblib`)

```python
import joblib

joblib.dump(model, path / "model.joblib")
loaded = joblib.load(path / "model.joblib")
```

Optional compression via `compress=True` — Juli defaults to uncompressed `model.joblib`
unless issue specifies otherwise.

### sklearn — leakage pitfall (`/scikit-learn/scikit-learn`)

Feature selection on the full dataset **before** `train_test_split` inflates eval
scores. Fit selectors/encoders on train only, then transform test.

```python
# Wrong: SelectKBest on all X before split → optimistic bias
# Right: split first, fit selector on X_train, transform X_test
```

---

## 8. Sources / live Context7 pointers

This workspace uses the **Context7 CLI** (`npx ctx7@latest`), not Context7 MCP.

```bash
npx ctx7@latest library pytest "fixtures tmp_path conftest"
npx ctx7@latest docs /pytest-dev/pytest "tmp_path fixture"
npx ctx7@latest docs /joblib/joblib "dump load compress"
npx ctx7@latest docs /scikit-learn/scikit-learn "train_test_split data leakage"
```

| Topic | Suggested CLI queries |
|-------|----------------------|
| pytest fixtures | `library pytest` → `docs /pytest-dev/pytest` — `tmp_path`, `conftest` |
| joblib persistence | `library joblib` → `docs /joblib/joblib` — dump/load, compression |
| sklearn splits / leakage | `library scikit-learn` → `docs /scikit-learn/scikit-learn` — `train_test_split`, common pitfalls |
| pandas parquet (dataset) | `library pandas` → `docs <id>` — `read_parquet`, dtypes |

**Example library IDs** (resolve with `library` before use): `/pytest-dev/pytest`,
`/joblib/joblib`, `/scikit-learn/scikit-learn`.

See [`.cursor/rules/context7-cli.mdc`](../../../rules/context7-cli.mdc).

**Repo authority:** `juli_backend/ai/*/MODULE.md`, [`artifacts/MODULE.md`](../../../backend/src/juli_backend/ai/artifacts/MODULE.md),
[`docs/api/data-models/`](../../../docs/api/data-models/).
