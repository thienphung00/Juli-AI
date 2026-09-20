"""The 062/063 expand-contract split that unblocked the release lane (#2050).

`062_workflow_and_subject` (#1701) shipped a per-row backfill `UPDATE` and a
`SET NOT NULL` on `workflow_runs.subject_ref`. Both are non-additive, so
`infra/scripts/migration_additive_gate.py` refused every release from
2026-09-16 on and production sat at `6767bccc`. #2050 split the revision: 062
keeps the additive half, and `063_workflow_subject_contract` carries the two
refused statements.

These tests pin the three properties that make that split work, because each
one is silently undoable by a plausible future edit:

1. **062 passes the gate.** Re-adding the backfill "because the column should
   be NOT NULL" re-blocks every release.
2. **063 is REFUSED by the gate, and that is correct.** It is the contract
   step; a version of it the gate accepted would have stopped being one.
3. **063 is NOT in `versions/`.** Moving it there looks like tidying up and is
   the one change that deadlocks the lane: pending becomes `[062, 063]`, the
   gate refuses on 063, no candidate starts, so the expand code never reaches
   production -- and 063 must not run until it has. The file may only move
   into `versions/` in a follow-up PR, AFTER it has been applied by hand.

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
CONTRACT_063_PATH = DEFERRED_DIR / "063_workflow_subject_contract.py"
RUNBOOK_PATH = REPO_ROOT / "docs/runbooks/backend-deploy-runbook.md"

EXPAND_REVISION = "062_workflow_and_subject"
CONTRACT_REVISION = "063_workflow_subject_contract"


def _gate():
    sys.path.insert(0, str(REPO_ROOT / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths  # noqa: PLC0415

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
# Property 2 -- the contract step is a contract step.
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


def test_contract_step_063_is_refused_by_the_additive_gate():
    """The refusal IS the contract step's signature, not a defect to fix.

    Both findings that used to block 062 must now be here -- if only one had
    moved, the split would be half done and 062 would still be refused (which
    `test_expand_step_062_is_accepted_by_the_additive_gate` would catch) or
    063 would no longer close the column.
    """
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
# Property 3 -- the contract step is invisible to the release lane.
# ---------------------------------------------------------------------------


def test_contract_step_063_is_not_in_the_versions_directory():
    """Moving it into `versions/` deadlocks the release lane -- see this
    module's docstring and 063's own."""
    stray = [p.name for p in VERSIONS_DIR.glob("063*")]
    assert stray == [], (
        f"{stray} is in versions/, so the additive gate will inspect it as pending "
        "and refuse every release. The contract step stays in deferred/ until it "
        "has been applied by hand."
    )


def test_alembic_head_is_the_expand_step_and_the_deferred_file_is_not_in_the_chain():
    """The mechanical consequence of the file's location, asserted through
    Alembic itself rather than inferred from the directory listing."""
    from alembic.config import Config  # noqa: PLC0415
    from alembic.script import ScriptDirectory  # noqa: PLC0415

    script = ScriptDirectory.from_config(Config(str(REPO_ROOT / "alembic.ini")))
    assert list(script.get_heads()) == [EXPAND_REVISION], script.get_heads()
    known = {revision.revision for revision in script.walk_revisions()}
    assert CONTRACT_REVISION not in known, (
        "Alembic can see the contract step, so it is pending on every release"
    )


def test_deferred_directory_holds_only_migrations_that_the_gate_refuses():
    """A file parked in `deferred/` that the gate would accept has no reason to
    be out of the chain, and silently skipping a releasable migration is its own
    defect. This keeps the directory from becoming a junk drawer."""
    deferred = sorted(p for p in DEFERRED_DIR.glob("*.py") if p.name != "__init__.py")
    assert deferred, "deferred/ is empty -- delete it rather than leaving it to rot"
    for path in deferred:
        assert not _gate()([path]).accepted, (
            f"{path.name} is additive, so it belongs in versions/, not deferred/"
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
