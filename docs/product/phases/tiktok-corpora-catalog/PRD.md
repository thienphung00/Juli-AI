# PRD: TikTok document corpora — catalog retrieval for Architect/Meta

> **Canonical docs:** [ADR-051](../../../adr/051-tiktok-corpora-catalog-retrieval.md) ·
> [`CONTEXT.md`](../../../../CONTEXT.md) (Vendor document corpora) ·
> Focus skill routing · curated `docs/integrations/tiktok_api/` + `tiktok_platform/`.
>
> **Parent issue:** [#593](https://github.com/thienphung00/Juli-AI/issues/593) — filed via
> `to-prd` from grill-with-docs (2026-07-29).
> Single implementation issue (user-approved: one large slice).

## Assumptions

- Grill handoff and ADR-051 are authoritative; no re-interview.
- One large AFK-capable implementation issue is preferred over many thin slices.
- Corpus markdown bodies already exist under `.worktrees/adhoc/` and will be moved or
  symlinked to the shared local root (HITL only for machine path confirmation if needed).
- Catalog regen runs on a machine that has the local corpus root; CI does not need
  corpus bodies.
- No new Cursor skill in v1.

## Problem Statement

Architect and Meta agents cannot reliably use the three TikTok document archives
(Business API, Academy, Partner API) during planning or ad-hoc verification. The
archives are large, live only on an ad-hoc worktree, and would overflow context if
loaded whole. Executor and Review must stay on curated integrations docs. Without a
catalog-first access path, agents either invent vendor details or skip verification.

## Solution

Wire **corpus catalog retrieval**: thin indexes committed in-repo; markdown bodies on a
shared local path outside git; Focus routes Architect/Meta to catalog → search →
selective page reads. Findings distill into ADRs and curated docs before Executor work.
Executor and Review never open corpus pages.

## User Stories

1. As an Architect, I want a committed catalog of Business API pages, so that I can
   find relevant vendor docs without opening the whole tree.
2. As an Architect, I want a committed catalog of Academy pages, so that I can ground
   UI/product/seller-policy planning in official Academy wording.
3. As an Architect, I want a committed catalog of Partner API and webhook pages, so that
   I can verify API and data-model decisions against Partner docs.
4. As an Architect, I want to search across all three catalogs when a question spans
   surfaces, so that I can synthesize without loading every file.
5. As Meta, I want Focus to load the corpora playbook and the right catalog(s) for
   planning/context routing, so that large-context models use the approved path.
6. As Meta, I want corpus findings distilled into ADRs or curated docs before Executor
   starts, so that Composer executors never need raw corpus pages.
7. As an Executor, I want Focus to exclude corpus catalogs and bodies from my Context
   Plan, so that I only implement from curated integrations docs and ADRs.
8. As Review, I want the same exclusion, so that validation stays on durable SoT.
9. As an engineer, I want corpus bodies on a stable local root outside git, so that any
   worktree can Read pages when present.
10. As an engineer, I want Partner `_raw` twins excluded from catalogs, so that Grep
    does not return duplicate noisy hits.
11. As an engineer, I want a regen script that rebuilds catalogs from YAML front matter,
    so that after a crawl I can refresh indexes without hand-editing JSON.
12. As an Architect, I want missing local bodies to fail soft, so that catalogs still
    help discovery and I never invent page content.
13. As an engineer, I want a short playbook next to the catalogs, so that Focus and
    humans know the protocol, authority split, and phase gate.
14. As Meta, I want curated integrations docs to remain code SoT, so that corpus text
    cannot silently override Juli mappings.
15. As an engineer, I want crawlers retargeted (or documented) to write into the shared
    local root, so that future crawls do not land only under adhoc again.

## Implementation Decisions

### Modules (by responsibility)

1. **Corpus residency bootstrap** — Move or symlink the three document trees to the
   shared local root defined in ADR-051; document the layout in the playbook.
2. **Catalog builder** — Script that walks each corpus, parses front matter, skips
   Partner `_raw`, emits three catalog JSON files with the minimum fields from ADR-051.
3. **In-repo corpora index package** — Committed catalogs + README playbook under the
   integrations docs area named in ADR-051.
4. **Focus routing** — Context Plan rules: Architect/Meta may load playbook + selected
   catalogs; Executor/Review DO NOT Load corpora; task-typed corpus defaults per ADR-051.
5. **Crawler output alignment** — Update or document adhoc crawler output roots to the
   shared local path (implementation may stay on `local/adhoc` for crawler code).

### Contracts / invariants

- Curated `tiktok_api` / `tiktok_platform` remain Juli implementation SoT.
- Executor/Review never Read corpus markdown bodies.
- Catalogs contain no full page bodies.
- Missing body path → explicit “unavailable,” no invented vendor text.
- Optional env override for corpus root as in ADR-051.

### Assumptions

- First catalog generation runs once after residency bootstrap on this machine.
- Tests focus on catalog builder behavior (front matter → entry; `_raw` skip), not on
  crawling TikTok live.

## Testing Decisions

- Prefer external behavior of the catalog builder: given a small fixture tree of markdown
  with front matter, emit expected catalog entries; skip `_raw`; omit body text from
  output.
- Do not require corpus bodies in CI; fixtures only.
- No live TikTok network tests.
- Focus routing changes are verified by checklist / doc review (or lightweight config
  assertion if routing is data-driven).

## Out of Scope

- Embedding RAG / vector stores
- Committing markdown corpus bodies to git
- New Cursor skill
- Executor or Review opening corpus pages
- Auto-promoting corpus text into curated docs without Architect/Meta distillate
- Re-crawling TikTok (use existing corpora for first catalogs)

## Further Notes

- Risk: catalogs drift after crawl if regen is skipped — playbook should state regen
  after every crawl.
- Risk: other machines lack bodies — fail soft is intentional.
- Rollout: ADR-051 + CONTEXT already accepted; this PRD is harness wiring only.
- Follow-up: if catalog+Grep proves insufficient, revisit RAG as a separate grill (not
  this issue).
