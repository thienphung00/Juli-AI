"""Unit tests for Meta workflow-cache ensure (no network)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(CI_DIR))
sys.path.insert(0, str(REPO_ROOT / "agent-runtime" / "scripts"))

from ensure_workflow_cache import (  # noqa: E402
    ensure_workflow_caches,
    in_scope_paths_for_epic,
    load_issue_prepare_overlay,
    load_runtime_config,
    parse_parent_issue_id,
    parse_slice_id,
    refresh_in_scope,
    resolve_linkage,
    single_domain_harness_utility,
    unescape_scope_block,
)
from issue_load_profile import load_slice_routing_rules  # noqa: E402


def test_parse_parent_and_slice_from_issue_body() -> None:
    body = "## Parent\n#419\n\nSlice: P2-OPS-1\n\n## Acceptance criteria\n- one\n"
    assert parse_parent_issue_id(body) == 419
    assert parse_slice_id(body) == "P2-OPS-1"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        # Forms that worked before the label was admitted. These are the
        # regression half: the widening must not have moved any of them.
        ("## Parent\n#419\n", 419),
        ("## Parent\n1228\n", 1228),
        ("Parent: 55\n", 55),
        ("Part of #66\n", 66),
        # `to-issues` emitted this for all 17 W4/W5 issues, and it parsed as
        # nothing -- so `meta_prepare_executor` halted on every one of them
        # with "Cannot resolve parent". That is a mandatory gate, and a gate
        # that always halts is one operators learn to route around.
        ("## Parent\nPRD #1228\n", 1228),
        ("## Parent\nEpic #77\n", 77),
        ("## Parent\nIssue #12\n", 12),
    ],
)
def test_parent_line_accepts_an_optional_enumerated_label(body: str, expected: int) -> None:
    assert parse_parent_issue_id(body) == expected


@pytest.mark.parametrize(
    "body",
    [
        # The label set is enumerated rather than `\w+` precisely so these
        # keep failing loudly. A generic word class would resolve #5 and #1219
        # here -- briefing an Executor against a confidently wrong parent,
        # which is strictly worse than the halt it replaced.
        "## Parent\nSee #5 for context\n",
        "## Parent\nBlocked by #1219\n",
        "## Parent\nNone - can start immediately\n",
    ],
)
def test_parent_line_rejects_an_unenumerated_label(body: str) -> None:
    assert parse_parent_issue_id(body) is None


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


def test_resolve_linkage_reads_issue_prepare_overlay(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    prepare_dir = repo / "agent-runtime" / "config" / "issue-prepare"
    prepare_dir.mkdir(parents=True)
    (prepare_dir / "615.yml").write_text(
        "\n".join(
            [
                "parentIssueId: 602",
                "sliceId: CDP-A2-1",
                "handoffPath: docs/handoffs/phase-3.5-prd-bodies/a2-batch.md",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    cfg = {"workflow_prompt_cache": {"epicRegistry": {}}}

    linkage = resolve_linkage(
        issue_id=615,
        issue_body="## Acceptance criteria\n- stagger scheduler\n",
        config=cfg,
        repo_root=repo,
    )

    assert linkage["parentIssueId"] == 602
    assert linkage["sliceId"] == "CDP-A2-1"
    assert linkage["handoffPath"] == "docs/handoffs/phase-3.5-prd-bodies/a2-batch.md"


def test_load_slice_routing_rules_merges_overlay(tmp_path: Path) -> None:
    config_dir = tmp_path / "agent-runtime" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "slice-routing.yml").write_text(
        "BASE-SLICE:\n  executorDomain: backend\n  requiredDocs: []\n  requiredModules: []\n",
        encoding="utf-8",
    )
    slices_dir = config_dir / "slices"
    slices_dir.mkdir()
    (slices_dir / "CDP-A2-1.yml").write_text(
        "\n".join(
            [
                "CDP-A2-1:",
                "  executorDomain: backend",
                "  requiredDocs:",
                "    - EXECUTION.md",
                "  requiredModules:",
                "    - backend/src/juli_backend/services/cdp_batch/stagger_scheduler.py",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rules = load_slice_routing_rules(config_dir / "slice-routing.yml")

    assert "BASE-SLICE" in rules
    assert rules["CDP-A2-1"]["requiredModules"] == [
        "backend/src/juli_backend/services/cdp_batch/stagger_scheduler.py"
    ]


def test_issue_prepare_overlay_cli_precedence(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    prepare_dir = repo / "agent-runtime" / "config" / "issue-prepare"
    prepare_dir.mkdir(parents=True)
    (prepare_dir / "615.yml").write_text(
        "parentIssueId: 602\nsliceId: CDP-A2-1\nhandoffPath: docs/from-overlay.md\n",
        encoding="utf-8",
    )
    cfg = {"workflow_prompt_cache": {"epicRegistry": {}}}

    linkage = resolve_linkage(
        issue_id=615,
        issue_body="",
        config=cfg,
        parent_issue_id=999,
        slice_id="CLI-SLICE",
        handoff_path="docs/from-cli.md",
        repo_root=repo,
    )

    assert linkage["parentIssueId"] == 999
    assert linkage["sliceId"] == "CLI-SLICE"
    assert linkage["handoffPath"] == "docs/from-cli.md"
    assert load_issue_prepare_overlay(615, repo)["sliceId"] == "CDP-A2-1"


# --- #1583: the scope document must carry the epic's authorised paths --------


def test_a_stale_cache_without_authorised_paths_is_refreshed_not_kept() -> None:
    """#1583: `inScope` is persisted in the child cache, so `.get("inScope") or ...`
    keeps whatever a previous run wrote.

    Found while verifying the fix end-to-end: regenerating the scope document for
    a real issue still produced the old two-line list, because the cache from
    before the fix already had one. Every cache written before this change is in
    that state, so without a refresh the fix reaches only new issues — and the
    executors it exists to unblock are working on issues that already have caches.
    """
    stale = ["Slice CI-WAVE-1 acceptance criteria", "Executor domain: backend"]
    authorised = in_scope_paths_for_epic({"inScopePaths": ["agent-runtime/", "eval/"]})
    assert authorised, "fixture must name paths or this asserts nothing"

    refreshed = refresh_in_scope(stale, authorised, parent_id=1434)
    assert any("agent-runtime/" in line for line in refreshed), (
        "a cache written before this change keeps its pathless inScope, so the "
        "executor still sees prohibitions without authorisations"
    )
    # Refreshing must not drop what was already there.
    for line in stale:
        assert any(line in r for r in refreshed), f"refresh lost {line!r}"
    # And it must be idempotent -- running twice must not double the entry.
    assert refresh_in_scope(refreshed, authorised, parent_id=1434) == refreshed


def test_no_epic_authorises_a_path_its_own_scope_block_forbids() -> None:
    """#1583: the first version of this mined paths out of prose, skipping lines
    that matched prohibition marker phrases. Review defeated it, and a scan of
    the real registry showed why: **24 distinct leaks across 38 epics**.

    Epic #1325 authorised `core/security/dependencies.py` off a line reading
    "W6 IS RUNNING IN PARALLEL AND OWNS THESE FILES. Never edit: ..." — a
    security-relevant epic, handed an executor exactly the file another lane
    owns. Others leaked `UI/UX`, `I/O`, `W7/W8` and a bare `/` as though they
    were directories.

    A denylist over natural language cannot be made safe by adding phrases; the
    next epic writes a prohibition in wording nobody enumerated. Authorisation
    must be declared, not inferred. This test runs over the whole shipped
    registry so a new epic cannot reintroduce the class.
    """
    cfg = load_runtime_config(REPO_ROOT)
    registry = (cfg.get("workflow_prompt_cache") or {}).get("epicRegistry") or {}
    assert registry, "epicRegistry is empty; this test would assert nothing"

    prohibition = re.compile(
        r"must not|off-limits|excluded|restricted|not yours|do not|no product|never",
        re.IGNORECASE,
    )
    leaks: list[str] = []
    for epic_id, entry in registry.items():
        block = unescape_scope_block(entry.get("parentScopeBlock") or "")
        for path in in_scope_paths_for_epic(entry):
            for line in block.splitlines():
                if path in line and prohibition.search(line):
                    leaks.append(f"#{epic_id}: {path!r} from {line.strip()[:80]!r}")
    assert leaks == [], "authorised paths taken from prohibition lines:\n" + "\n".join(leaks[:8])


def test_authorised_paths_are_declared_not_inferred() -> None:
    """The registry entry declares them; nothing is parsed out of prose."""
    assert in_scope_paths_for_epic({}) == []
    assert in_scope_paths_for_epic({"parentScopeBlock": "- Harness only: eval/, apps/"}) == [], (
        "paths were inferred from the scope block; declaration is the only source"
    )
    assert in_scope_paths_for_epic({"inScopePaths": ["eval/", "tests/unit/"]}) == [
        "eval/",
        "tests/unit/",
    ]
