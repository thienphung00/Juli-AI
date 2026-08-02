#!/usr/bin/env python3
"""Generate .claude/skills pointer skills from the authoritative .cursor/skills bodies.

Each pointer carries Claude-native frontmatter (name + description) so Claude Code can
discover and route the skill, then defers to the .cursor body. Re-runnable: rewrites
pointers in place. Bodies are never copied.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CURSOR = REPO / ".cursor" / "skills"
TARGET = REPO / ".claude" / "skills"

CATALOG_EXTRA = """\
The Cursor body is the authoritative index of marketplace plugins, MCP servers, and plugin
skills. **Claude Code deviates from it in one way: tooling is CLI-first.**

MCP tool schemas are always-on context cost for every agent on every request; a CLI costs
nothing until invoked, is reproducible from a workflow cache, and is gateable by a single
Bash hook. So in Claude Code, reach for MCP only where no CLI exists — and only during the
Architect/Meta phases.

| Need | Claude Code uses | Instead of |
|------|------------------|------------|
| GitHub issues, PRs, checks, merge queue | `gh` | (never an MCP) |
| Supabase schema, RLS, local DB | `npx --yes supabase@latest` | `supabase` MCP |
| Library / framework / SDK docs | `npx ctx7@latest` | `context7` MCP |
| shadcn registry / components | `npx shadcn@latest` | `shadcn` MCP |
| E2E browser flows | `npx playwright` | `playwright` MCP |
| Deploy, env vars | `vercel` | `plugin-vercel-vercel` MCP |
| Celery / Redis inspection | `celery` CLI, `redis-cli` | `celery`, `upstash` MCP |
| Layout / component extraction | **MCP** `open-design` | — no CLI exists |
| Screen / flow inspiration | **MCP** `Mobbin` | — no CLI exists |
| Figma read/write | **MCP** `figma` (load `figma-use` first) | — no CLI exists |

Executor subagents are configured with **no MCP tools at all**. If an Executor thinks it
needs a design reference, the Meta routing was wrong: stop and report rather than reaching
for a tool.

Cursor keeps using the MCP servers listed in the body — that is expected, and neither
harness should be changed to match the other here.
"""

# phase -> which agent(s) may load the skill; extra -> appended contract lines.
PHASE = {
    "focus": ("All phases — router", "Run this **first** on every non-trivial task. Emit a Context Plan with an explicit *DO NOT load* list before touching anything else."),
    "skill-catalog": ("Architect / Meta — external tooling router", CATALOG_EXTRA),
    "grill-with-docs": ("Planning (Architect)", "One question at a time, each with a recommended answer. Update `CONTEXT.md` and ADRs inline as decisions crystallise."),
    "to-prd": ("Planning (Architect)", None),
    "to-issues": ("Planning (Architect)", "Tracer-bullet vertical slices. Record child slice IDs in `agent-runtime/config/agent-runtime.config.yml` `epicRegistry` when opening a new epic."),
    "domain-modeling": ("Planning (Architect)", None),
    "codebase-design": ("Planning (Architect) / ad-hoc", None),
    "improve-codebase-architecture": ("Ad-hoc — explore → report → grill → execute", None),
    "restructure": ("Ad-hoc", "Mechanical moves only, when the target structure is already decided. The same tests must pass before and after every issue."),
    "api-docs": ("Planning / Implementation", "Pair with the Context7 **CLI** (`npx ctx7@latest`) when SDK references are needed — Context7 is not an MCP in this repo."),
    "platform-docs": ("Planning", "Uses WebFetch against vendor University/policy pages. Context7 CLI only for partner SDK docs."),
    "prompt-caching": ("Meta", "Governs the two-tier workflow prompt cache. Meta owns it; Executors consume the injected blocks and must not rewrite them."),
    "handoff": ("Any phase — session boundary", None),
    "qa": ("Ad-hoc / Implementation intake", None),
    "diagnose": ("Implementation", None),
    "ui-bug": ("Planning intake (UI defects)", None),
    "screenshot-annotate": ("Internal — invoked by `ui-bug` only", None),
    "extract-design-md": ("Ad-hoc (design system extraction)", None),
    "open-design-system": ("Planning / Meta — design reference", "Upstream of `ui-ux-design` per ADR-043. Uses the `open-design` MCP, reference-only. **Executor agents have no MCP tools** — design references are gathered before the Executor starts."),
    "ui-ux-design": ("Implementation (ui-ux executor)", "Read ADR-028 `dictionary.md` and `docs/product/design/` soul + ux_principles before writing components."),
    "intent-review": ("Review", "First step of Review. Emits the intent-review artifact that `guardrails` must consume — do not skip to guardrails."),
    "guardrails": ("Review", "Consumes the intent-review artifact and emits the ADR-003 review artifact."),
    "validate": ("Review", "Runs every `agent-runtime/scripts/validate/*.py` gate and emits `agent-runtime/artifacts/validation/validation-issue-<n>.json`. Deterministic — do not summarise gate output, run the gates."),
    "ship": ("Review — ship-ready", "Prepares and validates; never deploys directly. Merge Queue is primary, sync-before-merge is the fallback only."),
    "write-a-skill": ("Ad-hoc — requires explicit user request", "Skills governance: never scaffold a skill for convenience. When a new Cursor skill is approved, add its `.claude/skills/` pointer in the same change."),
    "backend-executor": ("Implementation (Executor)", "Juli product logic and `/v1/*` FastAPI. **Not** vendor I/O (that is `integrations-executor`) and not schema/ETL durability (that is `data-platform-executor`)."),
    "ui-ux-executor": ("Implementation (Executor)", "Web and iOS UI: `apps/dashboard`, `apps/demo`, `ios/`, `packages/*`."),
    "data-platform-executor": ("Implementation (Executor)", "Postgres schema, Alembic migrations, repositories, ETL consumer durability."),
    "machine-learning-executor": ("Implementation (Executor)", "Work under `backend/src/juli_backend/ai/` and model promotion paths."),
    "integrations-executor": ("Implementation (Executor)", "Vendor clients, webhooks, polling/sync, analytics backfill — platform-agnostic commerce I/O."),
}

INTERNAL = {"screenshot-annotate"}


def parse_frontmatter(text: str) -> tuple[str, str]:
    # Tolerate a stray leading blank line before the fence (qa/SKILL.md has one).
    m = re.match(r"^\s*---\n(.*?)\n---\n", text, re.S)
    if not m:
        return "", ""
    fm = m.group(1)
    name = re.search(r"^name:\s*(.+)$", fm, re.M)
    folded = re.search(r"^description:\s*(?:>-|>|\|)\s*\n((?:[ \t]+\S.*\n?)+)", fm, re.M)
    inline = re.search(r"^description:\s*(\S.*)$", fm, re.M)
    if folded:
        desc = " ".join(line.strip() for line in folded.group(1).splitlines() if line.strip())
    elif inline:
        desc = inline.group(1).strip()
    else:
        desc = ""
    return (name.group(1).strip() if name else ""), desc


def yaml_block(key: str, value: str) -> str:
    """Emit a folded scalar so long descriptions stay readable and quote-safe."""
    if len(value) <= 80 and not any(c in value for c in ":#\"'"):
        return f"{key}: {value}\n"
    wrapped, line = [], ""
    for word in value.split():
        if len(line) + len(word) + 1 > 88:
            wrapped.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        wrapped.append(line)
    body = "\n".join(f"  {w}" for w in wrapped)
    return f"{key}: >-\n{body}\n"


def main() -> int:
    sources = sorted(CURSOR.glob("**/SKILL.md"))
    if not sources:
        print("no source skills found", file=sys.stderr)
        return 1

    written, skipped = [], []
    for src in sources:
        name, desc = parse_frontmatter(src.read_text())
        if not name or not desc:
            skipped.append(str(src.relative_to(REPO)))
            continue

        rel = src.relative_to(REPO)
        siblings = sorted(
            p.name for p in src.parent.iterdir()
            if p.is_file() and p.name not in {"SKILL.md", ".DS_Store"}
        )
        phase, extra = PHASE.get(name, ("Focus-selected", None))

        fm = ["---", yaml_block("name", name).rstrip(), yaml_block("description", desc).rstrip()]
        if name in INTERNAL:
            fm.append("user-invocable: false")
        fm.append("---")

        lines = [
            "\n".join(fm),
            "",
            f"# {name}",
            "",
            f"**Phase:** {phase}",
            "",
            f"**Authoritative body:** [`{rel}`](../../../{rel})",
            "",
            "Read that file now and follow it. This pointer exists so Claude Code can discover",
            "and route the skill — the procedure itself is deliberately not restated here. The",
            "`.cursor/` file is the single source of truth for both harnesses; edit it there, and",
            "never fork a copy into `.claude/`.",
        ]

        if siblings:
            lines += ["", "**Bundled resources** in the same directory (load only when the body says to):", ""]
            lines += [f"- [`{s}`](../../../{rel.parent}/{s})" for s in siblings]

        if extra:
            lines += ["", "## Contract", "", extra]

        dest = TARGET / name / "SKILL.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("\n".join(lines).rstrip() + "\n")
        written.append(name)

    print(f"wrote {len(written)} pointer skills -> {TARGET.relative_to(REPO)}")
    for n in written:
        print(f"  {n}")
    if skipped:
        print(f"skipped (no name/description frontmatter): {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
