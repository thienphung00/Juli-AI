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
