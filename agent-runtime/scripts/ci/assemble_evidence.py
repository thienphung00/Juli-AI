"""Assemble one ``evidence.json`` per run from runner-observed facts (#1458).

The verification pipeline of #1434 — every downstream gate, the claim-versus-
executed comparison and the judge — reads an ``evidence.json`` that nothing in
this repository produced. This module produces it.

**Runner-observed only.** Five sources are merged, each tagged with where it
came from: junit XML, coverage XML, gate results, the environment fingerprint
and the execution trace. Every value is something a process measured — an exit
code, a duration a runner timed, a byte count, ``git rev-parse`` read in the
checkout. Nothing here is a value an agent typed.

Where an agent-authored artifact offers a value that is also observed, the
observed value is what the document records and the claim is preserved beside
it in ``disagreements[]``. That disagreement is not an error path; it is the
eval label the whole epic exists to produce, so it is kept rather than
resolved.

**Unavailable is not zero.** ``tokenUsage`` has no instrumented reading
available to any process in this pipeline, so it is recorded as
``{"available": false, "reason": ...}`` and never as ``0``. A zero reads as a
measurement, and mistaking an unmeasured field for a measured zero is the exact
defect this epic was built to end. ``executionDurationMs`` is the opposite
case: the execution trace carries per-command durations the runner itself
timed, so it *is* observable, and an agent's round number loses to their sum.

**Fail-closed, always** (#1434 lock 2, matching ``capture_providers``). A
source that is absent, unparseable, the wrong document, or missing the fields
that make it evidence rather than prose raises :class:`EvidenceAssemblyError`
naming that source. No document is returned or written. A section silently
missing would make the absence of evidence indistinguishable from evidence of
absence.

Stdlib only, like everything else under ``agent-runtime/scripts/ci/``. The one
non-stdlib dependency is a repo sibling: the environment fingerprint comes from
``capture_providers/environment.py`` (#1442) and is imported, never
reimplemented. If that module is not present, ``environment`` fails closed as
any other missing source would.

Usage::

    python agent-runtime/scripts/ci/assemble_evidence.py \\
        --issue 1458 --junit junit.xml --coverage coverage.xml \\
        --gate-results gate-results.json --trace trace.jsonl \\
        --claims agent-runtime/artifacts/implementations/implementation-issue-1458.json \\
        --out evidence.json
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

EVIDENCE_SCHEMA_VERSION = "1.0.0"

#: Source name -> the provenance ``kind`` its tag must carry. A section tagged
#: with another source's kind is a source impersonating a source, which the
#: verifier rejects: "tagged" has to mean "tagged correctly" or any file could
#: enter the document as any other.
SOURCE_KINDS: dict[str, str] = {
    "junit": "junit-xml",
    "coverage": "coverage-xml",
    "gateResults": "gate-results-json",
    "environment": "environment-fingerprint",
    "trace": "execution-trace-jsonl",
}

#: All five are required. There is no optional source and no "skipped".
REQUIRED_SOURCES: tuple[str, ...] = tuple(SOURCE_KINDS)

#: Why ``tokenUsage`` is unavailable rather than zero. Three independent
#: executors reported the same finding: no instrumented reading exists for it
#: anywhere in this pipeline, so every non-zero historical value is
#: unsourceable and every zero is indistinguishable from a real measurement.
TOKEN_USAGE_UNAVAILABLE = (
    "no instrumented token reading is exposed to the runner; recorded unavailable "
    "rather than 0 so an unmeasured field cannot read as a measured zero"
)

_ENVIRONMENT_PROVIDER = "capture_providers.environment.fingerprint"


class EvidenceAssemblyError(RuntimeError):
    """A source could not be turned into evidence. Never swallowed, never skipped.

    Carries :attr:`source` so a caller can name the offender instead of
    reporting a generic assembly failure.
    """

    def __init__(self, source: str, cause: BaseException | str) -> None:
        self.source = source
        super().__init__(f"evidence source {source!r} failed: {cause}")


# ---------------------------------------------------------------------------
# Availability — the shape that makes "unmeasured" unmistakable.
# ---------------------------------------------------------------------------


def observed(value: Any, source: str) -> dict[str, Any]:
    """A measured value, with the source that measured it."""
    return {"available": True, "value": value, "observedFrom": source}


def unavailable(reason: str) -> dict[str, Any]:
    """An unmeasured field. Deliberately carries no ``value`` key at all.

    Omitting the key rather than setting it to ``None`` or ``0`` means a
    consumer that forgets to check ``available`` gets a ``KeyError`` instead of
    a plausible number.
    """
    return {"available": False, "reason": reason}


# ---------------------------------------------------------------------------
# File-backed sources.
# ---------------------------------------------------------------------------


def _read_bytes(source: str, path: Path) -> bytes:
    try:
        return Path(path).read_bytes()
    except OSError as exc:
        raise EvidenceAssemblyError(source, f"cannot read {path}: {exc}") from exc


def _file_tag(source: str, path: Path, payload: bytes) -> dict[str, Any]:
    """Provenance for a file-backed source, pinned to the bytes actually read.

    The digest is taken from the same bytes that were parsed, so the document
    cannot end up describing a different file than the one it cites.
    """
    return {
        "kind": SOURCE_KINDS[source],
        "path": str(path),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "observedBy": "runner",
    }


def _parse_xml(source: str, payload: bytes) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise EvidenceAssemblyError(source, f"is not parseable XML: {exc}") from exc


def _int_attr(source: str, element: ElementTree.Element, name: str, default: int | None = 0) -> int:
    raw = element.get(name)
    if raw is None:
        if default is None:
            raise EvidenceAssemblyError(
                source, f"element <{element.tag}> has no {name!r} attribute"
            )
        return default
    try:
        return int(float(raw))
    except ValueError as exc:
        raise EvidenceAssemblyError(source, f"{name}={raw!r} is not a number") from exc


def _float_attr(source: str, element: ElementTree.Element, name: str) -> float | None:
    raw = element.get(name)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise EvidenceAssemblyError(source, f"{name}={raw!r} is not a number") from exc


def load_junit(path: Path) -> dict[str, Any]:
    """Per-suite and per-case results as pytest wrote them in the runner."""
    source = "junit"
    payload = _read_bytes(source, path)
    root = _parse_xml(source, payload)

    if root.tag == "testsuites":
        suites = list(root.findall("testsuite"))
    elif root.tag == "testsuite":
        suites = [root]
    else:
        raise EvidenceAssemblyError(
            source,
            f"root element is <{root.tag}>, expected <testsuites> or <testsuite>; "
            "this is not a junit report",
        )
    if not suites:
        raise EvidenceAssemblyError(source, "contains no <testsuite>; no run was recorded")

    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    seconds: float | None = 0.0
    cases: list[dict[str, Any]] = []
    for suite in suites:
        totals["tests"] += _int_attr(source, suite, "tests", default=None)
        totals["failures"] += _int_attr(source, suite, "failures")
        totals["errors"] += _int_attr(source, suite, "errors")
        totals["skipped"] += _int_attr(source, suite, "skipped")
        suite_seconds = _float_attr(source, suite, "time")
        if suite_seconds is None:
            # A suite with no time= contributes no timing. Summing it as 0.0
            # would turn "not measured" into "measured as zero" - the exact
            # defect this module exists to end (#1434 lock 2). The total is
            # discarded instead, so testSuiteDurationMs reports unavailable.
            seconds = None
        elif seconds is not None:
            seconds += suite_seconds
        for case in suite.findall("testcase"):
            cases.append(
                {
                    "classname": case.get("classname", ""),
                    "name": case.get("name", ""),
                    "seconds": _float_attr(source, case, "time"),
                    "outcome": _case_outcome(case),
                }
            )

    totals["passed"] = max(
        0, totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    )
    return {
        "source": _file_tag(source, path, payload),
        "totals": totals,
        "durationSeconds": seconds,
        "cases": cases,
    }


def _case_outcome(case: ElementTree.Element) -> str:
    for tag, outcome in (("failure", "failed"), ("error", "errored"), ("skipped", "skipped")):
        if case.find(tag) is not None:
            return outcome
    return "passed"


def load_coverage(path: Path) -> dict[str, Any]:
    """Line and branch coverage as coverage.py wrote it in the runner."""
    source = "coverage"
    payload = _read_bytes(source, path)
    root = _parse_xml(source, payload)
    if root.tag != "coverage":
        raise EvidenceAssemblyError(
            source,
            f"root element is <{root.tag}>, expected <coverage>; this is not a coverage report",
        )
    line_rate = _float_attr(source, root, "line-rate")
    if line_rate is None:
        raise EvidenceAssemblyError(source, "<coverage> has no line-rate attribute")
    return {
        "source": _file_tag(source, path, payload),
        "lineRate": line_rate,
        "linesCovered": _int_attr(source, root, "lines-covered", default=None),
        "linesValid": _int_attr(source, root, "lines-valid", default=None),
        "branchRate": _float_attr(source, root, "branch-rate"),
        "toolVersion": root.get("version"),
    }


def _load_json(source: str, path: Path) -> tuple[Any, bytes]:
    payload = _read_bytes(source, path)
    try:
        return json.loads(payload.decode("utf-8")), payload
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceAssemblyError(source, f"is not parseable JSON: {exc}") from exc


def load_gate_results(path: Path) -> dict[str, Any]:
    """Per-gate verdicts with the exit code the runner actually saw.

    A verdict without an exit code is prose, and prose is what this epic
    replaces — so it fails closed rather than being recorded as a result.
    """
    source = "gateResults"
    body, payload = _load_json(source, path)
    if isinstance(body, list):
        entries = body
    elif isinstance(body, dict) and isinstance(body.get("gates"), list):
        entries = body["gates"]
    else:
        raise EvidenceAssemblyError(
            source, "expected a list of gate results or an object with a 'gates' list"
        )
    if not entries:
        raise EvidenceAssemblyError(source, "records no gate results; no gate was run")

    gates: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise EvidenceAssemblyError(source, f"gate #{index} is not an object")
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise EvidenceAssemblyError(source, f"gate #{index} has no name")
        exit_code = entry.get("exitCode")
        if not isinstance(exit_code, int) or isinstance(exit_code, bool):
            raise EvidenceAssemblyError(
                source,
                f"gate {name!r} has no integer exitCode; a verdict with no exit code "
                "is prose, not an observation",
            )
        result = entry.get("result")
        if not isinstance(result, str) or not result.strip():
            # pr.yml's own note: Python exits 1 for both a reported FAIL and an
            # uncaught exception, so the verdict line — not the exit code — is
            # what separates "the gate answered" from "the gate could not". A
            # null verdict beside exitCode 0 is the latter wearing the former's
            # clothes, and is how a harvester that mis-parses gate output turns
            # four unanswered gates into four passes.
            raise EvidenceAssemblyError(
                source,
                f"gate {name!r} reports no verdict; an exit code without a verdict "
                "records that the gate ran, not that it answered",
            )
        gates.append(
            {
                "name": name,
                "result": result,
                "exitCode": exit_code,
                "durationMs": entry.get("durationMs"),
                "mode": entry.get("mode"),
                "diagnostic": entry.get("diagnostic"),
            }
        )

    return {
        "source": _file_tag(source, path, payload),
        "gates": gates,
        "totals": {
            "gates": len(gates),
            "nonZeroExit": sum(1 for gate in gates if gate["exitCode"] != 0),
        },
    }


def load_trace(path: Path) -> dict[str, Any]:
    """The commands the runner invoked, with the exit codes and durations it timed.

    JSONL, one observation per line. Every event must carry an integer
    ``exitCode`` and an integer ``durationMs``: an event lacking either is a
    narration of a command rather than a record of running one.
    """
    source = "trace"
    payload = _read_bytes(source, path)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvidenceAssemblyError(source, f"is not valid UTF-8: {exc}") from exc

    events: list[dict[str, Any]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvidenceAssemblyError(
                source, f"line {lineno} is not parseable JSON: {exc}"
            ) from exc
        if not isinstance(event, dict):
            raise EvidenceAssemblyError(source, f"line {lineno} is not an object")
        command = event.get("command")
        if not isinstance(command, (str, list)) or not command:
            raise EvidenceAssemblyError(source, f"line {lineno} names no command")
        for field in ("exitCode", "durationMs"):
            value = event.get(field)
            if not isinstance(value, int) or isinstance(value, bool):
                raise EvidenceAssemblyError(
                    source,
                    f"line {lineno} has no integer {field}; an event without one was "
                    "narrated, not observed",
                )
        events.append(
            {
                "command": command,
                "exitCode": event["exitCode"],
                "durationMs": event["durationMs"],
                "startedAt": event.get("startedAt"),
            }
        )

    if not events:
        raise EvidenceAssemblyError(
            source, "contains no events; zero observed commands is not a run"
        )

    return {
        "source": _file_tag(source, path, payload),
        "events": events,
        "totals": {
            "commands": len(events),
            "nonZeroExit": sum(1 for event in events if event["exitCode"] != 0),
            "durationMs": sum(event["durationMs"] for event in events),
        },
    }


# ---------------------------------------------------------------------------
# The environment fingerprint — imported from its owner, never reimplemented.
# ---------------------------------------------------------------------------


def default_fingerprint() -> dict[str, Any]:
    """Call ``capture_providers.environment.fingerprint()`` (#1442).

    Loaded by path rather than by package import because
    ``agent-runtime/scripts/ci`` is only on ``sys.path`` when a caller put it
    there, and because a stale ``capture_providers`` package elsewhere on the
    path must not be able to answer for this one.
    """
    module_path = Path(__file__).resolve().parent / "capture_providers" / "environment.py"
    if not module_path.exists():
        raise ModuleNotFoundError(f"{_ENVIRONMENT_PROVIDER} is not present at {module_path}")
    spec = importlib.util.spec_from_file_location("_juli_evidence_environment", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"{module_path} is not an importable Python module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fingerprint = getattr(module, "fingerprint", None)
    if not callable(fingerprint):
        raise AttributeError(f"{module_path} defines no callable fingerprint()")
    return fingerprint()


def load_environment(fingerprint: Callable[[], dict[str, Any]] | None = None) -> dict[str, Any]:
    """The environment fingerprint, treated as a source like any other."""
    source = "environment"
    provider = fingerprint or default_fingerprint
    try:
        value = provider()
    # Broad on purpose: the provider is third-party to this module and any
    # failure of it must fail the 'environment' source by name. Re-raised,
    # named, never swallowed. No suppression needed - ruff.toml selects
    # E4/E7/E9/F, so BLE001 is not an enforced rule here and a suppression
    # comment for it would be a tracked ratchet identity paying for nothing.
    except Exception as exc:
        raise EvidenceAssemblyError(source, exc) from exc
    if not isinstance(value, dict):
        raise EvidenceAssemblyError(
            source, f"fingerprint() returned {type(value).__name__}, expected a JSON object"
        )
    if not value:
        raise EvidenceAssemblyError(source, "fingerprint() returned an empty object")
    return {
        "source": {
            "kind": SOURCE_KINDS[source],
            "provider": _ENVIRONMENT_PROVIDER,
            "observedBy": "runner",
        },
        "fingerprint": value,
    }


# ---------------------------------------------------------------------------
# The runner's own view of the checkout.
# ---------------------------------------------------------------------------


def _git(repo_root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def observe_runner(repo_root: Path) -> dict[str, Any]:
    """``git rev-parse`` read in the runner, plus whether the checkout is shallow.

    CI checks out shallow, so shallowness is *recorded* rather than assumed
    either way, and a directory that is no checkout at all reports the commit
    unavailable rather than as an empty string.
    """
    head = _git(repo_root, "rev-parse", "HEAD")
    shallow = _git(repo_root, "rev-parse", "--is-shallow-repository")
    return {
        "repoRoot": str(repo_root),
        "commit": (
            observed(head, "git rev-parse HEAD")
            if head
            else unavailable("git rev-parse HEAD did not resolve in this working directory")
        ),
        "shallow": shallow == "true",
        "observedBy": "runner",
    }


# ---------------------------------------------------------------------------
# Claims: recorded as disagreements, never as facts.
# ---------------------------------------------------------------------------


def _claimed(claims: dict[str, Any], field: str) -> Any:
    """Look ``field`` up at the artifact's top level, then inside ``metrics``."""
    if field in claims:
        return claims[field]
    metrics = claims.get("metrics")
    if isinstance(metrics, dict) and field in metrics:
        return metrics[field]
    return _MISSING


_MISSING = object()


def _disagreements(
    claims: dict[str, Any] | None,
    junit: dict[str, Any],
    metrics: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compare each agent-authored claim against what was observed.

    The observed value is already what the document records; this only preserves
    the claim beside it. An agreeing claim produces no entry, so a non-empty
    list always means something.
    """
    if not claims:
        return []

    totals = junit["totals"]
    comparisons: list[tuple[str, Any, str]] = [
        ("testsRun", totals["tests"], "junit"),
        ("testsFailed", totals["failures"] + totals["errors"], "junit"),
        ("testsPassed", totals["passed"], "junit"),
    ]

    entries: list[dict[str, Any]] = []
    for field, observed_value, origin in comparisons:
        claimed = _claimed(claims, field)
        if claimed is _MISSING or claimed == observed_value:
            continue
        entries.append(
            {
                "field": field,
                "claimed": claimed,
                "observed": observed_value,
                "observedFrom": origin,
                "resolution": "observed",
            }
        )

    for field, metric in metrics.items():
        claimed = _claimed(claims, field)
        if claimed is _MISSING:
            continue
        if metric["available"]:
            if claimed == metric["value"]:
                continue
            entries.append(
                {
                    "field": field,
                    "claimed": claimed,
                    "observed": metric["value"],
                    "observedFrom": metric["observedFrom"],
                    "resolution": "observed",
                }
            )
        else:
            # Any claim for an unobservable field is a disagreement, including a
            # claimed zero — zero is exactly as unsourceable as 1,800,000 and is
            # the more convincing of the two.
            entries.append(
                {
                    "field": field,
                    "claimed": claimed,
                    "observed": None,
                    "observedFrom": "unavailable",
                    "reason": metric["reason"],
                    "resolution": "unobservable",
                }
            )

    return entries


# ---------------------------------------------------------------------------
# Assembly and verification.
# ---------------------------------------------------------------------------


def verify_evidence_document(document: dict[str, Any]) -> None:
    """Raise unless every required source is present and correctly tagged.

    Run by :func:`assemble_evidence` on its own output before returning, so the
    assembler cannot emit a document it would itself reject.
    """
    sources = document.get("sources")
    if not isinstance(sources, dict):
        raise EvidenceAssemblyError("document", "has no 'sources' object")

    for name in REQUIRED_SOURCES:
        section = sources.get(name)
        if not isinstance(section, dict):
            raise EvidenceAssemblyError(name, "section is absent from the assembled document")
        tag = section.get("source")
        if not isinstance(tag, dict):
            raise EvidenceAssemblyError(name, "section carries no 'source' provenance tag")
        if tag.get("kind") != SOURCE_KINDS[name]:
            raise EvidenceAssemblyError(
                name,
                f"is tagged kind={tag.get('kind')!r}, expected {SOURCE_KINDS[name]!r}; "
                "a section tagged as another source cannot be trusted as either",
            )
        if tag.get("observedBy") != "runner":
            raise EvidenceAssemblyError(
                name,
                f"is tagged observedBy={tag.get('observedBy')!r}; this document records "
                "runner observations only, never a value an agent supplied",
            )

    unexpected = set(sources) - set(REQUIRED_SOURCES)
    if unexpected:
        raise EvidenceAssemblyError("document", f"carries unknown sources {sorted(unexpected)}")

    for name, metric in document.get("metrics", {}).items():
        if not isinstance(metric, dict) or not isinstance(metric.get("available"), bool):
            raise EvidenceAssemblyError(name, "metric does not declare availability")
        if metric["available"] is False and "value" in metric:
            raise EvidenceAssemblyError(
                name, "metric is unavailable yet carries a value; unavailable is never a number"
            )


def assemble_evidence(
    *,
    issue: int | None,
    junit_xml: Path | str,
    coverage_xml: Path | str,
    gate_results: Path | str,
    trace: Path | str,
    claims: dict[str, Any] | None = None,
    repo_root: Path | str | None = None,
    fingerprint: Callable[[], dict[str, Any]] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Merge the five sources into one document. Fails closed on any of them."""
    root = Path(repo_root) if repo_root is not None else Path.cwd()

    sources = {
        "junit": load_junit(Path(junit_xml)),
        "coverage": load_coverage(Path(coverage_xml)),
        "gateResults": load_gate_results(Path(gate_results)),
        "environment": load_environment(fingerprint),
        "trace": load_trace(Path(trace)),
    }

    metrics = {
        # Observable: the trace carries per-command durations the runner timed.
        "executionDurationMs": observed(
            sources["trace"]["totals"]["durationMs"], "trace.sumOfCommandDurations"
        ),
        # Also observable, and independently: pytest's own suite timing.
        "testSuiteDurationMs": (
            observed(round(sources["junit"]["durationSeconds"] * 1000), "junit.suiteTime")
            if sources["junit"]["durationSeconds"] is not None
            else unavailable(
                "the junit report carries no suite time= attribute; recorded unavailable "
                "rather than 0 so an untimed suite cannot read as an instant one"
            )
        ),
        # Not observable anywhere in this pipeline. Recorded as such, not as 0.
        "tokenUsage": unavailable(TOKEN_USAGE_UNAVAILABLE),
    }

    document = {
        "schemaVersion": EVIDENCE_SCHEMA_VERSION,
        "generatedAt": generated_at
        or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "issue": issue,
        "runner": observe_runner(root),
        "sources": {name: sources[name] for name in REQUIRED_SOURCES},
        "metrics": metrics,
        "disagreements": _disagreements(claims, sources["junit"], metrics),
    }

    verify_evidence_document(document)
    return document


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--issue", type=int, default=None)
    parser.add_argument("--junit", required=True, type=Path, help="junit XML from the runner")
    parser.add_argument("--coverage", required=True, type=Path, help="coverage XML from the runner")
    parser.add_argument("--gate-results", required=True, type=Path, help="per-gate results JSON")
    parser.add_argument("--trace", required=True, type=Path, help="execution trace JSONL")
    parser.add_argument(
        "--claims",
        type=Path,
        default=None,
        help="agent-authored artifact whose claims are compared against observation",
    )
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=Path("evidence.json"))
    return parser


def main(
    argv: list[str] | None = None,
    *,
    fingerprint: Callable[[], dict[str, Any]] | None = None,
) -> int:
    args = _build_parser().parse_args(argv)

    claims: dict[str, Any] | None = None
    if args.claims is not None:
        try:
            claims = json.loads(args.claims.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"assemble_evidence: cannot read claims {args.claims}: {exc}", file=sys.stderr)
            return 1
        if not isinstance(claims, dict):
            print(f"assemble_evidence: claims {args.claims} is not a JSON object", file=sys.stderr)
            return 1

    try:
        document = assemble_evidence(
            issue=args.issue,
            junit_xml=args.junit,
            coverage_xml=args.coverage,
            gate_results=args.gate_results,
            trace=args.trace,
            claims=claims,
            repo_root=args.repo_root,
            fingerprint=fingerprint,
        )
    except EvidenceAssemblyError as exc:
        # Nothing is written: a half-document is worse than none, because the
        # missing half would be indistinguishable from a source that had nothing
        # to report.
        print(f"assemble_evidence: FAIL - {exc}", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"assemble_evidence: PASS - {args.out} ({len(REQUIRED_SOURCES)} sources)")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
