"""The `module_md_sync` gate must actually read the tree (#1859).

Before this slice `parse_architecture_map()` returned zero modules against the
real `docs/architecture/map.md`, so `touched` in
`check_module_drift.py::run_check` was always empty and the gate passed
vacuously for every PR. These tests are written against the REAL map and the
REAL `services/operations/MODULE.md` wherever the tree already contains the
case, and against a synthetic repo only for the cases it does not (deliberate
drift, a second `###` Public Interface section).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATE_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "validate"
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"


def _load(name: str):
    """Import a harness script by name, the way tests/unit already does.

    Kept a call rather than a top-of-file import so the sys.path insertion the
    harness scripts require does not need an E402 suppression.
    """
    for path in (VALIDATE_DIR, CI_DIR):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    return __import__(name)


common = _load("common")
check_module_drift = _load("check_module_drift")

OPERATIONS = "backend/services/operations"
OPERATIONS_MD = (
    REPO_ROOT / "backend" / "src" / "juli_backend" / "services" / "operations" / "MODULE.md"
)

# The real map lists well over this many backend modules today. The floor is a
# floor, not an equality, so adding a row never breaks it — but a regression to
# the zero-module vacuum cannot pass.
NON_VACUOUS_MODULE_FLOOR = 20


class TestParsesTheRealArchitectureMap:
    def test_the_scan_is_not_vacuous(self) -> None:
        """Anti-vacuum guard: zero modules is the defect, not an answer."""
        modules = common.parse_architecture_map()

        assert len(modules) >= NON_VACUOUS_MODULE_FLOOR, (
            "parse_architecture_map resolved "
            f"{len(modules)} modules from the real map.md; the gate is vacuous again"
        )

    def test_link_form_rows_resolve(self) -> None:
        modules = common.parse_architecture_map()

        assert OPERATIONS in modules
        assert "backend/services/scoring" in modules
        assert "backend/ai/dataset" in modules

    def test_tier_is_read_from_the_row(self) -> None:
        modules = common.parse_architecture_map()

        assert modules[OPERATIONS].tier == 2
        assert modules["backend/api"].tier == 1

    def test_module_for_file_resolves_end_to_end_on_the_real_map(self) -> None:
        """The paired defect: the map keys and `module_for_file` must agree."""
        modules = common.parse_architecture_map()

        resolved = common.module_for_file(
            "backend/src/juli_backend/services/operations/outcome_tracking.py", modules
        )

        assert resolved == OPERATIONS

    def test_module_root_of_a_parsed_key_exists_on_disk(self) -> None:
        modules = common.parse_architecture_map()

        for module_path in modules:
            assert common.backend_module_root(module_path).is_dir(), (
                f"map.md row {module_path} does not resolve to a directory"
            )

    def test_code_symbols_resolve_for_a_parsed_key(self) -> None:
        symbols = common.module_public_symbols_from_code(OPERATIONS)

        assert "load_outcome_chain" in symbols


class TestPublicInterfaceParsing:
    def test_every_public_interface_section_is_read(self, tmp_path: Path) -> None:
        module_md = tmp_path / "MODULE.md"
        module_md.write_text(
            "# Module: fixture\n\n"
            "## Public Interface\n\n"
            "- `alpha`\n\n"
            "## Dependencies\n\n"
            "- `not_a_symbol`\n\n"
            "---\n\n"
            "## Later section\n\n"
            "### Public interface\n\n"
            "- `beta`\n",
            encoding="utf-8",
        )

        symbols = common.parse_module_md_public_symbols(module_md)

        assert symbols == {"alpha", "beta"}

    def test_call_signature_entries_are_recognised(self, tmp_path: Path) -> None:
        module_md = tmp_path / "MODULE.md"
        module_md.write_text(
            "## Public Interface\n\n"
            "- `bare_identifier`\n"
            "- `with_call(session, shop_id) -> Result`\n"
            "- `no_args() -> None`\n"
            "- `union_return(x) -> A | B`\n",
            encoding="utf-8",
        )

        symbols = common.parse_module_md_public_symbols(module_md)

        assert symbols == {"bare_identifier", "with_call", "no_args", "union_return"}

    def test_dotted_spans_are_still_not_symbols(self, tmp_path: Path) -> None:
        module_md = tmp_path / "MODULE.md"
        module_md.write_text(
            "## Public Interface\n\n- `alpha`\n- `pkg.module.thing`\n",
            encoding="utf-8",
        )

        symbols = common.parse_module_md_public_symbols(module_md)

        assert symbols == {"alpha"}

    def test_backticked_prose_in_parentheses_is_not_a_documented_symbol(self) -> None:
        """The three real false positives measured on the live MODULE.md."""
        symbols = common.parse_module_md_public_symbols(OPERATIONS_MD)

        assert {"pending", "unavailable", "missing"}.isdisjoint(symbols)
        assert {"LinkReason", "EmptyLink", "OutcomeChain"} <= symbols

    def test_widening_did_not_lose_the_call_signature_entries_in_the_tree(self) -> None:
        symbols = common.parse_module_md_public_symbols(OPERATIONS_MD)

        assert "record_workflow_outcome" in symbols
        assert "load_outcome_chain" in symbols
        assert "recommendation_quality" in symbols

    def test_prose_after_the_em_dash_does_not_declare_a_symbol(self, tmp_path: Path) -> None:
        """A bullet declares before the dash and explains after it.

        Counting the explanation made database table names and result
        attributes into "documented symbols", which the gate then reported as
        documented-but-nonexistent. Three of the thirteen orphans it claimed
        for services/operations were exactly this.
        """
        module_md = tmp_path / "MODULE.md"
        module_md.write_text(
            "## Public Interface\n\n"
            "- `record_outcome(session, execution) -> Result` —\n"
            "  persist the `workflow_outcome_metrics` envelope\n"
            "- `NoData` — the value returned by every result's `ratio`\n",
            encoding="utf-8",
        )

        symbols = common.parse_module_md_public_symbols(module_md)

        assert symbols == {"record_outcome", "NoData"}
        assert "workflow_outcome_metrics" not in symbols
        assert "ratio" not in symbols

    def test_a_label_before_the_dash_leaves_the_declaration_in_the_tail(
        self, tmp_path: Path
    ) -> None:
        """The mirror-image convention, used by four Tier 1/2 modules.

        Splitting on the dash unconditionally kept the bold label and threw the
        symbols away. It hid 96 genuinely documented, genuinely exported names
        across integrations/tiktok, services/tiktok, ai/recommendations and
        services/agent, which then landed in the drift allowlist as
        "undocumented" -- the gate manufacturing its own findings again.
        """
        module_md = tmp_path / "MODULE.md"
        module_md.write_text(
            "## Public Interface\n\n"
            "- **HTTP client** — `TikTokClient`, `TikTokAuth`\n"
            "- **Rate limiting** — `RateLimiter`\n",
            encoding="utf-8",
        )

        symbols = common.parse_module_md_public_symbols(module_md)

        assert symbols == {"TikTokClient", "TikTokAuth", "RateLimiter"}

    def test_the_real_tiktok_module_still_documents_its_client(self) -> None:
        """Measured against the tree, not a fixture."""
        module_md = common.REPO_ROOT / "backend/src/juli_backend/integrations/tiktok/MODULE.md"

        symbols = common.parse_module_md_public_symbols(module_md)

        assert {"TikTokClient", "TikTokAuth", "RateLimiter"} <= symbols

    def test_an_import_fence_declares_its_names(self, tmp_path: Path) -> None:
        """The third convention: state the interface as the caller's import."""
        module_md = tmp_path / "MODULE.md"
        module_md.write_text(
            "## Public Interface\n\n"
            "```python\n"
            "from juli_backend.services.agent.sanitize import (\n"
            "    PER_RESULT_TOKEN_CEILING,\n"
            "    # a comment between entries\n"
            "    BannedPatternGuardFailure,\n"
            "    estimate_tokens,\n"
            ")\n"
            "```\n",
            encoding="utf-8",
        )

        symbols = common.parse_module_md_public_symbols(module_md)

        assert symbols == {
            "PER_RESULT_TOKEN_CEILING",
            "BannedPatternGuardFailure",
            "estimate_tokens",
        }

    def test_an_unparseable_fence_declares_nothing(self, tmp_path: Path) -> None:
        """An elided import list is not a licence to guess."""
        module_md = tmp_path / "MODULE.md"
        module_md.write_text(
            "## Public Interface\n\n"
            "```python\n"
            "from juli_backend.integrations.tiktok import TikTokAuth, ...\n"
            "```\n"
            "- `RateLimiter`\n",
            encoding="utf-8",
        )

        symbols = common.parse_module_md_public_symbols(module_md)

        assert symbols == {"RateLimiter"}

    def test_the_real_agent_module_declares_its_fenced_names(self) -> None:
        module_md = common.REPO_ROOT / "backend/src/juli_backend/services/agent/MODULE.md"

        symbols = common.parse_module_md_public_symbols(module_md)

        assert {
            "PER_RESULT_TOKEN_CEILING",
            "RETRYABLE_VENDOR_CODES",
            "BannedPatternGuardFailure",
        } <= symbols

    def test_a_table_row_is_never_split_on_its_dash(self, tmp_path: Path) -> None:
        """A row carries no declare/explain boundary, so it is scanned whole."""
        module_md = tmp_path / "MODULE.md"
        module_md.write_text(
            "## Public Interface\n\n"
            "| name | what |\n"
            "| --- | --- |\n"
            "| `run_workflow` | starts a run — returns `RunHandle` |\n",
            encoding="utf-8",
        )

        symbols = common.parse_module_md_public_symbols(module_md)

        assert {"run_workflow", "RunHandle"} <= symbols

    def test_several_names_before_the_dash_all_declare(self, tmp_path: Path) -> None:
        module_md = tmp_path / "MODULE.md"
        module_md.write_text(
            "## Public Interface\n\n"
            "- `APPROVED_STATUSES` / `DISMISSED_STATUSES` /\n"
            "  `PENDING_STATUSES` — the seller-decision mapping, declared once\n",
            encoding="utf-8",
        )

        symbols = common.parse_module_md_public_symbols(module_md)

        assert symbols == {"APPROVED_STATUSES", "DISMISSED_STATUSES", "PENDING_STATUSES"}


class TestCodeSideSymbolExtraction:
    """`ast_public_symbols` has to see a module-level constant.

    It previously admitted a name only when the value was a call or a def, so
    `CARDS_SURFACED = "cards surfaced"` and `APPROVED_STATUSES: frozenset[str]
    = frozenset({...})` were both invisible and the gate called them orphans.
    """

    def _symbols(self, tmp_path: Path, source: str) -> set[str]:
        py = tmp_path / "impl.py"
        py.write_text(source, encoding="utf-8")
        return common.ast_public_symbols(py)

    def test_a_plain_string_constant_is_an_export(self, tmp_path: Path) -> None:
        assert "CARDS_SURFACED" in self._symbols(tmp_path, 'CARDS_SURFACED = "cards surfaced"\n')

    def test_an_annotated_constant_is_an_export(self, tmp_path: Path) -> None:
        symbols = self._symbols(
            tmp_path,
            "APPROVED_STATUSES: frozenset[str] = frozenset({'approved'})\n"
            "KIND_PRECEDENCE: tuple[str, ...] = ('a', 'b')\n",
        )

        assert {"APPROVED_STATUSES", "KIND_PRECEDENCE"} <= symbols

    def test_a_private_name_is_still_not_an_export(self, tmp_path: Path) -> None:
        symbols = self._symbols(tmp_path, "_HIDDEN = 1\n_ANNOTATED: int = 2\nVISIBLE = 3\n")

        assert symbols == {"VISIBLE"}

    def test_a_conventional_logger_binding_is_not_an_export(self, tmp_path: Path) -> None:
        """Documenting a module logger would be noise, not information."""
        symbols = self._symbols(
            tmp_path,
            "import logging\nlogger = logging.getLogger(__name__)\nREAL = 1\n",
        )

        assert symbols == {"REAL"}

    def test_a_local_assignment_inside_a_function_is_not_an_export(self, tmp_path: Path) -> None:
        symbols = self._symbols(tmp_path, "def fn() -> int:\n    INNER = 1\n    return INNER\n")

        assert symbols == {"fn"}


class TestOperationsIsTheWorkedExample:
    """#1859 AC5: services/operations reaches zero drift, not an allowlist entry."""

    def test_operations_has_no_drift_in_either_direction(self) -> None:
        documented, actual = check_module_drift.module_symbols(OPERATIONS)

        assert sorted(documented - actual) == [], "MODULE.md names symbols that do not exist"
        assert sorted(actual - documented) == [], "module exports symbols MODULE.md omits"

    def test_operations_is_absent_from_the_allowlist(self) -> None:
        assert OPERATIONS not in check_module_drift.KNOWN_DRIFT_ALLOWLIST


def _write_synthetic_repo(
    root: Path,
    *,
    documented: str,
    code: str,
    tier: int = 2,
) -> None:
    """A miniature repo whose map.md row uses the real markdown-link form."""
    map_md = root / "docs" / "architecture" / "map.md"
    map_md.parent.mkdir(parents=True, exist_ok=True)
    map_md.write_text(
        "| Module | Tier | Purpose | Public interface | Area |\n"
        "|---|---|---|---|---|\n"
        "| [`backend/src/juli_backend/services/fixture`]"
        "(../../backend/src/juli_backend/services/fixture/MODULE.md) "
        f"| {tier} | fixture | `alpha` | Test |\n",
        encoding="utf-8",
    )
    module_dir = root / "backend" / "src" / "juli_backend" / "services" / "fixture"
    module_dir.mkdir(parents=True, exist_ok=True)
    (module_dir / "MODULE.md").write_text(documented, encoding="utf-8")
    (module_dir / "impl.py").write_text(code, encoding="utf-8")


@pytest.fixture
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def _build(*, documented: str, code: str, tier: int = 2) -> Path:
        _write_synthetic_repo(tmp_path, documented=documented, code=code, tier=tier)
        monkeypatch.setattr(common, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(
            common, "ARCHITECTURE_MAP", tmp_path / "docs" / "architecture" / "map.md"
        )
        return tmp_path

    return _build


CHANGED = ["backend/src/juli_backend/services/fixture/impl.py"]
IN_SYNC_MD = "## Public Interface\n\n- `alpha(x) -> int`\n"
IN_SYNC_CODE = "def alpha(x: int) -> int:\n    return x\n"


def _patch_changed(monkeypatch: pytest.MonkeyPatch, changed: list[str]) -> None:
    monkeypatch.setattr(check_module_drift, "git_changed_files", lambda: list(changed))


class TestTheGateIsNotVacuous:
    def test_touched_modules_are_reported(
        self, synthetic_repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        synthetic_repo(documented=IN_SYNC_MD, code=IN_SYNC_CODE)
        _patch_changed(monkeypatch, CHANGED)

        passed, _, details = check_module_drift.run_check(1859)

        assert details["touchedModules"] == ["backend/services/fixture"]
        assert passed is True

    def test_undocumented_symbol_fails_the_gate_by_name(
        self, synthetic_repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        synthetic_repo(
            documented=IN_SYNC_MD,
            code=IN_SYNC_CODE + "\n\ndef beta() -> None:\n    return None\n",
        )
        _patch_changed(monkeypatch, CHANGED)

        passed, message, details = check_module_drift.run_check(1859)

        assert passed is False
        assert "drift" in message.lower()
        assert details["drift"][0]["module"] == "backend/services/fixture"
        assert details["drift"][0]["missingInModuleMd"] == ["beta"]

    def test_orphan_symbol_fails_the_gate_by_name(
        self, synthetic_repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        synthetic_repo(
            documented=IN_SYNC_MD + "- `gone_from_code`\n",
            code=IN_SYNC_CODE,
        )
        _patch_changed(monkeypatch, CHANGED)

        passed, _, details = check_module_drift.run_check(1859)

        assert passed is False
        assert details["drift"][0]["orphanInModuleMd"] == ["gone_from_code"]

    def test_changed_files_unresolved_still_fails_closed(
        self, synthetic_repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        synthetic_repo(documented=IN_SYNC_MD, code=IN_SYNC_CODE)

        def _raise() -> list[str]:
            raise common.ChangedFilesUnresolved("origin/main", "no merge base")

        monkeypatch.setattr(check_module_drift, "git_changed_files", _raise)

        passed, message, details = check_module_drift.run_check(1859)

        assert passed is False
        assert details["changedFilesUnresolved"] == "no merge base"
        assert "unresolved" in message.lower()


class TestTheAllowlist:
    def test_allowlisted_symbol_does_not_fail_the_gate(
        self, synthetic_repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        synthetic_repo(
            documented=IN_SYNC_MD,
            code=IN_SYNC_CODE + "\n\ndef beta() -> None:\n    return None\n",
        )
        _patch_changed(monkeypatch, CHANGED)
        monkeypatch.setattr(
            check_module_drift,
            "KNOWN_DRIFT_ALLOWLIST",
            {
                "backend/services/fixture": {
                    "undocumented": check_module_drift.AllowedDrift(
                        reason="pre-existing fixture drift, named on purpose",
                        symbols=("beta",),
                    ),
                }
            },
        )

        passed, _, details = check_module_drift.run_check(1859)

        assert passed is True
        assert details["allowlisted"] == ["backend/services/fixture:undocumented:beta"]

    def test_allowlist_does_not_swallow_new_drift(
        self, synthetic_repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        synthetic_repo(
            documented=IN_SYNC_MD,
            code=(
                IN_SYNC_CODE
                + "\n\ndef beta() -> None:\n    return None\n"
                + "\n\ndef gamma() -> None:\n    return None\n"
            ),
        )
        _patch_changed(monkeypatch, CHANGED)
        monkeypatch.setattr(
            check_module_drift,
            "KNOWN_DRIFT_ALLOWLIST",
            {
                "backend/services/fixture": {
                    "undocumented": check_module_drift.AllowedDrift(
                        reason="pre-existing fixture drift, named on purpose",
                        symbols=("beta",),
                    ),
                }
            },
        )

        passed, _, details = check_module_drift.run_check(1859)

        assert passed is False
        assert details["drift"][0]["missingInModuleMd"] == ["gamma"]
        assert details["allowlisted"] == ["backend/services/fixture:undocumented:beta"]

    def test_every_entry_is_explicit_and_carries_a_reason(self) -> None:
        for module_path, kinds in check_module_drift.KNOWN_DRIFT_ALLOWLIST.items():
            assert "*" not in module_path
            assert set(kinds) <= {"undocumented", "orphan"}
            for kind, entry in kinds.items():
                assert entry.symbols, f"{module_path}:{kind} is an empty (wildcard-shaped) entry"
                assert len(entry.reason) >= 40, f"{module_path}:{kind} has no real reason"
                for symbol in entry.symbols:
                    assert "*" not in symbol
                    assert symbol.isidentifier(), f"{module_path}:{kind}:{symbol} is not a symbol"

    def test_every_entry_still_names_real_drift(self) -> None:
        """Anti-rot: the allowlist cannot outlive the drift it excuses."""
        modules = common.parse_architecture_map()
        stale: list[str] = []
        for module_path, kinds in check_module_drift.KNOWN_DRIFT_ALLOWLIST.items():
            assert module_path in modules, f"{module_path} is not a row in map.md"
            documented, actual = check_module_drift.module_symbols(module_path)
            live = {
                "undocumented": actual - documented,
                "orphan": documented - actual,
            }
            for kind, entry in kinds.items():
                for symbol in entry.symbols:
                    if symbol not in live[kind]:
                        stale.append(f"{module_path}:{kind}:{symbol}")

        assert not stale, f"allowlist entries no longer name real drift: {stale}"


class TestTheRealTreePassesWithTheAllowlist:
    def test_operations_is_green_once_allowlisted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_changed(
            monkeypatch, ["backend/src/juli_backend/services/operations/outcome_chain.py"]
        )

        passed, _, details = check_module_drift.run_check(1859)

        assert details["touchedModules"] == [OPERATIONS]
        assert passed is True, f"unallowlisted drift: {details['drift']}"


class TestTheAllowlistCannotHideADocumentedSymbol:
    """A parser that loses a declaration turns it into "undocumented" drift.

    That is how 96 real exports were quietly allowlisted. The check below is
    deliberately independent of the declare/explain rule the parser uses: it
    looks at the FIRST backticked identifier on each bullet, which is a
    declaration under either convention in this tree and is never a prose
    mention. So a future parser regression cannot launder its mistakes through
    the allowlist the way the last one did.
    """

    @staticmethod
    def _leading_symbols(module_md) -> set[str]:
        leading: set[str] = set()
        for body in common.public_interface_sections(module_md.read_text(encoding="utf-8")):
            for line in body.splitlines():
                if not re.match(r"^\s*[-*]\s", line):
                    continue
                match = common.BACKTICK_SYMBOL_RE.search(line)
                if match and match.group(1) not in common.NEVER_A_SYMBOL:
                    leading.add(match.group(1))
        return leading

    def test_no_allowlisted_undocumented_symbol_leads_a_bullet(self) -> None:
        laundered: list[str] = []
        for module_path, kinds in check_module_drift.KNOWN_DRIFT_ALLOWLIST.items():
            entry = kinds.get("undocumented")
            if entry is None:
                continue
            module_md = common.backend_module_root(module_path) / "MODULE.md"
            if not module_md.exists():
                continue
            leading = self._leading_symbols(module_md)
            laundered += [f"{module_path}:{sym}" for sym in entry.symbols if sym in leading]

        assert not laundered, (
            "these symbols are excused as undocumented, but their MODULE.md "
            "declares them at the head of a bullet -- the parser lost a "
            f"declaration: {sorted(laundered)}"
        )

    def test_the_check_reads_real_declarations_in_all_four_broken_modules(self) -> None:
        """Proof it is not vacuous: every module whose convention broke still
        yields leading-bullet declarations for this check to compare against."""
        for module_path, must_include in (
            ("backend/integrations/tiktok", {"TikTokClient", "TikTokAuth"}),
            ("backend/services/tiktok", set()),
            ("backend/ai/recommendations", set()),
            ("backend/services/agent", set()),
        ):
            leading = self._leading_symbols(common.backend_module_root(module_path) / "MODULE.md")
            assert leading, f"{module_path} yields no leading-bullet declarations"
            assert must_include <= leading, f"{module_path} lost {must_include - leading}"


class TestTheAllowlistIsADerivation:
    """The allowlist must equal what the tree measures, in BOTH directions.

    `test_every_entry_still_names_real_drift` walks allowlist -> tree, so it
    catches an entry that stopped being drift. Nothing walked tree ->
    allowlist, so drift that appeared AFTER the list was generated -- a module
    gaining an export on main while this branch was open -- silently escaped
    it and would fail the gate on the next PR to touch that module. One
    equality assertion closes the whole class.
    """

    @staticmethod
    def _derive() -> dict[str, dict[str, tuple[str, ...]]]:
        derived: dict[str, dict[str, tuple[str, ...]]] = {}
        for module_path in sorted(common.parse_architecture_map()):
            documented, actual = check_module_drift.module_symbols(module_path)
            kinds = {
                "orphan": tuple(sorted(documented - actual)),
                "undocumented": tuple(sorted(actual - documented)),
            }
            present = {kind: syms for kind, syms in kinds.items() if syms}
            if present:
                derived[module_path] = present
        return derived

    def test_the_committed_allowlist_equals_a_fresh_derivation(self) -> None:
        committed = {
            module_path: {kind: entry.symbols for kind, entry in kinds.items()}
            for module_path, kinds in check_module_drift.KNOWN_DRIFT_ALLOWLIST.items()
        }
        derived = self._derive()

        # Keyed by (module, kind): keying by module alone let a module with
        # both kinds overwrite its own orphan diff, losing the guidance the
        # message exists to give.
        missing = {
            f"{module_path}:{kind}": sorted(
                set(symbols) - set(committed.get(module_path, {}).get(kind, ()))
            )
            for module_path, kinds in derived.items()
            for kind, symbols in kinds.items()
        }
        missing = {where: syms for where, syms in missing.items() if syms}

        assert not missing, (
            "drift exists in the tree that the allowlist does not cover, so the "
            "next PR touching these modules fails a gate for something it did "
            f"not do -- regenerate the allowlist: {missing}"
        )
        assert committed == derived, (
            "the allowlist is not a faithful derivation of the tree; regenerate "
            "it rather than editing entries by hand"
        )
