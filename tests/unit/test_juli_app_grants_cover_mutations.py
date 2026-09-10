"""Every table the application mutates must grant `juli_app` the verb it uses (#1897).

WHY THIS FILE EXISTS. `run_confirmations` granted `juli_app` only INSERT and
SELECT while `services/agent_runs/confirmations.py` UPDATEs it on every seller
decision. The whole human-in-the-loop write path was dead in production for
three days and no test saw it, because every unit test of that service ran on
SELECT-exempt ground: SQLite, or Postgres as the table owner, for which
Postgres never checks table privileges at all. A grant gap is invisible from
the owner connection by construction, so only a test that runs as the deployed
role can see one. This module is that test, generalised past the one table.

DERIVATION STRATEGY, AND WHY IT IS A REGISTRY *PLUS* A CROSS-CHECK.

A fully static derivation is not sound here. The application's dominant write
idiom is not `update(Model)` -- it is ORM attribute assignment on a row loaded
through a repository method, then `flush()`. Recovering "which table is this
object" in every such case is type inference over the whole package, and a
scanner that silently infers nothing would make this guard vacuous while
staying green. So:

* `GRANT_REQUIRED` is the explicit registry: one entry per (table, privilege)
  the application needs, each pinned to a VERBATIM source line that proves it.
* `test_every_registry_entry_still_names_a_live_call_site` re-reads those
  lines out of the tree. Delete or reword a mutation and the entry fails until
  someone re-justifies or removes it, so the registry cannot rot into fiction.
* `scan_for_mutations` is a real AST scan for the mechanically visible forms
  (`update(M)` / `delete(M)`, attribute assignment on a statically typed row,
  `ShopScopedRepo.upsert`'s natural-key path). Everything it finds must already
  be in the registry, so a NEW mutation of a recognisable shape fails this
  module until its grant is added.
* `test_the_scan_is_not_vacuous` pins the scan against the incident itself, so
  a scanner that regressed to finding nothing cannot pass silently.

The residue is honest: a mutation whose row is typed only through a repository
method the scan cannot resolve is caught by the registry, not by the scan.
`alert_configs` is exactly that shape today. The scan narrows the hole; it does
not close it.

TABLES DELIBERATELY ABSENT. Append-only tables stay ungranted, at least until a
call site proves otherwise: `action_card_approvals`, `alert_history`,
`decision_emission_novelty_ledger`, `impact_readings`, `production_write_audit`,
`recommendations`, `users`, `workflow_outcome_records`, `workflow_run_events`,
`workflow_webhook_signals`, `webhook_raw_events`, and the four bronze raw
payload tables. `analytics_kpi_envelopes` is absent for a different reason --
see `KNOWN_TRANSIENT`. The application contains no DELETE on any mapped table,
so no DELETE is registered.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from tests.support.postgres import RUNTIME_ROLE, owner_sync_engine, requires_postgres

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "backend/src/juli_backend"
MODELS_PATH = PACKAGE_ROOT / "models" / "models.py"


@dataclass(frozen=True)
class MutationSite:
    """One (table, privilege) the application needs, and the line that proves it."""

    schema: str
    table: str
    privilege: str
    path: str
    source_line: str
    why: str

    @property
    def qualified(self) -> tuple[str, str, str]:
        return (self.schema, self.table, self.privilege)


# ---------------------------------------------------------------------------
# The registry. Every entry is a measured call site, not a guess.
# ---------------------------------------------------------------------------

GRANT_REQUIRED: tuple[MutationSite, ...] = (
    # -- the six the #1897 audit found missing -----------------------------
    MutationSite(
        "public",
        "run_confirmations",
        "UPDATE",
        "backend/src/juli_backend/services/agent_runs/confirmations.py",
        "update(RunConfirmation)",
        "every seller approve/decline flips status out of 'pending'",
    ),
    MutationSite(
        "public",
        "shops",
        "UPDATE",
        "backend/src/juli_backend/repositories/identity.py",
        "shop.is_active = False",
        "ShopsRepo.pause_automation deactivates a shop after deauthorization (#354)",
    ),
    MutationSite(
        "public",
        "alert_configs",
        "UPDATE",
        "backend/src/juli_backend/services/alerts/engine.py",
        "existing.channel = rule.channel",
        "configure_rules rewrites an existing rule in place instead of inserting",
    ),
    MutationSite(
        "public",
        "campaigns",
        "UPDATE",
        "backend/src/juli_backend/services/feedback/outcome_ingest.py",
        'campaign.status = "completed"',
        "ingest_campaign_outcome closes an existing campaign with its realized figures",
    ),
    MutationSite(
        "public",
        "graph_edges",
        "UPDATE",
        "backend/src/juli_backend/repositories/graph.py",
        "existing.metadata_json = metadata_json",
        "GraphRepo.upsert_edge refreshes an existing edge's measurements",
    ),
    MutationSite(
        "public",
        "demo_execution_records",
        "UPDATE",
        "backend/src/juli_backend/services/demo_execution/dry_run.py",
        "record.completed_at = done_at",
        "the row is flushed as 'queued', then walked to 'running' and 'done'",
    ),
    # -- already granted; registered so the guard covers the whole surface --
    MutationSite(
        "public",
        "workflow_runs",
        "UPDATE",
        "backend/src/juli_backend/services/agent/runner/conversation_store.py",
        "run.status = status.value",
        "every run status/rollup persist (granted by 043)",
    ),
    MutationSite(
        "public",
        "action_cards",
        "UPDATE",
        "backend/src/juli_backend/services/agent/approval.py",
        'card.status = "approved"',
        "the approval lifecycle flip (granted by 043)",
    ),
    MutationSite(
        "public",
        "tool_executions",
        "UPDATE",
        "backend/src/juli_backend/repositories/workflow.py",
        "record.status = status",
        "ToolExecutionsRepo.update_status (granted by 043)",
    ),
    MutationSite(
        "public",
        "tiktok_credentials",
        "UPDATE",
        "backend/src/juli_backend/repositories/tiktok_credentials.py",
        "credential.access_token = encrypt_token(access_token)",
        "token refresh rewrites the stored credential (granted by 043)",
    ),
    MutationSite(
        "public",
        "tiktok_sync_state",
        "UPDATE",
        "backend/src/juli_backend/repositories/tiktok_credentials.py",
        "row.last_update_time = last_update_time",
        "every incremental-sync cursor advance after the first (granted by 055)",
    ),
    MutationSite(
        "public",
        "production_write_authorizations",
        "UPDATE",
        "backend/src/juli_backend/repositories/production_write.py",
        "authorization.consumed_at = utc_now_naive()",
        "single-use authorizations are consumed and revoked in place (granted by 048)",
    ),
    MutationSite(
        "public",
        "products",
        "UPDATE",
        "backend/src/juli_backend/repositories/commerce.py",
        "update(Product)",
        "ProductsRepo bulk price/status write (granted by 043)",
    ),
    MutationSite(
        "silver",
        "orders",
        "UPDATE",
        "backend/src/juli_backend/repositories/commerce.py",
        "order.status = SHIPPED",
        "OrdersRepo marks fulfilment, and upserts by natural key (granted by 043)",
    ),
    MutationSite(
        "ops",
        "analytics_backfill_partitions",
        "UPDATE",
        "backend/src/juli_backend/repositories/backfill.py",
        "row.status = COMPLETE",
        "partition checkpoints advance in place (granted by 043)",
    ),
    MutationSite(
        "gold",
        "kpi_envelopes",
        "UPDATE",
        "backend/src/juli_backend/repositories/analytics.py",
        "envelope.envelope_version = envelope_version",
        "GoldKpiEnvelopesRepo.upsert rewrites the shop's single envelope (granted by 043)",
    ),
    # -- ShopScopedRepo.upsert's natural-key path: `setattr` then `flush` ---
    MutationSite(
        "public",
        "order_items",
        "UPDATE",
        "backend/src/juli_backend/repositories/commerce.py",
        '_lookup_attrs = ("tiktok_order_id", "tiktok_sku_id")',
        "upsert re-applies a re-synced line item (granted by 043)",
    ),
    MutationSite(
        "silver",
        "returns",
        "UPDATE",
        "backend/src/juli_backend/repositories/commerce.py",
        '_lookup_attrs = ("tiktok_return_id",)',
        "upsert re-applies a re-synced return (granted by 043)",
    ),
    MutationSite(
        "public",
        "inventory_items",
        "UPDATE",
        "backend/src/juli_backend/repositories/commerce.py",
        '_lookup_attrs = ("tiktok_sku_id",)',
        "upsert re-applies a re-synced SKU (granted by 043)",
    ),
    MutationSite(
        "public",
        "settlements",
        "UPDATE",
        "backend/src/juli_backend/repositories/commerce.py",
        '_lookup_attrs = ("tiktok_settlement_id",)',
        "upsert re-applies a re-synced settlement (granted by 043)",
    ),
    MutationSite(
        "public",
        "creators",
        "UPDATE",
        "backend/src/juli_backend/repositories/analytics.py",
        '_lookup_attrs = ("tiktok_creator_id",)',
        "upsert re-applies a re-synced creator (granted by 043)",
    ),
    MutationSite(
        "public",
        "livestreams",
        "UPDATE",
        "backend/src/juli_backend/repositories/analytics.py",
        '_lookup_attrs = ("tiktok_livestream_id",)',
        "upsert re-applies a re-synced livestream (granted by 043)",
    ),
    MutationSite(
        "public",
        "analytics_performance_intervals",
        "UPDATE",
        "backend/src/juli_backend/repositories/analytics.py",
        '_lookup_attrs = ("snapshot_key",)',
        "upsert re-applies a re-synced interval snapshot (granted by 043)",
    ),
)

#: Scan hits that are provably NOT database writes. Each is pinned to its
#: source line for the same anti-rot reason as `GRANT_REQUIRED`, and each needs
#: a reason a reader can check, not an assertion that it is fine.
KNOWN_TRANSIENT: tuple[MutationSite, ...] = (
    MutationSite(
        "public",
        "analytics_kpi_envelopes",
        "UPDATE",
        "backend/src/juli_backend/repositories/analytics.py",
        "envelope.computed_at = computed_at",
        "post-#606 the legacy envelope is a VIEW OBJECT built by "
        "_gold_to_legacy_envelope and never added to a session; the durable "
        "write goes to gold.kpi_envelopes, which is registered above",
    ),
)

_TOLERATED = {site.qualified for site in (*GRANT_REQUIRED, *KNOWN_TRANSIENT)}


def tables_requiring(privilege: str, *, schema: str = "public") -> frozenset[str]:
    """The tables `GRANT_REQUIRED` justifies for `privilege` in `schema`.

    THE ONE AUTHORITY, and the reason it is a function rather than a constant.
    `tests/integration/test_migrations.py` reads this instead of keeping a list
    of its own, so the two guards cannot drift apart: this module asserts that
    every table the code mutates HOLDS the privilege, and that one asserts that
    no table HOLDS a privilege the code does not need. Over one list those are
    the two halves of an equality; over two hand-copied lists they are two
    opinions, and the stale one wins silently -- which is precisely what
    happened, since `test_juli_app_public_tables_have_select_insert` pinned
    `public.shops` at SELECT+INSERT and would have gone on pinning the broken
    state that made every confirmation decision impossible (#1897).
    """
    return frozenset(
        site.table
        for site in GRANT_REQUIRED
        if site.schema == schema and site.privilege == privilege
    )


#: Method-call receivers whose result is one mapped row, used to type a name
#: bound from a `select(Model)` statement variable.
_ROW_HELPERS = frozenset(
    {
        "_one_or_none",
        "_all",
        "_add",
        "execute",
        "first",
        "one",
        "one_or_none",
        "scalar",
        "scalar_one",
        "scalar_one_or_none",
        "scalars",
    }
)


# ---------------------------------------------------------------------------
# The scan.
# ---------------------------------------------------------------------------


def model_tables() -> dict[str, tuple[str, str]]:
    """`{ORM class name: (schema, table)}`, read out of `models/models.py`."""
    tree = ast.parse(MODELS_PATH.read_text(encoding="utf-8"))
    mapping: dict[str, tuple[str, str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        table, schema = None, "public"
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            names = {t.id for t in stmt.targets if isinstance(t, ast.Name)}
            if "__tablename__" in names and isinstance(stmt.value, ast.Constant):
                table = str(stmt.value.value)
            if "__table_args__" in names:
                for key, value in zip(*_dict_items(stmt.value), strict=True):
                    if key == "schema":
                        schema = value
        if table is not None:
            mapping[node.name] = (schema, table)
    return mapping


def _dict_items(node: ast.expr) -> tuple[list[str], list[str]]:
    """Constant string keys and values of any dict literal inside `node`."""
    keys: list[str] = []
    values: list[str] = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Dict):
            continue
        for key, value in zip(sub.keys, sub.values, strict=True):
            if (
                isinstance(key, ast.Constant)
                and isinstance(key.value, str)
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
            ):
                keys.append(key.value)
                values.append(value.value)
    return keys, values


def _annotated_model(node: ast.expr | None, models: frozenset[str]) -> str | None:
    """The one model class named anywhere in an annotation, if there is exactly one."""
    if node is None:
        return None
    named = {sub.id for sub in ast.walk(node) if isinstance(sub, ast.Name) and sub.id in models}
    return named.pop() if len(named) == 1 else None


class ReturnTypes:
    """Which model, if any, a call returns -- by owning class, then by name.

    `by_class` is exact: `self.get(...)` inside `ToolExecutionsRepo` is that
    class's own `get`. `by_name` is the fallback for a call on some other
    receiver, and it DROPS any name two classes define with two different row
    types. `get` is the case that matters: `UsersRepo.get -> User` and
    `ToolExecutionsRepo.get -> ToolExecution` make the bare name useless, and
    guessing one of them attributed `order.status = SHIPPED` to
    `tool_executions`. A wrong table here is worse than a missing one.
    """

    def __init__(self, trees: list[ast.Module], models: frozenset[str]) -> None:
        self.by_class: dict[tuple[str, str], str] = {}
        seen: dict[str, str | None] = {}
        for tree in trees:
            for owner, fn in _functions_with_owner(tree):
                model = _annotated_model(fn.returns, models)
                if model is None:
                    continue
                if owner is not None:
                    self.by_class[(owner, fn.name)] = model
                seen[fn.name] = None if seen.get(fn.name, model) != model else model
        self.by_name = {name: model for name, model in seen.items() if model is not None}

    def resolve(self, call: ast.Call, owner: str | None) -> str | None:
        func = call.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "self"
            and owner is not None
        ):
            return self.by_class.get((owner, func.attr))
        if isinstance(func, ast.Attribute):
            return self.by_name.get(func.attr)
        if isinstance(func, ast.Name):
            return self.by_name.get(func.id)
        return None


def _functions_with_owner(
    tree: ast.Module,
) -> list[tuple[str | None, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Every function in the module, paired with the class that defines it."""
    out: list[tuple[str | None, ast.FunctionDef | ast.AsyncFunctionDef]] = []

    def walk(node: ast.AST, owner: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                walk(child, child.name)
            elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                out.append((owner, child))
                walk(child, owner)
            else:
                walk(child, owner)

    walk(tree, None)
    return out


def _source_files() -> list[Path]:
    return sorted(p for p in PACKAGE_ROOT.rglob("*.py") if "migrations" not in p.parts)


def scan_for_mutations() -> dict[tuple[str, str, str], list[str]]:
    """`{(schema, table, verb): ["path:line  source"]}` for the visible mutations."""
    models = model_tables()
    names = frozenset(models)
    trees = {path: ast.parse(path.read_text(encoding="utf-8")) for path in _source_files()}
    returns = ReturnTypes(list(trees.values()), names)

    found: dict[tuple[str, str, str], list[str]] = {}

    for path, tree in trees.items():
        lines = path.read_text(encoding="utf-8").splitlines()
        rel = path.relative_to(REPO_ROOT)

        def record(model: str, verb: str, lineno: int, rel=rel, lines=lines) -> None:
            schema, table = models[model]
            found.setdefault((schema, table, verb), []).append(
                f"{rel}:{lineno}  {lines[lineno - 1].strip()}"
            )

        _scan_module(tree, names, returns, record)
    return found


def _scan_module(
    tree: ast.Module,
    names: frozenset[str],
    returns: ReturnTypes,
    record,
) -> None:
    # 1. `update(Model)` / `delete(Model)` -- the unambiguous form.
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"update", "delete"}
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in names
        ):
            record(node.args[0].id, node.func.id.upper(), node.lineno)

    # 2. `ShopScopedRepo.upsert`'s natural-key path: `setattr(existing, ...)`
    #    then `flush()`, inside `_base._apply_if_newer`. A repository declaring
    #    `_lookup_attrs` therefore UPDATEs its `_model`'s table.
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        model, has_lookup, lookup_line = None, False, node.lineno
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            targets = {t.id for t in stmt.targets if isinstance(t, ast.Name)}
            if "_model" in targets and isinstance(stmt.value, ast.Name):
                model = stmt.value.id
            if "_lookup_attrs" in targets and isinstance(stmt.value, ast.Tuple):
                has_lookup = bool(stmt.value.elts)
                lookup_line = stmt.lineno
        if model in names and has_lookup:
            record(model, "UPDATE", lookup_line)

    # 3. Attribute assignment on a row whose model is statically knowable.
    for owner, fn in _functions_with_owner(tree):
        for lineno, model in _mutated_rows(fn, owner, names, returns):
            record(model, "UPDATE", lineno)


def _mutated_rows(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    owner: str | None,
    names: frozenset[str],
    returns: ReturnTypes,
) -> list[tuple[int, str]]:
    row_types: dict[str, str] = {}
    stmt_types: dict[str, str] = {}
    constructed: set[str] = set()
    loaded: set[str] = set()

    for arg in (*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs):
        model = _annotated_model(arg.annotation, names)
        if model is not None:
            row_types[arg.arg] = model

    for node in ast.walk(fn):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            model = _annotated_model(node.annotation, names)
            if model is not None:
                row_types[node.target.id] = model
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if not targets:
            continue
        model, kind = _value_model(node.value, owner, names, returns, stmt_types)
        if model is None:
            continue
        for target in targets:
            if kind == "stmt":
                stmt_types[target] = model
            else:
                row_types[target] = model
                (constructed if kind == "new" else loaded).add(target)

    # A constructed row that has already been flushed is persisted, so every
    # later assignment to it is an UPDATE, not part of its INSERT. This is how
    # `demo_execution_records` walks queued -> running -> done.
    #
    # A name bound to a LOADED row anywhere in the function is never treated as
    # merely constructed, whatever the branches do afterwards. That is the
    # `row = await repo.get(...)` / `if row is None: row = Model(...)` upsert
    # shape, and reading it as a plain insert hid the real UPDATE on
    # `ops.analytics_backfill_partitions` and `gold.kpi_envelopes`.
    flushes = [
        node.lineno
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"flush", "commit"}
    ]
    first_flush = min(flushes) if flushes else None

    mutations: list[tuple[int, str]] = []
    for node in ast.walk(fn):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AugAssign):
            targets = [node.target]
        for target in targets:
            if not (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)):
                continue
            name = target.value.id
            if name not in row_types:
                continue
            purely_new = name in constructed and name not in loaded
            if purely_new and (first_flush is None or node.lineno <= first_flush):
                continue
            mutations.append((node.lineno, row_types[name]))
    return mutations


def _value_model(
    value: ast.expr,
    owner: str | None,
    names: frozenset[str],
    returns: ReturnTypes,
    stmt_types: dict[str, str],
) -> tuple[str | None, str]:
    """Classify an assigned expression as a new row, a loaded row, or a statement."""
    expr = value.value if isinstance(value, ast.Await) else value
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id in names:
        return expr.func.id, "new"

    calls = [sub for sub in ast.walk(value) if isinstance(sub, ast.Call)]
    executed = any(
        isinstance(call.func, ast.Attribute) and call.func.attr in _ROW_HELPERS for call in calls
    )

    # `x = await session.get(Model, ...)`
    for call in calls:
        if (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "get"
            and call.args
            and isinstance(call.args[0], ast.Name)
            and call.args[0].id in names
        ):
            return call.args[0].id, "row"

    # `stmt = select(Model)...`, possibly executed in the same expression.
    for call in calls:
        if (
            isinstance(call.func, ast.Name)
            and call.func.id == "select"
            and call.args
            and isinstance(call.args[0], ast.Name)
            and call.args[0].id in names
        ):
            return call.args[0].id, "row" if executed else "stmt"

    # `row = await self._one_or_none(stmt)` where `stmt` came from `select(Model)`.
    for call in calls:
        if not (isinstance(call.func, ast.Attribute) and call.func.attr in _ROW_HELPERS):
            continue
        for arg in call.args:
            if isinstance(arg, ast.Name) and arg.id in stmt_types:
                return stmt_types[arg.id], "row"

    # `row = await repo.get_partition(...)` -- resolved by return annotation.
    for call in calls:
        model = returns.resolve(call, owner)
        if model is not None:
            return model, "row"
    return None, "none"


def _grants(engine: Engine) -> set[tuple[str, str, str]]:
    sql = text(
        "SELECT table_schema, table_name, privilege_type "
        "FROM information_schema.role_table_grants WHERE grantee = :role"
    )
    with engine.connect() as conn:
        return {tuple(row) for row in conn.execute(sql, {"role": RUNTIME_ROLE})}


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


@requires_postgres
def test_every_mutated_table_grants_the_privilege_it_needs():
    """The acceptance criterion, and the class of defect #1897 belongs to.

    Names every table that is short a privilege, rather than failing on the
    first one: a role cutover tends to miss a set, not a single table.
    """
    with owner_sync_engine() as engine:
        held = _grants(engine)

    missing = [site for site in GRANT_REQUIRED if site.qualified not in held]

    assert not missing, "juli_app is missing a privilege its own code path needs:\n" + "\n".join(
        f"  {s.schema}.{s.table} needs {s.privilege} -- {s.why} ({s.path}: {s.source_line!r})"
        for s in missing
    )


def test_the_code_scan_finds_no_mutation_outside_the_registry():
    """A new mutation of a recognisable shape fails here until it is registered.

    This is the anti-rot direction that matters. The registry alone would have
    been just as blind to #1897 as the suite already was; the scan is what
    makes a NEW `run_confirmations` impossible to add quietly.
    """
    unregistered = {
        key: sites for key, sites in scan_for_mutations().items() if key not in _TOLERATED
    }

    assert not unregistered, (
        "the code mutates a table this module does not know about -- add it to "
        "GRANT_REQUIRED (with the migration that grants it) or to "
        "KNOWN_TRANSIENT (with the reason it is not a database write):\n"
        + "\n".join(
            f"  {schema}.{table} {verb}\n    " + "\n    ".join(sites)
            for (schema, table, verb), sites in sorted(unregistered.items())
        )
    )


def test_the_scan_is_not_vacuous():
    """Pin the scan against the incident itself.

    A scan that inferred nothing would satisfy the test above forever. This one
    fails the moment the scan stops seeing the very mutation that started this.
    """
    found = scan_for_mutations()

    assert ("public", "run_confirmations", "UPDATE") in found, (
        "the mutation scan no longer finds confirmations.py's UPDATE -- it has "
        "stopped inferring anything and every guard above is now vacuous"
    )
    assert len(found) >= 20, (
        f"the mutation scan resolved only {len(found)} tables; it measured 23 when "
        "written, so it has lost its type inference and is no longer a real net"
    )


def test_every_registry_entry_still_names_a_live_call_site():
    """Each entry's evidence line must still exist, verbatim, where it claims to.

    This is what keeps the hand-written half honest: a registry nobody can
    falsify is documentation, not a test.
    """
    stale: list[str] = []
    for site in (*GRANT_REQUIRED, *KNOWN_TRANSIENT):
        path = REPO_ROOT / site.path
        if not path.is_file():
            stale.append(f"  {site.schema}.{site.table}: missing file {site.path}")
            continue
        body = path.read_text(encoding="utf-8")
        if site.source_line not in body:
            stale.append(
                f"  {site.schema}.{site.table}: {site.source_line!r} no longer in {site.path}"
            )

    assert not stale, (
        "a registry entry no longer points at real code; re-justify it against "
        "the current call site or delete it and revoke the grant:\n" + "\n".join(stale)
    )


def test_append_only_tables_are_not_quietly_granted_update():
    """Least privilege, asserted rather than assumed.

    Audit trails and event logs were reviewed and found insert-only. If one
    later gains an UPDATE grant, that is either a mistake or a code change
    nobody registered here -- both worth failing on.
    """
    append_only = {
        "action_card_approvals",
        "alert_history",
        "decision_emission_novelty_ledger",
        "impact_readings",
        "production_write_audit",
        "recommendations",
        "users",
        "workflow_outcome_records",
        "workflow_run_events",
        "workflow_webhook_signals",
    }
    registered = {site.table for site in GRANT_REQUIRED}

    assert not (append_only & registered), (
        "a table documented as append-only is registered as mutated; the "
        "docstring and the registry disagree"
    )
