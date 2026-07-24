"""Unit tests for Meta workflow-cache ensure (no network)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(CI_DIR))
sys.path.insert(0, str(REPO_ROOT / "agent-runtime" / "scripts"))

from ensure_workflow_cache import (  # noqa: E402
    ensure_workflow_caches,
    load_runtime_config,
    parse_parent_issue_id,
    parse_slice_id,
    single_domain_harness_utility,
)


def test_parse_parent_and_slice_from_issue_body() -> None:
    body = "## Parent\n#419\n\nSlice: P2-OPS-1\n\n## Acceptance criteria\n- one\n"
    assert parse_parent_issue_id(body) == 419
    assert parse_slice_id(body) == "P2-OPS-1"


def test_single_domain_harness_utility_never_dual() -> None:
    harness = single_domain_harness_utility("backend")
    skills = harness["skills"]
    assert len(skills) == 1
    assert skills[0]["path"].endswith("/domain/backend/SKILL.md")


def test_ensure_workflow_caches_bootstraps_parent_and_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    (repo / "agent-runtime" / "config").mkdir(parents=True)
    (repo / "agent-runtime" / "artifacts" / "workflow-cache").mkdir(parents=True)
    (repo / "docs" / "adr").mkdir(parents=True)
    (repo / "EXECUTION.md").write_text("## Phase 2\n- [x] **P2-OPS-1** ops\n", encoding="utf-8")
    (repo / "docs" / "adr" / "027-database-migration-safety-pipeline.md").write_text(
        "# ADR 027\n", encoding="utf-8"
    )

    (repo / "agent-runtime" / "config" / "agent-runtime.config.yml").write_text(
        "\n".join(
            [
                "version: 1",
                "workflow_prompt_cache:",
                "  artifactsDir: agent-runtime/artifacts/workflow-cache",
                "  requireValidCacheBeforeExecutor: true",
                "  ensureOnMetaEntry: true",
                "  bootstrap:",
                "    pinBranch: HEAD",
                "    sourcePaths:",
                "      - .cursor/skills",
                "  epicRegistry:",
                "    419:",
                "      defaultSliceId: P2-OPS-1",
                "      handoffPath: docs/adr/027-database-migration-safety-pipeline.md",
                "      parentScopeBlock: '# Parent 419'",
                "      doNotLoad:",
                "        - web/",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "agent-runtime" / "config" / "slice-routing.yml").write_text(
        "\n".join(
            [
                "P2-OPS-1:",
                "  executorDomain: backend",
                "  requiredDocs:",
                "    - docs/adr/027-database-migration-safety-pipeline.md",
                "  requiredModules:",
                "    - infra/scripts/safe_alembic_helpers.py",
                "  loadWhenNeeded: []",
                "  doNotLoad:",
                "    - web/",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    bodies = {
        420: "## Parent\n#419\n\n## Acceptance criteria\n- Local gate works\n",
        419: "# Parent PRD\n",
    }

    import ensure_workflow_cache as ewc
    import issue_load_profile as ilp

    monkeypatch.setattr(
        ewc,
        "bootstrap_ref_from_git",
        lambda branch, repo_root, copied_at=None: {
            "branch": branch,
            "commitSha": "a" * 40,
            "copiedAt": "2026-07-21T00:00:00Z",
        },
    )
    monkeypatch.setattr(
        ewc,
        "build_parent_upstream_fingerprints",
        lambda **kwargs: [
            {"path": f"GitHub issue #{kwargs['parent_issue_id']}", "fingerprint": "p" * 16},
            {"path": kwargs["handoff_path"], "fingerprint": "h" * 40},
            {"path": "EXECUTION.md", "fingerprint": "e" * 40},
        ],
    )
    monkeypatch.setattr(
        ewc,
        "build_child_upstream_fingerprints",
        lambda **kwargs: [
            {"path": f"GitHub issue #{kwargs['issue_id']}", "fingerprint": "c" * 16},
            {"path": kwargs["scope_alignment_path"], "fingerprint": "s" * 40},
        ],
    )
    monkeypatch.setattr(
        ilp,
        "SLICE_ROUTING_CONFIG",
        repo / "agent-runtime" / "config" / "slice-routing.yml",
    )
    monkeypatch.setattr(
        ewc,
        "load_slice_routing_rules",
        lambda config_path=None: ilp.load_slice_routing_rules(
            repo / "agent-runtime" / "config" / "slice-routing.yml"
        ),
    )

    cfg = load_runtime_config(repo)
    summary = ensure_workflow_caches(
        420,
        repo_root=repo,
        config=cfg,
        issue_body_fetcher=lambda iid: bodies[iid],
        issue_labels_fetcher=lambda _iid: [],
    )

    assert summary["readyForExecutor"] is True
    assert summary["parentIssueId"] == 419
    assert summary["sliceId"] == "P2-OPS-1"
    assert summary["executorDomain"] == "backend"

    child_path = repo / summary["childCachePath"]
    parent_path = repo / summary["parentCachePath"]
    assert child_path.exists()
    assert parent_path.exists()
    child = json.loads(child_path.read_text(encoding="utf-8"))
    assert child["cacheStatus"] == "valid"
    assert child["parentIssueId"] == 419
    assert child["publicRelease"] is False
    assert child["publicReleaseReasons"] == []
    assert len(child["harnessUtility"]["skills"]) == 1
    assert (repo / child["scopeAlignmentPath"]).exists()


def test_ensure_persists_label_only_public_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    (repo / "agent-runtime" / "config").mkdir(parents=True)
    (repo / "agent-runtime" / "artifacts" / "workflow-cache").mkdir(parents=True)
    (repo / "docs" / "adr").mkdir(parents=True)
    (repo / "EXECUTION.md").write_text("## Phase 2\n- [x] **P2-OPS-1** ops\n", encoding="utf-8")
    (repo / "docs" / "adr" / "027-database-migration-safety-pipeline.md").write_text(
        "# ADR 027\n", encoding="utf-8"
    )
    (repo / "agent-runtime" / "config" / "agent-runtime.config.yml").write_text(
        "\n".join(
            [
                "version: 1",
                "workflow_prompt_cache:",
                "  artifactsDir: agent-runtime/artifacts/workflow-cache",
                "  requireValidCacheBeforeExecutor: true",
                "  ensureOnMetaEntry: true",
                "  bootstrap:",
                "    pinBranch: HEAD",
                "    sourcePaths:",
                "      - .cursor/skills",
                "  epicRegistry:",
                "    419:",
                "      defaultSliceId: P2-OPS-1",
                "      handoffPath: docs/adr/027-database-migration-safety-pipeline.md",
                "      parentScopeBlock: '# Parent 419'",
                "      doNotLoad:",
                "        - web/",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "agent-runtime" / "config" / "slice-routing.yml").write_text(
        "\n".join(
            [
                "P2-OPS-1:",
                "  executorDomain: backend",
                "  requiredDocs:",
                "    - docs/adr/027-database-migration-safety-pipeline.md",
                "  requiredModules:",
                "    - infra/scripts/safe_alembic_helpers.py",
                "  loadWhenNeeded: []",
                "  doNotLoad:",
                "    - web/",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    bodies = {
        420: "## Parent\n#419\n\n## Acceptance criteria\n- Local gate works\n",
        419: "# Parent PRD\n",
    }

    import ensure_workflow_cache as ewc
    import issue_load_profile as ilp

    monkeypatch.setattr(
        ewc,
        "bootstrap_ref_from_git",
        lambda branch, repo_root, copied_at=None: {
            "branch": branch,
            "commitSha": "a" * 40,
            "copiedAt": "2026-07-21T00:00:00Z",
        },
    )
    monkeypatch.setattr(
        ewc,
        "build_parent_upstream_fingerprints",
        lambda **kwargs: [
            {"path": f"GitHub issue #{kwargs['parent_issue_id']}", "fingerprint": "p" * 16},
            {"path": kwargs["handoff_path"], "fingerprint": "h" * 40},
            {"path": "EXECUTION.md", "fingerprint": "e" * 40},
        ],
    )
    monkeypatch.setattr(
        ewc,
        "build_child_upstream_fingerprints",
        lambda **kwargs: [
            {"path": f"GitHub issue #{kwargs['issue_id']}", "fingerprint": "c" * 16},
            {"path": kwargs["scope_alignment_path"], "fingerprint": "s" * 40},
        ],
    )
    monkeypatch.setattr(
        ewc,
        "load_slice_routing_rules",
        lambda config_path=None: ilp.load_slice_routing_rules(
            repo / "agent-runtime" / "config" / "slice-routing.yml"
        ),
    )

    cfg = load_runtime_config(repo)
    summary = ensure_workflow_caches(
        420,
        repo_root=repo,
        config=cfg,
        issue_body_fetcher=lambda iid: bodies[iid],
        issue_labels_fetcher=lambda _iid: ["public-release"],
    )
    child = json.loads((repo / summary["childCachePath"]).read_text(encoding="utf-8"))
    assert child["publicRelease"] is True
    assert "label:public-release" in child["publicReleaseReasons"]
