"""Fixture-driven tests for #670 P1 Option A: compact per-issue status records
replacing verbose review/validation/implementation/intent-review/optimization
bodies as the wave->main artifact-gate read path and the git-tracked source
of truth.

Covers AC1-AC5 from the issue plus the bootstrapping guard (in-loop validate
gates must still read verbose bodies off disk while those five dirs are
gitignored — gitignore blocks committing, not reading/writing).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(CI_DIR))

import capture_providers  # noqa: E402
from common import load_json  # noqa: E402
from generate_status_records import build_status_record, migrate  # noqa: E402
from json_schema_validate import validate_json_schema  # noqa: E402
from wave_manifest import validate_wave_artifacts  # noqa: E402

BODY_DIRS = (
    "reviews",
    "implementations",
    "intent-reviews",
    "validation",
    "optimization",
)
STATUS_SCHEMA_PATH = REPO_ROOT / "agent-runtime" / "docs" / "schemas" / "status-record.schema.json"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )


@pytest.fixture(autouse=True)
def _unlatch_settle_clock():
    """Every test in this file starts and ends with an unlatched settle clock.

    ``task_transcripts.settle_clock`` latches one instant per process, which is
    right for the short-lived generation scripts that import it and wrong for a
    pytest session that outlives the 300s settle window. Resetting around each
    test keeps every test judging transcript ages against an instant from its
    own run, and stops a test that *places* the clock from pinning its
    neighbours to a fabricated one.
    """
    import task_transcripts

    task_transcripts.reset_settle_clock()
    yield
    task_transcripts.reset_settle_clock()


# --- AC1: verbose body untracked/ignored, status record tracked -----------


def test_verbose_body_path_is_gitignored() -> None:
    result = _git(
        "check-ignore",
        "--quiet",
        "agent-runtime/artifacts/reviews/review-issue-999999999.json",
    )
    assert result.returncode == 0, (
        "expected a review body path to be git-ignored; "
        f"check-ignore exited {result.returncode}: {result.stderr}"
    )


def test_status_record_path_is_not_gitignored() -> None:
    result = _git(
        "check-ignore",
        "--quiet",
        "agent-runtime/artifacts/status/issue-999999999.json",
    )
    assert result.returncode == 1, (
        "expected a status record path to NOT be git-ignored (status/ stays "
        f"tracked); check-ignore exited {result.returncode}"
    )


# --- AC2: migration leaves no tracked *.json in the five dirs; one record --
# --- per previously-recorded issue with matching statuses -----------------


def test_five_body_dirs_have_no_tracked_json_after_migration() -> None:
    for dirname in BODY_DIRS:
        tracked = _git("ls-files", f"agent-runtime/artifacts/{dirname}/*.json")
        assert tracked.stdout.strip() == "", (
            f"expected no tracked *.json under agent-runtime/artifacts/{dirname}/, "
            f"found:\n{tracked.stdout}"
        )


def test_status_dir_has_one_record_per_migrated_issue_pair() -> None:
    reviews = REPO_ROOT / "agent-runtime" / "artifacts" / "reviews"
    validation = REPO_ROOT / "agent-runtime" / "artifacts" / "validation"
    status_dir = REPO_ROOT / "agent-runtime" / "artifacts" / "status"

    review_issues = {
        int(p.stem.rsplit("-", 1)[-1])
        for p in reviews.glob("review-issue-*.json")
        if p.stem.rsplit("-", 1)[-1].isdigit()
    }
    validation_issues = {
        int(p.stem.rsplit("-", 1)[-1])
        for p in validation.glob("validation-issue-*.json")
        if p.stem.rsplit("-", 1)[-1].isdigit()
    }
    expected_issues = review_issues & validation_issues
    if not expected_issues:
        pytest.skip(
            "no review+validation pair present on disk (expected on a clean checkout: "
            "#670 gitignores the five verbose body dirs, so nothing is tracked in git "
            "for them to be present from). This consistency check only applies when "
            "bodies happen to be present locally, e.g. right after running "
            "generate_status_records.py on a dev machine."
        )

    status_issues = {
        int(p.stem.rsplit("-", 1)[-1])
        for p in status_dir.glob("issue-*.json")
        if p.stem.rsplit("-", 1)[-1].isdigit()
    }
    assert expected_issues <= status_issues, (
        f"missing status records for issues: {sorted(expected_issues - status_issues)}"
    )

    for issue in sorted(expected_issues):
        record = load_json(status_dir / f"issue-{issue}.json")
        review = load_json(reviews / f"review-issue-{issue}.json")
        validation_body = load_json(validation / f"validation-issue-{issue}.json")
        assert record["review"]["status"] == review.get("status")
        expected_validation_status = (
            "PASS"
            if validation_body.get("status") == "PASS"
            and validation_body.get("readyForMerge") is True
            else (validation_body.get("status") or "FAIL")
        )
        assert record["validation"]["status"] == expected_validation_status


def test_migration_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    import generate_status_records as gsr

    reviews = tmp_path / "reviews"
    validation = tmp_path / "validation"
    status_dir = tmp_path / "status"
    reviews.mkdir()
    validation.mkdir()

    review_payload = {
        "issue": 42,
        "status": "PASS",
        "criticalFindings": [],
        "modulesTouched": ["web"],
        "testCoverage": {"acceptance": {"total": 3, "mapped": 3}},
        "timestamp": "2026-08-02T00:00:00Z",
    }
    validation_payload = {
        "issue": 42,
        "status": "PASS",
        "readyForMerge": True,
        "timestamp": "2026-08-02T00:01:00Z",
    }
    (reviews / "review-issue-42.json").write_text(json.dumps(review_payload), encoding="utf-8")
    (validation / "validation-issue-42.json").write_text(
        json.dumps(validation_payload), encoding="utf-8"
    )

    monkeypatch.setattr(gsr, "REVIEWS_DIR", reviews)
    monkeypatch.setattr(gsr, "VALIDATION_DIR", validation)
    monkeypatch.setattr(gsr, "STATUS_DIR", status_dir)
    monkeypatch.setattr(gsr, "WAVES_DIR", tmp_path / "waves")

    first = migrate()
    first_bytes = (status_dir / "issue-42.json").read_bytes()
    second = migrate()
    second_bytes = (status_dir / "issue-42.json").read_bytes()

    assert first == [42]
    assert second == [42]
    assert first_bytes == second_bytes


class _Straddle:
    """A ``time`` stand-in that moves only when the test says so.

    Two fixed instants, half a second either side of the settle boundary,
    selected by ``index`` — so which side of the boundary a transcript falls on
    is chosen by the test rather than by how long the test took to run.
    """

    def __init__(self, ticks: tuple[float, ...]) -> None:
        self.ticks = ticks
        self.index = 0

    def time(self) -> float:
        return self.ticks[self.index]


def _plant_transcript(tasks_dir: Path, *, agent_id: str, issue: int) -> None:
    """One JSONL transcript, backdated to the epoch.

    Backdating makes the file's age exactly whatever the clock reads, which is
    what lets the test place it on the boundary instead of hoping to land there.
    """
    import os

    tasks_dir.mkdir(parents=True, exist_ok=True)
    # #1512 reads the spawn directive to tell an executor from a reviewer, and
    # only an executor is reported as the run. Without one this agent classifies
    # `unknown`, the block goes `ambiguous`, and the boundary this test exists to
    # pin is never reached.
    spawn = {
        "type": "user",
        "agentId": agent_id,
        "sessionId": "session-under-test",
        "isSidechain": True,
        "timestamp": "2026-09-02T00:59:00.000Z",
        "message": {"role": "user", "content": f"Implement GitHub issue #{issue}."},
    }
    record = {
        "type": "assistant",
        "agentId": agent_id,
        "sessionId": "session-under-test",
        "gitBranch": "main",
        "isSidechain": True,
        "timestamp": "2026-09-02T01:00:00.000Z",
        "message": {
            "id": "m-1",
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "name": "Bash",
                    "id": "tu_1",
                    "input": {"command": f"ls /repo/.worktrees/w4-{issue}"},
                }
            ],
            "usage": {
                "input_tokens": 1,
                "output_tokens": 1,
                "cache_creation_input_tokens": 1,
                "cache_read_input_tokens": 1,
            },
        },
    }
    path = tasks_dir / f"{agent_id}.output"
    path.write_text(json.dumps(spawn) + "\n" + json.dumps(record) + "\n", encoding="utf-8")
    os.utime(path, (0, 0))


def test_record_generation_is_idempotent_across_the_settle_boundary(
    tmp_path: Path, monkeypatch
) -> None:
    """Two generations of one record agree even on a transcript sitting on 300s.

    ``test_migration_is_idempotent`` above cannot see this. It reads whatever
    session store the machine happens to have, so the bug only bites when some
    transcript's age falls inside the gap between the two ``migrate()`` calls —
    a few seconds out of 300. It was measured failing about 1 run in 5, and only
    on the slow runs; the fix that preceded this one was accepted on "3/3 green",
    which is roughly a coin flip with the bug fully present.

    So this test plants its own store and places the clock rather than sampling
    it. The transcript is backdated to the epoch and the clock reads 299.5s on
    one generation and 300.5s on the next. Before #1515 that alone flipped the
    record between ``not-measured`` and ``measured``, on bytes that are supposed
    to be identical.
    """
    import generate_status_records as gsr
    import task_transcripts

    reviews = tmp_path / "reviews"
    validation = tmp_path / "validation"
    status_dir = tmp_path / "status"
    reviews.mkdir()
    validation.mkdir()

    (reviews / "review-issue-42.json").write_text(
        json.dumps(
            {
                "issue": 42,
                "status": "PASS",
                "criticalFindings": [],
                "modulesTouched": ["web"],
                "testCoverage": {"acceptance": {"total": 3, "mapped": 3}},
                "timestamp": "2026-08-02T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    (validation / "validation-issue-42.json").write_text(
        json.dumps(
            {
                "issue": 42,
                "status": "PASS",
                "readyForMerge": True,
                "timestamp": "2026-08-02T00:01:00Z",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(gsr, "REVIEWS_DIR", reviews)
    monkeypatch.setattr(gsr, "VALIDATION_DIR", validation)
    monkeypatch.setattr(gsr, "STATUS_DIR", status_dir)
    monkeypatch.setattr(gsr, "WAVES_DIR", tmp_path / "waves")

    tasks_dir = tmp_path / "session" / "tasks"
    _plant_transcript(tasks_dir, agent_id="agent-astride", issue=42)
    # The documented override, so this reads the planted store and never the
    # machine's real session — hermetic, and the same code path CI takes.
    monkeypatch.setenv(task_transcripts.STORE_ENV_VAR, str(tasks_dir))

    settle = task_transcripts.SETTLE_SECONDS
    straddle = _Straddle((settle - 0.5, settle + 0.5))
    monkeypatch.setattr(task_transcripts, "time", straddle)

    def _generate() -> tuple[bytes, str]:
        migrate()
        raw = (status_dir / "issue-42.json").read_bytes()
        return raw, json.loads(raw)["run"]["metrics"]["status"]

    task_transcripts.reset_settle_clock()
    straddle.index = 0
    short_first = _generate()
    straddle.index = 1
    short_second = _generate()
    assert short_first == short_second
    assert short_first[1] == "not-measured"

    task_transcripts.reset_settle_clock()
    straddle.index = 1
    past_first = _generate()
    straddle.index = 0
    past_second = _generate()
    assert past_first == past_second
    assert past_first[1] == "measured"

    # And the two latches really do disagree — without that, the pair of
    # assertions above would be satisfied by a boundary that never fires.
    assert short_first[0] != past_first[0]


# --- AC3: gate reads status record, fails on missing/non-PASS -------------


def test_gate_fails_closed_when_status_record_missing(tmp_path: Path, monkeypatch) -> None:
    import wave_manifest

    monkeypatch.setattr(wave_manifest, "STATUS_DIR", tmp_path / "status")
    manifest = {
        "schemaVersion": "1.0.0",
        "artifactType": "wave_manifest",
        "waveId": "wave-670",
        "branch": "feature/670-wave",
        "issues": [670],
    }
    result = validate_wave_artifacts(manifest)
    assert result["valid"] is False
    assert any("missing status record" in e.lower() for e in result["errors"])


# --- AC4: regression guard — non-body dirs remain tracked ------------------


def test_non_body_artifact_dirs_remain_tracked() -> None:
    for rel in (
        "agent-runtime/artifacts/benchmarks",
        "agent-runtime/artifacts/releases",
        "agent-runtime/docs/schemas",
        "agent-runtime/templates",
    ):
        tracked = _git("ls-files", rel)
        assert tracked.stdout.strip() != "", f"expected tracked files under {rel}/"

    # waves/ may not exist yet (no wave has landed against this checkout);
    # when present it must not be gitignored.
    waves_ignore = _git("check-ignore", "--quiet", "agent-runtime/artifacts/waves/wave-1.json")
    assert waves_ignore.returncode == 1, "agent-runtime/artifacts/waves/ must not be gitignored"


# --- AC5: gateVersion + sha256 present; integrity path exercised ----------


def test_status_record_schema_requires_gate_version_and_sha256() -> None:
    schema = load_json(STATUS_SCHEMA_PATH)
    assert "gateVersion" in schema["required"]
    review_required = schema["properties"]["review"]["required"]
    validation_required = schema["properties"]["validation"]["required"]
    assert "sha256" in review_required
    assert "sha256" in validation_required


def test_built_status_record_validates_against_schema(tmp_path: Path, monkeypatch) -> None:
    import generate_status_records as gsr

    reviews = tmp_path / "reviews"
    validation = tmp_path / "validation"
    reviews.mkdir()
    validation.mkdir()
    review_bytes = json.dumps(
        {
            "issue": 7,
            "status": "PASS",
            "criticalFindings": [],
            "modulesTouched": [],
            "testCoverage": {"acceptance": {"total": 1, "mapped": 1}},
            "timestamp": "2026-08-02T00:00:00Z",
        }
    ).encode("utf-8")
    validation_bytes = json.dumps(
        {
            "issue": 7,
            "status": "PASS",
            "readyForMerge": True,
            "timestamp": "2026-08-02T00:00:01Z",
        }
    ).encode("utf-8")
    (reviews / "review-issue-7.json").write_bytes(review_bytes)
    (validation / "validation-issue-7.json").write_bytes(validation_bytes)

    monkeypatch.setattr(gsr, "REVIEWS_DIR", reviews)
    monkeypatch.setattr(gsr, "VALIDATION_DIR", validation)
    monkeypatch.setattr(gsr, "WAVES_DIR", tmp_path / "waves")

    record = build_status_record(7)
    schema = load_json(STATUS_SCHEMA_PATH)
    errors = validate_json_schema(record, schema)
    assert errors == []
    assert record["gateVersion"] == 2
    assert record["review"]["sha256"] == hashlib.sha256(review_bytes).hexdigest()
    assert record["validation"]["sha256"] == hashlib.sha256(validation_bytes).hexdigest()


# --- Bootstrapping guard: in-loop gates still read bodies off disk while --
# --- the five dirs are gitignored (gitignore blocks commit, not I/O) -----


def test_review_artifact_readable_from_disk_when_dir_is_gitignored(
    tmp_path: Path, monkeypatch
) -> None:
    """Simulates the agent loop: a review body is written to a gitignored
    dir mid-loop; ADR-003 gates that read via common.load_review_artifact
    must still see it (they read the filesystem, not git's index)."""
    import common

    reviews = tmp_path / "agent-runtime" / "artifacts" / "reviews"
    monkeypatch.setattr(common, "REVIEWS_DIR", reviews)

    payload = {"id": "review-issue-670", "issue": 670, "status": "PASS"}
    reviews.mkdir(parents=True)
    (reviews / "review-issue-670.json").write_text(json.dumps(payload), encoding="utf-8")

    loaded = common.load_review_artifact(670)
    assert loaded is not None
    assert loaded["status"] == "PASS"

    # And confirm the real repo actually gitignores this directory, so the
    # guarantee we just exercised in tmp_path matches production behavior.
    result = _git(
        "check-ignore",
        "--quiet",
        "agent-runtime/artifacts/reviews/review-issue-670.json",
    )
    assert result.returncode == 0


# --- #1438: gateVersion 2, the run{} envelope, and the capture-provider seam --
# The seam is the deliverable: six Wave-2 slices each add ONE provider module
# under agent-runtime/scripts/ci/capture_providers/. If any of them had to edit
# generate_status_records.py they would serialize against each other, so the
# tests below assert the writer stays untouched, and that a provider which
# raises fails record generation closed rather than dropping its block.


def _seed_bodies(tmp_path: Path, issue: int, monkeypatch):
    """Point the generator at a tmp review+validation pair and return it."""
    import generate_status_records as gsr

    reviews = tmp_path / "reviews"
    validation = tmp_path / "validation"
    reviews.mkdir(exist_ok=True)
    validation.mkdir(exist_ok=True)
    (reviews / f"review-issue-{issue}.json").write_text(
        json.dumps(
            {
                "issue": issue,
                "status": "PASS",
                "criticalFindings": [],
                "modulesTouched": ["agent-runtime"],
                "testCoverage": {"acceptance": {"total": 4, "mapped": 4}},
                "timestamp": "2026-09-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    (validation / f"validation-issue-{issue}.json").write_text(
        json.dumps(
            {
                "issue": issue,
                "status": "PASS",
                "readyForMerge": True,
                "timestamp": "2026-09-01T00:00:01Z",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(gsr, "REVIEWS_DIR", reviews)
    monkeypatch.setattr(gsr, "VALIDATION_DIR", validation)
    monkeypatch.setattr(gsr, "STATUS_DIR", tmp_path / "status")
    monkeypatch.setattr(gsr, "WAVES_DIR", tmp_path / "waves")
    return gsr


def _write_provider_module(directory: Path, filename: str, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(body, encoding="utf-8")
    return path


def test_gateversion_2_record_with_run_block_validates(tmp_path: Path, monkeypatch) -> None:
    gsr = _seed_bodies(tmp_path, 1438, monkeypatch)

    record = gsr.build_status_record(1438)

    schema = load_json(STATUS_SCHEMA_PATH)
    assert validate_json_schema(record, schema) == []
    assert record["gateVersion"] == 2
    assert isinstance(record["run"], dict)
    # The shipped reference provider proves the registry is wired end to end,
    # not merely importable.
    assert "artifactBytes" in record["run"], (
        f"expected the reference provider's block under run{{}}, got {sorted(record['run'])}"
    )


def test_registered_provider_block_appears_without_writer_edit(tmp_path: Path, monkeypatch) -> None:
    """A Wave-2 slice drops one module into the provider directory; its block
    shows up under run{} with generate_status_records.py byte-identical."""
    writer_path = CI_DIR / "generate_status_records.py"
    writer_before = writer_path.read_bytes()

    provider_dir = tmp_path / "providers"
    _write_provider_module(
        provider_dir,
        "wave_two_probe.py",
        'PROVIDER_NAME = "waveTwoProbe"\n'
        "\n"
        "\n"
        "def capture(context):\n"
        '    return {"issue": context.issue}\n',
    )

    gsr = _seed_bodies(tmp_path, 1441, monkeypatch)

    with capture_providers.provider_sandbox():
        discovered = capture_providers.discover_providers(provider_dir)
        assert "waveTwoProbe" in discovered
        record = gsr.build_status_record(1441)

    assert record["run"]["waveTwoProbe"] == {"issue": 1441}
    # The seam, stated as an assertion: the writer never learned this provider's
    # name and was not modified to make the block appear.
    assert b"waveTwoProbe" not in writer_before
    assert writer_path.read_bytes() == writer_before

    # ...and the sandbox really did unregister it, so slices stay independent.
    assert "waveTwoProbe" not in capture_providers.registered_providers()


def test_provider_error_fails_closed(tmp_path: Path, monkeypatch) -> None:
    """A provider that raises must fail generation naming itself — never emit a
    record whose block is silently absent."""
    gsr = _seed_bodies(tmp_path, 1442, monkeypatch)

    def _boom(context):
        raise RuntimeError("transcript unavailable")

    with capture_providers.provider_sandbox():
        capture_providers.register_provider("explodingProbe", _boom)
        with pytest.raises(capture_providers.CaptureProviderError) as excinfo:
            gsr.migrate()

    assert excinfo.value.provider == "explodingProbe"
    assert "explodingProbe" in str(excinfo.value)
    assert "transcript unavailable" in str(excinfo.value)
    assert not (tmp_path / "status" / "issue-1442.json").exists(), (
        "fail-closed violated: a record was written despite a provider raising"
    )


def test_provider_returning_a_non_dict_fails_closed(tmp_path: Path, monkeypatch) -> None:
    gsr = _seed_bodies(tmp_path, 1443, monkeypatch)

    with capture_providers.provider_sandbox():
        capture_providers.register_provider("scalarProbe", lambda context: "not-a-block")
        with pytest.raises(capture_providers.CaptureProviderError) as excinfo:
            gsr.build_status_record(1443)

    assert excinfo.value.provider == "scalarProbe"


def test_provider_module_missing_capture_fails_closed(tmp_path: Path) -> None:
    provider_dir = tmp_path / "providers"
    _write_provider_module(provider_dir, "half_built.py", 'PROVIDER_NAME = "halfBuilt"\n')

    with capture_providers.provider_sandbox():
        with pytest.raises(capture_providers.CaptureProviderError) as excinfo:
            capture_providers.discover_providers(provider_dir)

    assert "halfBuilt" in str(excinfo.value)
    assert "halfBuilt" not in capture_providers.registered_providers()


def test_provider_module_that_fails_to_import_fails_closed(tmp_path: Path) -> None:
    provider_dir = tmp_path / "providers"
    _write_provider_module(provider_dir, "broken.py", "raise ImportError('no telemetry sdk')\n")

    with capture_providers.provider_sandbox():
        with pytest.raises(capture_providers.CaptureProviderError) as excinfo:
            capture_providers.discover_providers(provider_dir)

    assert "broken.py" in str(excinfo.value)


def test_two_modules_claiming_one_provider_name_fail_closed(tmp_path: Path) -> None:
    """Six slices land in parallel; a silently-overwritten block would be a
    lost measurement, so a name collision is an error, not last-writer-wins."""
    provider_dir = tmp_path / "providers"
    body = 'PROVIDER_NAME = "tokens"\n\n\ndef capture(context):\n    return {}\n'
    _write_provider_module(provider_dir, "slice_a.py", body)
    _write_provider_module(provider_dir, "slice_b.py", body)

    with capture_providers.provider_sandbox():
        with pytest.raises(capture_providers.CaptureProviderError) as excinfo:
            capture_providers.discover_providers(provider_dir)

    message = str(excinfo.value)
    assert "slice_a.py" in message and "slice_b.py" in message


def test_shipped_provider_directory_is_discoverable() -> None:
    """The real capture_providers/ directory registers the reference provider,
    which is what makes the file-drop path a Wave-2 slice uses real."""
    with capture_providers.provider_sandbox():
        discovered = capture_providers.discover_providers()

    assert "artifactBytes" in discovered


# --- #1497: the generator must not claim git-history for a gitignored body ---
# `git-history:agent-runtime/artifacts/reviews/...` asserts retrievability that
# .gitignore:82 forbids by policy (ADR-003: emit is not commit). The honest
# claim is `local-only:` -- the body existed locally, here is its sha256, it is
# not retrievable. See tests/unit/test_check_artifact_retention_guard.py for
# the reading half.


def test_gitignored_body_gets_policy_local_scheme(tmp_path: Path, monkeypatch) -> None:
    issue = 1497
    gsr = _seed_bodies(tmp_path, issue, monkeypatch)
    record = gsr.build_status_record(issue)
    assert record is not None

    for field, body_dir, prefix in (
        ("review", "reviews", "review"),
        ("validation", "validation", "validation"),
    ):
        ref = record[field]["artifactRef"]
        rel = f"agent-runtime/artifacts/{body_dir}/{prefix}-issue-{issue}.json"
        # git itself agrees this path is uncommittable, so a git-history claim
        # about it can never be true.
        assert _git("check-ignore", "--quiet", rel).returncode == 0, rel
        assert not ref.startswith("git-history:"), (
            f"{field}.artifactRef claims git history for {rel}, which .gitignore "
            "forbids committing — the claim can never be satisfied"
        )
        assert ref == f"local-only:{rel}", ref

    # The hash claim is unchanged and still honest: it is the digest of the body
    # that was on disk, only the retrievability claim was corrected.
    body = (tmp_path / "reviews" / f"review-issue-{issue}.json").read_bytes()
    assert record["review"]["sha256"] == hashlib.sha256(body).hexdigest()


def test_generated_record_with_policy_local_refs_still_validates_against_schema(
    tmp_path: Path, monkeypatch
) -> None:
    gsr = _seed_bodies(tmp_path, 1497, monkeypatch)
    record = gsr.build_status_record(1497)
    schema = json.loads(STATUS_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert validate_json_schema(record, schema) == []


def test_relabel_corrects_only_v2_policy_local_refs(tmp_path: Path, monkeypatch) -> None:
    """The one-off migration for records already committed under #1438: their
    bodies are gone, so they cannot be regenerated, but their `git-history:`
    label is provably wrong and their sha256 is not. Relabel corrects the label
    and touches nothing else -- and it must leave gateVersion 1 records alone
    (Architect lock, #1445: no backfill) and leave a `git-history:` ref to a
    genuinely committable path alone (it is not a policy-local body)."""
    import generate_status_records as gsr

    status_dir = tmp_path / "status"
    status_dir.mkdir()
    monkeypatch.setattr(gsr, "STATUS_DIR", status_dir)

    def _record(issue: int, gate_version: int, review_ref: str, validation_ref: str) -> dict:
        return {
            "issue": issue,
            "wave": None,
            "review": {"status": "PASS", "artifactRef": review_ref, "sha256": "a" * 64},
            "validation": {
                "status": "PASS",
                "artifactRef": validation_ref,
                "sha256": "b" * 64,
            },
            "gateVersion": gate_version,
        }

    def _body_refs(issue: int) -> tuple[str, str]:
        return (
            f"git-history:agent-runtime/artifacts/reviews/review-issue-{issue}.json",
            f"git-history:agent-runtime/artifacts/validation/validation-issue-{issue}.json",
        )

    v2 = _record(2001, 2, *_body_refs(2001))
    v1 = _record(2002, 1, *_body_refs(2002))
    committable = _record(
        2003,
        2,
        "git-history:backend/src/juli_backend/api/app.py",
        "git-history:backend/src/juli_backend/api/routes/__init__.py",
    )
    for record in (v2, v1, committable):
        (status_dir / f"issue-{record['issue']}.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    changed = gsr.relabel_policy_local_refs()
    assert changed == [2001], changed

    after_v2 = load_json(status_dir / "issue-2001.json")
    assert after_v2["review"]["artifactRef"] == (
        "local-only:agent-runtime/artifacts/reviews/review-issue-2001.json"
    )
    assert after_v2["validation"]["artifactRef"] == (
        "local-only:agent-runtime/artifacts/validation/validation-issue-2001.json"
    )
    # sha256 untouched: relabelling corrects a retrievability claim, never a hash.
    assert after_v2["review"]["sha256"] == "a" * 64
    assert after_v2["validation"]["sha256"] == "b" * 64

    # gateVersion 1 is not backfilled.
    assert load_json(status_dir / "issue-2002.json")["review"]["artifactRef"] == (
        "git-history:agent-runtime/artifacts/reviews/review-issue-2002.json"
    )
    # Committable paths keep their git-history claim, and therefore keep failing
    # the guard if they do not resolve. Relabelling is not a laundering tool.
    untouched = load_json(status_dir / "issue-2003.json")
    assert untouched["review"]["artifactRef"] == ("git-history:backend/src/juli_backend/api/app.py")
    assert untouched["validation"]["artifactRef"] == (
        "git-history:backend/src/juli_backend/api/routes/__init__.py"
    )

    # Idempotent: a second pass changes nothing.
    assert gsr.relabel_policy_local_refs() == []


def test_no_committed_status_record_claims_git_history_for_a_gitignored_body() -> None:
    """Corpus-level invariant: no gateVersion 2 record may assert retrievability
    for a path policy forbids committing. (gateVersion 1 records are exempt --
    they are not backfilled.)"""
    status_dir = REPO_ROOT / "agent-runtime" / "artifacts" / "status"
    offenders = []
    for path in sorted(status_dir.glob("issue-*.json")):
        record = load_json(path)
        if not isinstance(record, dict) or record.get("gateVersion") != 2:
            continue
        for field in ("review", "validation"):
            ref = (record.get(field) or {}).get("artifactRef", "")
            if not ref.startswith("git-history:"):
                continue
            rel = ref[len("git-history:") :]
            if _git("check-ignore", "--quiet", rel).returncode == 0:
                offenders.append(f"{path.name}:{field} -> {ref}")
    assert not offenders, (
        "gateVersion 2 records claiming git history for gitignored bodies: " + ", ".join(offenders)
    )
