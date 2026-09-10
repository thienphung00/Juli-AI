"""The PR-tier release-shape job must keep reproducing `release.yml`'s build (#1893).

`release.yml`'s build job runs `pytest tests/` -- the whole tree in ONE invocation
against ONE database. Every other test job runs `tests/unit` and `tests/integration`
separately, unit first, so a unit test never sees rows an integration fixture left
behind. Release is the only place it does.

That asymmetry is invisible until it blocks a deploy, because a red `build` skips
`deploy`. It has done so three times (#1402, #1739, and the 2026-09-10
credential-refresh outage fix, where release saw `assert 23 == 2` for a test that
was green on every PR check).

`release-shape.yml` exists to run that shape where an author can still see it.
These tests fail if the two drift apart -- otherwise the job could keep passing
while quietly no longer reproducing what release does.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PR_WORKFLOW = REPO_ROOT / ".github/workflows/pr.yml"
SHAPE_WORKFLOW = REPO_ROOT / ".github/workflows/release-shape.yml"
RELEASE_WORKFLOW = REPO_ROOT / ".github/workflows/release.yml"


def _load(path: Path) -> dict:
    assert path.exists(), f"{path} does not exist"
    return yaml.safe_load(path.read_text())


def _run_blocks(job: dict) -> list[str]:
    return [
        step["run"] for step in job.get("steps", []) if isinstance(step, dict) and "run" in step
    ]


def _pytest_invocation(job: dict) -> list[str]:
    """The job's `pytest tests/ ...` call, as a normalised token list.

    Joins shell line-continuations and drops comments so that reformatting the
    YAML cannot make two identical commands compare unequal.
    """
    for block in _run_blocks(job):
        joined = block.replace("\\\n", " ")
        for line in joined.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.match(r"^(python -X faulthandler -m )?pytest tests/\s", stripped + " "):
                return stripped.split()
    return []


@pytest.fixture(scope="module")
def pr_jobs() -> dict:
    return _load(SHAPE_WORKFLOW)["jobs"]


@pytest.fixture(scope="module")
def release_build() -> dict:
    return _load(RELEASE_WORKFLOW)["jobs"]["build"]


def test_pr_defines_a_release_shape_job(pr_jobs: dict) -> None:
    assert "release-shape" in pr_jobs, (
        "release-shape.yml lost its `release-shape` job. Without it, nothing at PR tier runs "
        "release's single-invocation shape, and the next order-dependent test "
        "blocks a production deploy instead of failing on the PR that wrote it."
    )


def test_release_shape_runs_the_same_pytest_command_as_release(
    pr_jobs: dict, release_build: dict
) -> None:
    release_cmd = _pytest_invocation(release_build)
    pr_cmd = _pytest_invocation(pr_jobs["release-shape"])

    assert release_cmd, "could not find release.yml build's `pytest tests/` invocation"
    assert pr_cmd, "could not find release-shape.yml's `pytest tests/` invocation"
    assert pr_cmd == release_cmd, (
        "release-shape.yml no longer runs the same command as release.yml's "
        "build job, so it has stopped reproducing the shape it exists to reproduce.\n"
        f"  release.yml:       {' '.join(release_cmd)}\n"
        f"  release-shape.yml: {' '.join(pr_cmd)}"
    )


def test_release_shape_runs_one_invocation_over_the_whole_tree(pr_jobs: dict) -> None:
    """A split into unit/integration would defeat the job's entire purpose."""
    cmd = _pytest_invocation(pr_jobs["release-shape"])
    assert "tests/" in cmd, f"expected the whole tree, got {' '.join(cmd)}"
    for narrower in ("tests/unit", "tests/integration"):
        assert narrower not in cmd, (
            f"release-shape narrowed to {narrower}. The bug class it catches only "
            "appears when both run in one collection, integration first."
        )

    invocations = [
        line
        for block in _run_blocks(pr_jobs["release-shape"])
        for line in block.replace("\\\n", " ").splitlines()
        if "pytest" in line and not line.strip().startswith("#")
    ]
    assert len(invocations) == 1, (
        f"release-shape must run pytest exactly once; found {len(invocations)}. "
        "Two invocations are two processes, which is the very isolation that hides "
        "the defect."
    )


def test_release_shape_provisions_the_same_services_as_release(
    pr_jobs: dict, release_build: dict
) -> None:
    """Release has Postgres and no Redis; a differently-provisioned job is a different test."""
    assert set(pr_jobs["release-shape"].get("services", {})) == set(
        release_build.get("services", {})
    ), (
        "release-shape's services no longer match release.yml's build. Tests behave "
        "differently by which backing services exist, so this job would stop "
        "predicting whether release will pass."
    )


def test_release_shape_checks_out_shallow_like_release(pr_jobs: dict) -> None:
    """`fetch-depth` would make this job strictly better-provisioned than release."""
    for step in pr_jobs["release-shape"]["steps"]:
        if isinstance(step, dict) and str(step.get("uses", "")).startswith("actions/checkout"):
            assert "fetch-depth" not in (step.get("with") or {}), (
                "release-shape deepened its checkout. release.yml checks out shallow, "
                "and the deselected branch-relative tests are deselected precisely "
                "because of that; deepening here makes the two shapes diverge."
            )
            return
    pytest.fail("release-shape has no checkout step")


def test_the_release_shape_lane_stays_out_of_pr_yml() -> None:
    """It must not be moved into pr.yml, however natural that looks.

    `command_scope.ci_selectors()` derives "CI's scope" from the broadest pytest
    lane in pr.yml -- the one deselecting the fewest markers. This lane deselects
    none by design, so putting it in pr.yml makes it the reference, and then every
    executor citing `pytest tests/ -m "not live and not demo_contract"` scores as
    NARROWER than CI (`extra_deselected_markers`) for no reason connected to this
    gate. Verified 2026-09-10: doing so turned that reference into an empty set
    and failed `test_ci_selectors_are_read_from_the_real_pr_yml`.
    """
    pr_yml = _load(PR_WORKFLOW)["jobs"]
    assert "release-shape" not in pr_yml, (
        "the release-shape lane moved into pr.yml, which silently rewrites the CI "
        "scope reference every executor's cited command is judged against. Keep it "
        "in release-shape.yml."
    )
    for name, job in pr_yml.items():
        for cmd in (_pytest_invocation(job),):
            if cmd and "tests/" in cmd and "-m" not in cmd:
                pytest.fail(
                    f"pr.yml job {name!r} runs the whole tree with no marker filter, "
                    "which becomes command_scope's CI scope reference. See this test's docstring."
                )
