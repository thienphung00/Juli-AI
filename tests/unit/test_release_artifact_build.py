"""CI-built release artifacts (Issue #837, slice P0-DEL-ARTIFACT, PRD #820).

PRD #820 moves application builds off the 2 vCPU / 4 GB server and into CI: CI
produces a release artifact tied to an exact commit, and the server's remaining
job is to start processes, never to compile.

`ADR-058 <../../docs/adr/058-release-packaging-shape.md>`_ fixed the packaging
shape this slice must produce — **build output plus a production dependency
install**, not ``output: 'standalone'`` — and stated the contract in two halves:

1. the built output (``.next``) for each deployable, and
2. its production dependency tree, *resolved in CI*, not resolved again on the
   server.

That is why "no build step on the server" here means removing both
``pnpm install --frozen-lockfile`` and ``turbo run build`` from what the server
executes.

Two deliberate choices about *how* this module asserts:

* It parses ``release.yml`` as data and asserts on job/step **structure and
  ordering**, not on YAML strings, so a reformat does not break it.
* Where it can, it *executes* the artifact builder and asserts on the artifact's
  own metadata and on the absence of a tarball. A success-marker grep over CI
  logs cannot see a job that failed before it logged anything, so log text is
  never treated as evidence here.

Out of scope by design (see the #837 evidence plan): delivering the artifact to
the server, starting a candidate from it, and cutover — those are #838 and #841.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
ARTIFACT_SCRIPT = ROOT / "infra" / "scripts" / "build-release-artifact.sh"
BUILD_DEMO_SCRIPT = ROOT / "infra" / "scripts" / "build-demo.sh"
DEPLOY_DEMO_SCRIPT = ROOT / "infra" / "scripts" / "deploy-demo-release.sh"
DEMO_PLAYWRIGHT_CONFIG = ROOT / "apps" / "demo" / "playwright.config.ts"

ARTIFACT_JOB = "app-release-artifact"
DEPLOYABLES = {"demo", "landing"}

# A commit-shaped value that is not this repo's HEAD, so a metadata document
# echoing it proves the value was threaded through rather than re-derived.
FAKE_COMMIT = "0123456789abcdef0123456789abcdef01234567"

# Every way this repo knows to compile or resolve a JS application. The server
# must run none of them (ADR-058).
BUILD_INVOCATIONS = (
    "pnpm install",
    "npm ci",
    "npm install",
    "turbo run build",
    "pnpm build:demo",
    "pnpm build:landing",
    "next build",
    "npm run build",
)


def _workflow() -> dict[str, Any]:
    return yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))


def _artifact_job() -> dict[str, Any]:
    jobs = _workflow()["jobs"]
    assert ARTIFACT_JOB in jobs, (
        f"release.yml has no {ARTIFACT_JOB!r} job; CI must build the application "
        f"artifact. Found jobs: {sorted(jobs)}"
    )
    return jobs[ARTIFACT_JOB]


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return list(job["steps"])


def _step_text(step: dict[str, Any]) -> str:
    """Everything a step can execute or parameterise, flattened for searching."""
    parts = [
        str(step.get("run", "")),
        str(step.get("uses", "")),
        str(step.get("name", "")),
    ]
    parts.extend(f"{key}={value}" for key, value in (step.get("with") or {}).items())
    parts.extend(f"{key}={value}" for key, value in (step.get("env") or {}).items())
    return "\n".join(parts)


def _index_of(steps: list[dict[str, Any]], needle: str) -> int:
    for index, step in enumerate(steps):
        if needle in _step_text(step):
            return index
    raise AssertionError(
        f"no step in {ARTIFACT_JOB} references {needle!r}; steps were: "
        f"{[step.get('name') or step.get('uses') for step in steps]}"
    )


def _upload_step_index(steps: list[dict[str, Any]]) -> int:
    for index, step in enumerate(steps):
        if str(step.get("uses", "")).startswith("actions/upload-artifact"):
            return index
    raise AssertionError(f"{ARTIFACT_JOB} never uploads anything")


def _run_artifact_script(
    tmp_path: Path, *extra_args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    # Without this, a missing script would make bash exit non-zero and the
    # "a failed build produces no artifact" assertions would pass vacuously.
    assert ARTIFACT_SCRIPT.exists(), f"{ARTIFACT_SCRIPT} does not exist"
    merged = dict(os.environ)
    merged.update(env or {})
    return subprocess.run(
        [
            "bash",
            str(ARTIFACT_SCRIPT),
            "--app",
            "demo",
            "--commit",
            FAKE_COMMIT,
            "--out",
            str(tmp_path),
            *extra_args,
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env=merged,
    )


# ---------------------------------------------------------------------------
# CI produces a release artifact for each deployable
# ---------------------------------------------------------------------------


def test_ci_builds_an_application_artifact_for_each_deployable() -> None:
    job = _artifact_job()
    matrix = (job.get("strategy") or {}).get("matrix") or {}
    apps = {str(entry) for entry in matrix.get("app", [])}
    assert DEPLOYABLES <= apps, (
        f"{ARTIFACT_JOB} must build an artifact for every Next deployable "
        f"{sorted(DEPLOYABLES)}; its matrix covers {sorted(apps)}"
    )


def test_artifact_job_delegates_to_the_ci_artifact_builder() -> None:
    assert ARTIFACT_SCRIPT.exists(), f"{ARTIFACT_SCRIPT} does not exist"
    steps = _steps(_artifact_job())
    _index_of(steps, "build-release-artifact.sh")


def test_release_metadata_job_is_not_repurposed_into_the_application_artifact() -> None:
    """`generate-release-artifact` is release *metadata* and predates this slice.

    Conflating the two concepts would silently drop provenance, so assert the
    metadata job still exists and still uploads its JSON document.
    """
    jobs = _workflow()["jobs"]
    assert "generate-release-artifact" in jobs
    steps = _steps(jobs["generate-release-artifact"])
    uploaded = steps[_upload_step_index(steps)]
    assert str(uploaded["with"]["path"]).endswith(".json")


# ---------------------------------------------------------------------------
# The artifact is traceable to an exact commit
# ---------------------------------------------------------------------------


def test_artifact_metadata_records_the_exact_commit(tmp_path: Path) -> None:
    """Executed, not grepped: the metadata document must carry the commit."""
    result = _run_artifact_script(tmp_path, "--metadata-only")
    assert result.returncode == 0, result.stderr

    metadata_files = sorted(tmp_path.rglob("release-artifact.json"))
    assert metadata_files, (
        f"--metadata-only wrote no release-artifact.json under {tmp_path}; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    document = json.loads(metadata_files[0].read_text(encoding="utf-8"))

    assert document["commit"] == FAKE_COMMIT
    assert FAKE_COMMIT.startswith(document["commitShort"])
    assert document["app"] == "demo"


def test_artifact_metadata_names_the_packaging_shape_adr_058_fixed(
    tmp_path: Path,
) -> None:
    result = _run_artifact_script(tmp_path, "--metadata-only")
    assert result.returncode == 0, result.stderr
    document = json.loads(
        sorted(tmp_path.rglob("release-artifact.json"))[0].read_text(encoding="utf-8")
    )
    assert document["packagingShape"] == "build-output-plus-production-dependencies"
    assert "058" in document["packagingShapeDecision"]


def test_artifact_builder_rejects_an_unknown_deployable(tmp_path: Path) -> None:
    assert ARTIFACT_SCRIPT.exists(), f"{ARTIFACT_SCRIPT} does not exist"
    result = subprocess.run(
        [
            "bash",
            str(ARTIFACT_SCRIPT),
            "--app",
            "dashboard",
            "--commit",
            FAKE_COMMIT,
            "--out",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert result.returncode != 0
    assert not list(tmp_path.glob("*.tar.gz"))


# ---------------------------------------------------------------------------
# A build failure produces no artifact
# ---------------------------------------------------------------------------


def test_a_failed_build_produces_no_artifact(tmp_path: Path) -> None:
    """The binding assertion is the tarball's absence, not a log line.

    A job that dies before it logs leaves no output at all, so a success-marker
    grep would pass vacuously here. Assert on the artifact itself.
    """
    result = _run_artifact_script(
        tmp_path,
        env={
            "RELEASE_ARTIFACT_INSTALL_CMD": "true",
            "RELEASE_ARTIFACT_BUILD_CMD": "false",
        },
    )
    assert result.returncode != 0, "a failing build must fail the artifact job"
    assert not list(tmp_path.rglob("*.tar.gz")), (
        f"a failed build left an artifact behind: {[p.name for p in tmp_path.rglob('*.tar.gz')]}"
    )


def test_no_artifact_job_step_swallows_its_own_failure() -> None:
    """`continue-on-error` or an `always()` guard would publish after a failure."""
    job = _artifact_job()
    assert not job.get("continue-on-error")
    for step in _steps(job):
        assert not step.get("continue-on-error"), f"step {step.get('name')!r} swallows failure"
        assert "always()" not in str(step.get("if", "")), (
            f"step {step.get('name')!r} runs after failure"
        )


def test_upload_is_the_final_step_and_an_empty_upload_fails() -> None:
    steps = _steps(_artifact_job())
    upload_index = _upload_step_index(steps)
    assert upload_index == len(steps) - 1, "publishing must be the last thing the job does"
    assert steps[upload_index]["with"]["if-no-files-found"] == "error"


# ---------------------------------------------------------------------------
# Browser-level checks run in CI against the artifact, before it ships
# ---------------------------------------------------------------------------


def test_browser_checks_run_against_the_artifact_before_it_is_published() -> None:
    steps = _steps(_artifact_job())
    browser_index = _index_of(steps, "DEMO_E2E_ARTIFACT_DIR")
    build_index = _index_of(steps, "build-release-artifact.sh")
    upload_index = _upload_step_index(steps)
    assert build_index < browser_index < upload_index, (
        "the browser gate must sit between building the artifact and publishing it "
        f"(build={build_index}, browser={browser_index}, upload={upload_index})"
    )


def test_browser_gate_extends_the_existing_demo_exit_gate_suite() -> None:
    """Extend `demo-e2e`'s Playwright suite rather than build a parallel one."""
    steps = _steps(_artifact_job())
    browser_step = steps[_index_of(steps, "DEMO_E2E_ARTIFACT_DIR")]
    assert "test:e2e" in _step_text(browser_step), (
        "the browser gate must run apps/demo's existing exit-gate Playwright suite"
    )


def test_playwright_starts_from_the_artifact_instead_of_rebuilding() -> None:
    config = DEMO_PLAYWRIGHT_CONFIG.read_text(encoding="utf-8")
    assert "DEMO_E2E_ARTIFACT_DIR" in config, (
        "playwright.config.ts must accept an already-built artifact directory; "
        "otherwise the browser gate verifies a fresh rebuild, not the artifact"
    )
    # The rebuild path must be conditional on the artifact dir being absent.
    artifact_clause = config.split("DEMO_E2E_ARTIFACT_DIR", 1)[1]
    assert "build:demo" in artifact_clause, (
        "the rebuild command must remain, but behind the artifact-directory branch"
    )


# ---------------------------------------------------------------------------
# No application build step runs on the server
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("script", [BUILD_DEMO_SCRIPT, DEPLOY_DEMO_SCRIPT])
def test_server_executed_scripts_never_compile_the_application(script: Path) -> None:
    body = script.read_text(encoding="utf-8")
    executable = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("#"))
    offenders = [needle for needle in BUILD_INVOCATIONS if needle in executable]
    assert not offenders, (
        f"{script.name} still runs {offenders} on the server; ADR-058 requires both "
        "the build and the dependency resolution to happen in CI"
    )


def test_server_demo_script_still_verifies_the_prebuilt_output() -> None:
    """#844 removes the script; until then it must fail loudly on a missing artifact."""
    body = BUILD_DEMO_SCRIPT.read_text(encoding="utf-8")
    assert ".next/server/app/decisions.html" in body
    assert ".next/static" in body
    assert "node_modules/.bin/next" in body


def test_artifact_builder_resolves_production_dependencies_in_ci() -> None:
    """ADR-058's second half: the dependency tree ships resolved, from CI."""
    body = ARTIFACT_SCRIPT.read_text(encoding="utf-8")
    executable = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("#"))
    assert "--prod" in executable, "the artifact must carry a production dependency tree"


def test_artifact_builder_does_not_drift_toward_standalone_packaging() -> None:
    """ADR-058 rejected `output: 'standalone'`; `outputFileTracingRoot` is its tell.

    Comments are stripped first: the script is *expected* to name standalone in
    prose, warning the next reader off it. What must not appear is an executable
    line that enables it.
    """
    executable = "\n".join(
        line
        for line in ARTIFACT_SCRIPT.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    assert "standalone" not in executable
    assert "outputFileTracingRoot" not in executable
