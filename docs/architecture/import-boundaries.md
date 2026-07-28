# Import boundaries (MMU-2)

Machine-enforced modular monolith import contract for `juli_backend`. The
allowed-edge matrix and deep-import policy live in [`.importlinter.toml`](../../.importlinter.toml)
at the repo root. CI runs the AST checker via
[`agent-runtime/scripts/ci/check_import_boundaries.py`](../../agent-runtime/scripts/ci/check_import_boundaries.py).

## What is enforced

1. **Allowed edges** — Each top-level package (`api`, `workers`, `services`,
   `ai`, `integrations`, `database`, `models`, `repositories`, `core`) may
   import only the top-level packages listed under `[allowed_edges]` in
   `.importlinter.toml`.
2. **Deep imports** — Cross top-level imports must stop at
   `juli_backend.<package>.<direct_child>`. Deeper submodule paths (for example
   `juli_backend.integrations.tiktok.client`) are forbidden from outside that
   top-level package.

Violations name the **importer file**, **importer package**, and **target module**.

## Local commands

```bash
# Warn-only scan of production backend (exit 0 even when violations exist)
python agent-runtime/scripts/ci/check_import_boundaries.py

# Strict mode — fails on any violation (PR gate / synthetic fixtures)
python agent-runtime/scripts/ci/check_import_boundaries.py --strict

# Synthetic contract proof
python agent-runtime/scripts/ci/check_import_boundaries.py \
  --config tests/fixtures/import_boundaries/synthetic/.importlinter.toml \
  --scan-root tests/fixtures/import_boundaries/synthetic/backend/src/juli_backend \
  --strict
```

Until MMU-3 (#556), production scans default to **warn-only**. Existing
violations do not block merges; the synthetic fixture in
`tests/fixtures/import_boundaries/synthetic/` proves the contract works.

## Updating the matrix when MODULES.md gains a module

When [MODULES.md](MODULES.md) adds a new backend module:

1. **Confirm the code path** under `backend/src/juli_backend/` (for example
   `services/billing/` → top-level package `services`, or a new top-level
   package if the module owns its own tree).
2. **Edit `.importlinter.toml`:**
   - If the module introduces a **new top-level package**, append it to
     `[packages].top_level`.
   - Add an `[allowed_edges].<package>` row (even if empty) for every new
     top-level package.
   - For each existing importer that may call the new module, add the new
     top-level name to that importer's allowed list.
   - Keep `[deep_imports].max_cross_package_depth` at `2` unless an ADR
     documents a different public-surface depth.
3. **Add or extend a synthetic fixture** under
   `tests/fixtures/import_boundaries/` when the new edge needs a dedicated
   regression (forbidden edge or deep import).
4. **Update [map.md](map.md)** and the module's `MODULE.md` public surface in
   the same PR as the code landing (same change set as MODULES.md).
5. **Run** `pytest tests/unit/test_import_boundaries.py` and
   `python agent-runtime/scripts/ci/check_import_boundaries.py --strict` on
   fixtures.

Do **not** add microservices or new deployables — this contract guards a single
backend package tree only.

## Related checks

- [`check_module_boundaries.py`](../../agent-runtime/scripts/validate/check_module_boundaries.py)
  — MODULE.md public-surface imports on changed files (separate gate).
- [`audit_cycles.py`](../../agent-runtime/scripts/ci/audit_cycles.py) — nightly
  Tarjan cycle audit from `map.md`.
