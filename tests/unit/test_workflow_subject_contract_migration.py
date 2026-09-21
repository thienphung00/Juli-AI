"""The 062/063 expand-contract split that unblocked the release lane (#2050),
and 063's promotion out of `deferred/` once it was applied (#2057).

`062_workflow_and_subject` (#1701) shipped a per-row backfill `UPDATE` and a
`SET NOT NULL` on `workflow_runs.subject_ref`. Both are non-additive, so
`infra/scripts/migration_additive_gate.py` refused every release from
2026-09-16 on and production sat at `6767bccc`. #2050 split the revision: 062
keeps the additive half, and `063_workflow_subject_contract` carries the two
refused statements, parked in `deferred/` (outside the Alembic chain the
release lane inspects) until an operator ran it by hand.

That happened on 2026-09-20T12:06Z: `alembic_version` is
`063_workflow_subject_contract`, `workflow_runs.subject_ref` is `NOT NULL`,
and all 37 pre-existing rows were backfilled. #2057 moved the file from
`deferred/` into `versions/` to match -- it is no longer pending, so the
additive gate never inspects it again, and leaving it in `deferred/` would
have deadlocked the *next* release instead: a fresh release checkout has no
copy of the file the VPS was hand-given, so Alembic could not resolve the
database's own stamped revision.

These tests now pin what the promoted state must look like, because each
property below is silently undoable by a plausible future edit:

1. **062 still passes the gate.** Re-adding the backfill "because the column
   should be NOT NULL" re-blocks every release.
2. **063's statements are still refused by the gate, taken on their own.**
   That is a static fact about the SQL (a data-moving `UPDATE` and a
   destructive `NOT NULL`), independent of which directory the file lives in
   or whether it is currently pending -- it is what proves the split was ever
   necessary, and a version of the file the gate silently accepted would mean
   those statements had gone missing.
3. **063 is now IN `versions/`, and `deferred/` is gone.** The opposite of
   #2050's invariant, because the precondition (applied in production) has
   flipped. `deferred/` held nothing else, and an empty holding directory has
   no purpose -- a future contract step recreates it when it exists.

No database is needed: these are source-level and Alembic-metadata assertions,
and they run everywhere. The behavioural round trip over both steps lives in
`tests/unit/test_migration_workflow_subject_roundtrip.py` and is Postgres-gated.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_ROOT = REPO_ROOT / "backend/src/juli_backend/database/migrations"
VERSIONS_DIR = MIGRATIONS_ROOT / "versions"
DEFERRED_DIR = MIGRATIONS_ROOT / "deferred"
EXPAND_062_PATH = VERSIONS_DIR / "062_workflow_and_subject.py"
CONTRACT_063_PATH = VERSIONS_DIR / "063_workflow_subject_contract.py"
RUNBOOK_PATH = REPO_ROOT / "docs/runbooks/backend-deploy-runbook.md"

EXPAND_REVISION = "062_workflow_and_subject"
CONTRACT_REVISION = "063_workflow_subject_contract"


def _gate():
    sys.path.insert(0, str(REPO_ROOT / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    return evaluate_migration_paths


def _revision_ids(path: Path) -> tuple[str | None, str | None]:
    body = path.read_text(encoding="utf-8")
    revision = re.search(r'^revision: str = "([^"]+)"', body, re.M)
    down = re.search(r'^down_revision: str \| None = (?:"([^"]+)"|None)', body, re.M)
    return (
        revision.group(1) if revision else None,
        down.group(1) if down and down.group(1) else None,
    )


# ---------------------------------------------------------------------------
# Property 1 -- the expand step is releasable.
# ---------------------------------------------------------------------------


def test_expand_step_062_is_accepted_by_the_additive_gate():
    """The whole point of #2050: this is what the `api` lane runs before it
    starts a candidate, and it must exit accepted."""
    result = _gate()([EXPAND_062_PATH])
    assert result.accepted, result.report()


def test_expand_step_062_does_not_backfill_or_narrow_subject_ref():
    """Stated against the source as well as the gate. The gate reads the AST
    and would catch `op.execute`/`op.alter_column`; this catches a rewrite that
    smuggles the same effect past it in a form the gate cannot read, which the
    gate itself classifies as `unverifiable` rather than silently allowing."""
    body = EXPAND_062_PATH.read_text(encoding="utf-8")
    upgrade_body = body.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
    assert "UPDATE public.workflow_runs" not in upgrade_body, (
        "062 is the expand step -- the per-row backfill belongs to 063"
    )
    assert 'sa.Column("subject_ref", sa.String(length=64), nullable=True)' in upgrade_body, (
        "062 must add subject_ref NULLABLE"
    )


# ---------------------------------------------------------------------------
# Property 2 -- 063's statements are still what made it a contract step.
# ---------------------------------------------------------------------------


def test_contract_step_063_exists_and_chains_onto_the_expand_step():
    assert CONTRACT_063_PATH.exists(), f"missing {CONTRACT_063_PATH}"
    revision, down_revision = _revision_ids(CONTRACT_063_PATH)
    assert revision == CONTRACT_REVISION
    assert revision == CONTRACT_063_PATH.stem
    assert len(revision) <= 32, (
        f"revision id {revision!r} is {len(revision)} chars -- "
        "alembic_version.version_num is VARCHAR(32)"
    )
    assert down_revision == EXPAND_REVISION


def test_contract_step_063_statements_are_still_refused_on_their_own():
    """Taken as a standalone file, 063's statements are exactly what the
    additive-only gate exists to refuse -- that fact does not change once the
    migration is applied and out of the pending set. It is a regression guard
    against a future edit quietly weakening the migration (e.g. dropping the
    NOT NULL narrowing), not a statement about whether a release lane would
    currently inspect this file."""
    result = _gate()([CONTRACT_063_PATH])
    assert not result.accepted, (
        "063 carries the backfill and the NOT NULL narrowing; a gate that "
        "accepts it means those statements went missing"
    )
    kinds = {(f.kind, f.operation) for f in result.findings}
    assert ("data_moving", "execute(UPDATE)") in kinds, result.report()
    assert ("destructive", "alter_column(not null)") in kinds, result.report()
    assert all(
        f.subject.startswith("UPDATE") or "subject_ref" in f.subject for f in result.findings
    ), result.report()


# ---------------------------------------------------------------------------
# Property 3 -- promoted: 063 now lives in versions/, deferred/ is gone.
# ---------------------------------------------------------------------------


def test_contract_step_063_is_now_in_versions_not_deferred():
    """#2057: the migration is applied in production, so it is no longer
    pending and belongs in the normal chain like any other applied
    revision."""
    assert CONTRACT_063_PATH.parent == VERSIONS_DIR
    stray_in_deferred = [p.name for p in DEFERRED_DIR.glob("063*")] if DEFERRED_DIR.exists() else []
    assert stray_in_deferred == [], (
        f"{stray_in_deferred} still present under deferred/ -- 063 should exist in "
        "exactly one place after promotion"
    )


def test_alembic_head_descends_from_the_contract_step():
    """The mechanical consequence of the promotion, asserted through Alembic
    itself. Deliberately does not assert a specific head revision: other
    migrations may chain onto 063 after this one lands, and re-pinning the
    exact head here would just make this test the next thing that goes stale
    for an unrelated reason. What must hold is that Alembic can resolve 063,
    that it still chains onto the expand step, and that it lies on the path
    to whatever head currently is."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(REPO_ROOT / "alembic.ini")))
    known = {revision.revision for revision in script.walk_revisions()}
    assert CONTRACT_REVISION in known, (
        "Alembic cannot resolve the contract step -- promoting the file into "
        "versions/ should have put it back in the chain"
    )
    contract_script = script.get_revision(CONTRACT_REVISION)
    assert contract_script.down_revision == EXPAND_REVISION

    on_path_to_a_head = any(
        CONTRACT_REVISION in {rev.revision for rev in script.iterate_revisions(head, "base")}
        for head in script.get_heads()
    )
    assert on_path_to_a_head, (
        f"{CONTRACT_REVISION} is known to Alembic but not an ancestor of any head "
        f"({script.get_heads()}) -- it may have been orphaned onto a dead branch"
    )


#: Contract steps parked outside the chain right now. #2057 deleted `deferred/`
#: once 063 was promoted, because 063 was the only file it had ever held and an
#: empty holding directory has no purpose of its own. #1972 recreated it for the
#: step below -- which is the "a future contract step recreates `deferred/` the
#: moment it needs it" case that decision anticipated, and which that test's own
#: failure message asks to be named here.
EXPECTED_DEFERRED_FILES = {"072_users_placeholder_phone_cleanup.py"}


def test_deferred_directory_holds_only_the_contract_steps_named_here():
    """`deferred/` exists only while a contract step is awaiting an operator.

    The directory is not a junk drawer and not a permanent fixture: it is
    present exactly when something is parked outside the chain, and it goes
    away again once that step has been applied and promoted (#2057's decision,
    kept). Naming the files is what keeps a stray or forgotten one visible --
    a step nobody remembers is a step that never runs.
    """
    if not EXPECTED_DEFERRED_FILES:
        assert not DEFERRED_DIR.exists(), (
            f"{DEFERRED_DIR} exists but nothing is parked outside the chain -- "
            "either it holds a new contract step (name it in "
            "EXPECTED_DEFERRED_FILES) or it is stray and should be deleted"
        )
        return

    assert DEFERRED_DIR.is_dir(), (
        f"{EXPECTED_DEFERRED_FILES} are expected under {DEFERRED_DIR}, which does "
        "not exist -- a contract step that is not on disk cannot be operated"
    )
    present = {p.name for p in DEFERRED_DIR.glob("*.py") if p.name != "__init__.py"}
    assert present == EXPECTED_DEFERRED_FILES, (
        f"{DEFERRED_DIR} holds {sorted(present)}, expected "
        f"{sorted(EXPECTED_DEFERRED_FILES)}. A contract step appears here on "
        "purpose and leaves once it has been applied and promoted."
    )


# ---------------------------------------------------------------------------
# The operator instruction has to exist, or the step is lost.
# ---------------------------------------------------------------------------


def test_the_runbook_names_the_contract_step_and_its_precondition():
    body = RUNBOOK_PATH.read_text(encoding="utf-8")
    assert CONTRACT_REVISION in body, (
        f"{RUNBOOK_PATH.name} must name the contract migration, or nobody will run it"
    )
    assert "deferred/" in body
    lowered = body.lower()
    assert "expand" in lowered and "contract" in lowered
