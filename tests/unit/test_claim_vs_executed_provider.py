"""#1443 (HE-B/P-EVAL-9): a cited command with no invocation fails the record.

The mutant table in ``eval/results/gate_operator_scores.md`` scored all 29 gates
against seven planted-defect operators and found ``narrowed_command_scope`` and
``environment_mismatch`` caught by *no* gate. ``check_differential_tdd`` — the
only gate that shells out — re-runs the tests itself and never reads what the
artifact claimed it ran, so a fabricated ``redGreenRefactorEvidence.commands``
entry is invisible to the whole suite.

These tests plant that exact lie and assert it is caught. Every test names a
falsehood and requires the provider to reject it; there is no happy-path-only
case here, and the missing-transcript case is deliberately the one that must NOT
be allowed to report a comfortable ``0 unmatched``.
"""

from __future__ import annotations

import builtins
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
PROVIDER_DIR = CI_DIR / "capture_providers"


def _load_seam():
    """Import the capture seam, which lives outside any importable package root.

    Done inside a function deliberately: hoisting the ``sys.path`` insert above
    module-level imports needs three ``# noqa: E402`` suppressions, and the
    repo's debt ratchet (#1462) counts suppression identities. Paying tracked
    debt for import cosmetics is a bad trade.
    """
    if str(CI_DIR) not in sys.path:
        sys.path.insert(0, str(CI_DIR))
    import capture_providers
    from capture_providers import claim_vs_executed

    return capture_providers, claim_vs_executed


capture_providers, provider = _load_seam()

CaptureContext = capture_providers.CaptureContext

# ---------------------------------------------------------------------------
# fixtures / builders
# ---------------------------------------------------------------------------


def _context(issue: int = 1443) -> CaptureContext:
    """A CaptureContext carrying only what the seam actually supplies."""
    review = {"issue": issue, "status": "PASS"}
    validation = {"issue": issue, "status": "PASS", "readyForMerge": True}
    return CaptureContext(
        issue=issue,
        review=review,
        validation=validation,
        review_bytes=json.dumps(review).encode("utf-8"),
        validation_bytes=json.dumps(validation).encode("utf-8"),
    )


def _artifact(*commands: str, cycle: int = 1) -> dict[str, Any]:
    """An implementation artifact citing ``commands`` as run, all green."""
    return {
        "issueId": 1443,
        "redGreenRefactorEvidence": [
            {
                "cycle": cycle,
                "commands": [{"command": c, "exitCode": 0} for c in commands],
            }
        ],
    }


def _transcript(directory: Path, *commands: str, name: str = "session.jsonl") -> Path:
    """Write a JSONL transcript whose tool_use records invoke ``commands``.

    Shaped like a real ``~/.claude/projects/*/<uuid>.jsonl``: one JSON object per
    line, the Bash calls nested under ``message.content[].input.command``, mixed
    with the non-tool traffic a real transcript carries so the parser is exercised
    against noise rather than a clean fixture.
    """
    directory.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        json.dumps({"type": "user", "message": {"role": "user", "content": "go"}}),
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "thinking about it"}],
                },
            }
        ),
    ]
    for index, command in enumerate(commands):
        lines.append(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": f"toolu_{index}",
                                "name": "Bash",
                                "input": {"command": command, "description": "d"},
                            }
                        ],
                    },
                }
            )
        )
    path = directory / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# AC1 — a cited command with no invocation fails the record
# ---------------------------------------------------------------------------


def test_cited_command_never_invoked_fails_record(tmp_path: Path) -> None:
    """The planted lie: the artifact swears it ran a test file it never touched.

    The transcript shows ``test_real.py`` being run. The artifact cites
    ``test_fabricated.py``. Nothing in the 29-gate suite notices today.
    """
    transcripts = tmp_path / "projects" / "-repo"
    _transcript(
        transcripts,
        "PYTHONPATH=$PWD/backend/src python -m pytest tests/unit/test_real.py -q",
        "ruff check backend",
    )

    block = provider.capture(
        _context(),
        implementation_artifact=_artifact(
            "PYTHONPATH=$PWD/backend/src python -m pytest tests/unit/test_fabricated.py -q"
        ),
        transcript_dirs=[transcripts],
    )

    assert block["status"] == "FAIL", block
    assert block["recordPasses"] is False
    assert block["unmatchedCommandCount"] == 1
    assert block["citedCommandCount"] == 1
    assert block["matchedCommandCount"] == 0
    # The offender is named, not merely counted — a bare count cannot be acted on.
    unmatched = [entry["command"] for entry in block["unmatchedCommands"]]
    assert any("test_fabricated.py" in command for command in unmatched), block


def test_partially_fabricated_claim_names_only_the_unmatched_command(tmp_path: Path) -> None:
    """One true claim beside one false one must not launder the false one."""
    transcripts = tmp_path / "projects" / "-repo"
    _transcript(transcripts, "python -m pytest tests/unit/test_real.py -q")

    block = provider.capture(
        _context(),
        implementation_artifact=_artifact(
            "python -m pytest tests/unit/test_real.py -q",
            "python -m pytest tests/unit/test_never_ran.py -q",
        ),
        transcript_dirs=[transcripts],
    )

    assert block["status"] == "FAIL"
    assert block["citedCommandCount"] == 2
    assert block["matchedCommandCount"] == 1
    assert block["unmatchedCommandCount"] == 1
    unmatched = [entry["command"] for entry in block["unmatchedCommands"]]
    assert unmatched == ["python -m pytest tests/unit/test_never_ran.py -q"]


def test_narrowed_command_scope_is_caught(tmp_path: Path) -> None:
    """``narrowed_command_scope``: claim the full suite, run one file.

    This is one of the two operators the committed mutant table shows no gate
    catching. The invoked command is a strict *narrowing* of the cited one, so
    substring matching in the wrong direction would wave it through.
    """
    transcripts = tmp_path / "projects" / "-repo"
    _transcript(transcripts, "python -m pytest tests/unit/test_one_file.py -q")

    block = provider.capture(
        _context(),
        implementation_artifact=_artifact("python -m pytest"),
        transcript_dirs=[transcripts],
    )

    assert block["status"] == "FAIL", (
        "a claim of the whole suite backed only by a single-file run must not pass"
    )
    assert block["unmatchedCommandCount"] == 1


def test_prose_instead_of_a_command_is_unmatched(tmp_path: Path) -> None:
    """Prose in the commands array is evidence of nothing and must not match."""
    transcripts = tmp_path / "projects" / "-repo"
    _transcript(transcripts, "python -m pytest tests/unit/test_real.py -q")

    block = provider.capture(
        _context(),
        implementation_artifact=_artifact("ran the tests and they all passed"),
        transcript_dirs=[transcripts],
    )

    assert block["status"] == "FAIL"
    assert block["unmatchedCommandCount"] == 1


# ---------------------------------------------------------------------------
# AC2 — matching claims pass
# ---------------------------------------------------------------------------


def test_matching_claims_pass(tmp_path: Path) -> None:
    """Truthful claims pass — and the pass is earned against a populated corpus.

    The negative control matters as much as the positive: the same transcript
    also contains a command the artifact does *not* cite, so a provider that
    trivially returned PASS would still be wrong on the tests above.
    """
    transcripts = tmp_path / "projects" / "-repo"
    _transcript(
        transcripts,
        "PYTHONPATH=$PWD/backend/src python -m pytest tests/unit/test_real.py -q",
        "ruff check backend tests",
        "git log --oneline -1",
    )

    block = provider.capture(
        _context(),
        implementation_artifact=_artifact(
            "PYTHONPATH=$PWD/backend/src python -m pytest tests/unit/test_real.py -q",
            "ruff check backend tests",
        ),
        transcript_dirs=[transcripts],
    )

    assert block["status"] == "PASS", block
    assert block["recordPasses"] is True
    assert block["unmatchedCommandCount"] == 0
    assert block["citedCommandCount"] == 2
    assert block["matchedCommandCount"] == 2
    assert block["unmatchedCommands"] == []
    # A pass must be able to show what it looked at.
    assert block["transcriptsScanned"] == 1
    assert block["invokedCommandCount"] >= 3


def test_cd_prefix_and_whitespace_do_not_fabricate_a_mismatch(tmp_path: Path) -> None:
    """Normalisation is real, but it is normalisation — not a match-everything rule.

    The lie planted here is in the *second* assertion: a differently-pathed
    ``cd`` prefix must not let an entirely different pytest target through.
    """
    transcripts = tmp_path / "projects" / "-repo"
    _transcript(
        transcripts,
        "cd /Users/macos/Juli-AI-v2/.worktrees/w2-1443 && "
        "python  -m   pytest tests/unit/test_real.py -q",
    )

    honest = provider.capture(
        _context(),
        implementation_artifact=_artifact("python -m pytest tests/unit/test_real.py -q"),
        transcript_dirs=[transcripts],
    )
    assert honest["status"] == "PASS", honest

    lying = provider.capture(
        _context(),
        implementation_artifact=_artifact(
            "cd /somewhere/else && python -m pytest tests/unit/test_other.py -q"
        ),
        transcript_dirs=[transcripts],
    )
    assert lying["status"] == "FAIL", lying


def test_command_in_an_and_chain_counts_as_invoked(tmp_path: Path) -> None:
    """A cited command really run as one leg of an ``&&`` chain did happen."""
    transcripts = tmp_path / "projects" / "-repo"
    _transcript(transcripts, "ruff format --check backend && python -m pytest tests/unit -q")

    block = provider.capture(
        _context(),
        implementation_artifact=_artifact("python -m pytest tests/unit -q"),
        transcript_dirs=[transcripts],
    )

    assert block["status"] == "PASS", block
    assert block["unmatchedCommandCount"] == 0


# ---------------------------------------------------------------------------
# AC3 — a transcript that cannot be located fails closed
# ---------------------------------------------------------------------------


def test_missing_transcript_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CI has no ``~/.claude``. Reporting ``0 unmatched`` there is the vacuous pass.

    #1456 found 1176 of 2457 dataset rows provenanced to one machine-local
    transcript directory that is not backed up and does not exist in CI. The lie
    planted here is the provider's own: the artifact cites a command that was
    never run anywhere, and with no corpus to check against the provider must
    say so rather than certify it.
    """
    empty_home = tmp_path / "empty-home"
    empty_home.mkdir()
    monkeypatch.setenv("HOME", str(empty_home))
    monkeypatch.setenv("USERPROFILE", str(empty_home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv(provider.TRANSCRIPT_DIR_ENV, raising=False)

    block = provider.capture(
        _context(),
        implementation_artifact=_artifact("python -m pytest tests/unit/test_never_ran.py -q"),
    )

    assert block["status"] == provider.STATUS_MISSING_SOURCE, block
    assert block["recordPasses"] is False, "an unverifiable claim is not a passing claim"
    assert block["verified"] is False
    assert block["transcriptsScanned"] == 0
    assert block["invokedCommandCount"] == 0
    # The whole point: it must NOT be indistinguishable from a clean run.
    assert block["unmatchedCommandCount"] is None, (
        "reporting a number here would make 'could not look' read as 'looked and found nothing'"
    )
    assert block["status"] != "PASS"
    assert block["reason"]


def test_transcript_dir_present_but_empty_also_fails_closed(tmp_path: Path) -> None:
    """A directory with no transcripts is still no evidence."""
    empty = tmp_path / "projects" / "-repo"
    empty.mkdir(parents=True)

    block = provider.capture(
        _context(),
        implementation_artifact=_artifact("python -m pytest -q"),
        transcript_dirs=[empty],
    )

    assert block["status"] == provider.STATUS_MISSING_SOURCE, block
    assert block["recordPasses"] is False
    assert block["unmatchedCommandCount"] is None


def test_missing_implementation_artifact_fails_closed(tmp_path: Path) -> None:
    """No artifact on disk is not 'nothing was claimed' — it is 'nothing was checked'."""
    transcripts = tmp_path / "projects" / "-repo"
    _transcript(transcripts, "python -m pytest -q")

    block = provider.capture(
        _context(issue=999_1443),
        implementation_artifact=None,
        artifact_dir=tmp_path / "no-such-implementations",
        transcript_dirs=[transcripts],
    )

    assert block["status"] == provider.STATUS_MISSING_SOURCE, block
    assert block["recordPasses"] is False
    assert block["unmatchedCommandCount"] is None


def test_artifact_citing_no_commands_does_not_pass_vacuously(tmp_path: Path) -> None:
    """Zero cited commands is zero evidence, not a clean bill of health."""
    transcripts = tmp_path / "projects" / "-repo"
    _transcript(transcripts, "python -m pytest -q")

    block = provider.capture(
        _context(),
        implementation_artifact={"issueId": 1443, "redGreenRefactorEvidence": []},
        transcript_dirs=[transcripts],
    )

    assert block["status"] == provider.STATUS_NO_CLAIMS, block
    assert block["recordPasses"] is False
    assert block["citedCommandCount"] == 0


# ---------------------------------------------------------------------------
# seam contract + house rules
# ---------------------------------------------------------------------------


def test_provider_is_discovered_without_a_generator_edit(tmp_path: Path) -> None:
    """The block appears under run{} because the module exists, not because the
    writer was taught about it."""
    writer = CI_DIR / "generate_status_records.py"
    writer_before = writer.read_bytes()

    with capture_providers.provider_sandbox():
        discovered = capture_providers.discover_providers(PROVIDER_DIR)
        assert provider.PROVIDER_NAME in discovered, discovered
        assert provider.PROVIDER_NAME in capture_providers.registered_providers()

    assert b"claimVsExecuted" not in writer_before, (
        "generate_status_records.py must not name this provider"
    )
    assert writer.read_bytes() == writer_before


def test_registry_call_path_produces_a_json_object_block(tmp_path: Path) -> None:
    """``capture_run_block`` calls ``capture(context)`` with no keywords — the
    zero-argument default path must still return a serialisable object."""
    empty_home = tmp_path / "empty-home"
    empty_home.mkdir()

    with capture_providers.provider_sandbox():
        capture_providers.register_provider(provider.PROVIDER_NAME, provider.capture, replace=True)
        run = capture_providers.capture_run_block(_context())

    block = run[provider.PROVIDER_NAME]
    assert isinstance(block, dict)
    json.dumps(block)  # must survive serialisation into the record


def test_provider_imports_no_third_party_modules() -> None:
    """A peer imported ``jsonschema``, passed locally and failed CI collection.

    Re-import the module with every non-stdlib import raising, so a dependency
    added later cannot ride in unnoticed.
    """
    source = (PROVIDER_DIR / "claim_vs_executed.py").read_text(encoding="utf-8")
    real_import = builtins.__import__
    banned = {"jsonschema", "pytest", "yaml", "pydantic", "requests", "httpx", "fastapi"}

    def guarded(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.split(".")[0] in banned:
            raise AssertionError(f"provider must not import third-party module {name!r}")
        return real_import(name, *args, **kwargs)

    namespace: dict[str, Any] = {
        "__name__": "_claim_vs_executed_import_probe",
        "__builtins__": builtins,
    }
    builtins.__import__ = guarded
    try:
        exec(compile(source, "claim_vs_executed.py", "exec"), namespace)
    finally:
        builtins.__import__ = real_import

    assert namespace["PROVIDER_NAME"] == "claimVsExecuted"


def test_module_runs_under_a_bare_interpreter_with_no_repo_on_path() -> None:
    """Discovery imports the file by path with no package context. Import it the
    same way in a clean subprocess so a stray relative import cannot hide."""
    module_path = str(PROVIDER_DIR / "claim_vs_executed.py")
    code = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('probe', {module_path!r})\n"
        "m = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(m)\n"
        "assert m.PROVIDER_NAME == 'claimVsExecuted'\n"
        "assert callable(m.capture)\n"
        "print('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=str(tmp_root())
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def tmp_root() -> Path:
    """Run the subprocess from a directory that is not the repo root."""
    return Path(REPO_ROOT).parent
