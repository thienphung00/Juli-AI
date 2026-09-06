"""Historical audit: how much red→green evidence can actually be reproduced.

#1603's third acceptance criterion: "GIVEN the historical implementation
artifacts WHEN they are re-examined THEN the number whose red→green evidence
cannot be reproduced is measured and stated" — so the blast radius of the
defect is known rather than assumed, the way #1603 itself was discovered only
by a reviewer re-running greps by hand.

This module does the tabulation; the actual re-execution is
``differential_tdd``'s job (already used by ``check_differential_tdd.py``).
``run_probe`` is injected on purpose: auditing N historical artifacts by
spawning two real pytest subprocesses each does not scale the way one CI gate
run does, and the counting logic is the part #1603 asks to be "measured and
stated" — it does not need a fresh git checkout per artifact to be correct.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterable

RunProbe = Callable[[int, dict[str, Any]], str]


def audit_artifacts(
    artifacts: Iterable[tuple[int, dict[str, Any]]],
    *,
    run_probe: RunProbe,
) -> dict[str, Any]:
    """Tabulate reproducibility verdicts across a set of implementation artifacts.

    ``run_probe(issue, artifact)`` returns one of ``differential_tdd``'s
    ``VERDICT_*`` constants. Only ``VERDICT_RED_GREEN`` counts as reproduced —
    every other verdict (non-discriminating, still failing, inconclusive,
    nothing to probe) is real evidence that the artifact's claim could not be
    reproduced, and is counted as such rather than silently dropped.
    """
    counts: dict[str, int] = {}
    per_issue: dict[int, str] = {}

    for issue, artifact in artifacts:
        verdict = run_probe(issue, artifact)
        counts[verdict] = counts.get(verdict, 0) + 1
        per_issue[issue] = verdict

    # Imported lazily so a caller that only wants the pure tabulation (as the
    # unit tests above do) never needs differential_tdd's VERDICT constant.
    from differential_tdd import VERDICT_RED_GREEN

    total = sum(counts.values())
    reproducible = counts.get(VERDICT_RED_GREEN, 0)
    return {
        "total": total,
        "reproducible": reproducible,
        "notReproducible": total - reproducible,
        "counts": counts,
        "perIssue": per_issue,
    }


def _iter_implementation_artifacts(
    directory: Path,
) -> Iterable[tuple[int, dict[str, Any]]]:
    """Yield (issue, artifact) for every ``implementation-issue-*.json`` file.

    Malformed filenames or unparsable JSON are skipped rather than raised —
    an audit's job is to measure what it can read, and a single corrupt file
    must not abort the count for every other artifact on disk.
    """
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("implementation-issue-*.json")):
        stem_suffix = path.stem.rsplit("-", 1)[-1]
        if not stem_suffix.isdigit():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        yield int(stem_suffix), data


def audit_directory(directory: Path, *, run_probe: RunProbe) -> dict[str, Any]:
    """Audit every implementation artifact found in ``directory``.

    A missing directory is a real, honest zero (no historical artifacts on
    this machine) rather than an error — these five artifact directories are
    gitignored by design (ADR-003 as amended by #670), so a fresh checkout
    legitimately has none.
    """
    return audit_artifacts(_iter_implementation_artifacts(directory), run_probe=run_probe)


def main() -> int:
    import argparse
    import sys

    ci_dir = Path(__file__).resolve().parent
    if str(ci_dir) not in sys.path:
        sys.path.insert(0, str(ci_dir))
    from common import IMPLEMENTATIONS_DIR
    from differential_tdd import (
        VERDICT_INCONCLUSIVE,
        VERDICT_NOTHING_TO_PROBE,
        classify_probe,
        materialize_base_tree,
        overlay_probes,
        resolve_base_sha,
        run_python_probes,
        select_probe_tests,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=IMPLEMENTATIONS_DIR)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[3]

    def _real_probe(_issue: int, artifact: dict[str, Any]) -> str:
        probes = [p for p in select_probe_tests(artifact) if p.endswith(".py")]
        if not probes:
            return VERDICT_NOTHING_TO_PROBE
        base_sha = resolve_base_sha(repo_root)
        if base_sha is None:
            return VERDICT_INCONCLUSIVE
        import tempfile

        with tempfile.TemporaryDirectory(prefix="repro-audit-") as tmp:
            base_tree = Path(tmp) / "base"
            if not materialize_base_tree(repo_root, base_sha, base_tree):
                return VERDICT_INCONCLUSIVE
            overlaid = overlay_probes(repo_root, base_tree, probes)
            if not overlaid:
                return VERDICT_INCONCLUSIVE
            base_exit, _ = run_python_probes(base_tree, overlaid, sys.executable)
            head_exit, _ = run_python_probes(repo_root, overlaid, sys.executable)
        return classify_probe(base_exit, head_exit)[0]

    result = audit_directory(args.directory, run_probe=_real_probe)
    print(
        f"reproducibility_audit: {result['reproducible']}/{result['total']} reproducible "
        f"({result['notReproducible']} not reproducible) — counts={result['counts']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
