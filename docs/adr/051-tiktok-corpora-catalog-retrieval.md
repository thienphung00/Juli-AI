# ADR-051: TikTok document corpora — catalog retrieval for Architect/Meta

**Status:** Accepted  
**Date:** 2026-07-29  
**Deciders:** grill-with-docs (Architect)

**Builds on:** crawl plans under `local/adhoc` (Academy / Partner / Business corpora),
existing curated pair `docs/integrations/tiktok_api/` + `docs/integrations/tiktok_platform/`,
Focus routing, `api-docs` / `platform-docs` promote paths.  
**Related:** [ADR-031](031-integrations-executor-domain.md) (Executor must not own vendor-doc retrieval).

## Context

Three large markdown corpora (~2.5k pages) exist from TikTok crawls:

| Corpus | Role |
|--------|------|
| `business_documents/` | TikTok Business API |
| `academy_documents/` | TikTok Academy (UI/product/seller-facing) |
| `partner_documents/` | TikTok Partner API + webhooks |

Agents need them for **planning** and **ad-hoc decision verification**, including
cross-corpus synthesis, **without** loading full documents or full trees into
context by default. Bodies today live only under `.worktrees/adhoc/` (gitignored,
`local/adhoc` never pushed). Curated `docs/integrations/` remains the
Juli-mapped implementation reference.

Alternatives considered:

- **Embedding RAG** — rejected for v1 (new store/pipeline; catalog + Grep/Read enough).
- **Curated-promote-only** (never query raw corpora) — rejected (loses depth and
  cross-corpus verification).
- **Commit full corpora to git** — rejected (size/churn; prior crawl grills).
- **Keep bodies only on `local/adhoc`** — rejected (feature/main worktrees cannot reach them).
- **New Cursor skill** — deferred; Focus + playbook sufficient for v1.
- **Executor/Review may Read corpus pages** — rejected (Composer / small-context;
  corpora reserved for Architect/Meta large-context models).

## Decision

1. **Retrieval (v1):** corpus **catalog** → Grep → **selective Read** of matched
   pages only. No embedding RAG.

2. **Body residency:** shared local root outside git:
   `/Users/macos/Juli-AI-local/tiktok-corpora/{business,academy,partner}_documents/`.
   Optional override via env `JULI_TIKTOK_CORPORA_ROOT` (same layout under that root).

3. **Catalogs on `main`:** thin indexes committed at
   `docs/integrations/tiktok_corpora/{business,academy,partner}-catalog.json`
   plus a README playbook. Regenerate after crawls; **never** commit markdown bodies.

4. **Catalog entry fields (minimum):** `corpus`, `path` (relative to that corpus
   directory), `title`, `url`, `slug`, `section`, `nav_path`, `page_kind`,
   `last_crawled`; optional `method`, `api_path`, `version` when present in
   front matter. Exclude Partner `partner_documents/_raw/**` from catalogs and
   default Grep.

5. **Layered authority:** curated `tiktok_api` / `tiktok_platform` = Juli
   implementation / code SoT. Corpora = vendor depth, gap-fill, verification.
   On conflict, cite both; curated binds code until promote via `api-docs` /
   `platform-docs` (or an ADR).

6. **Harness wiring:** Focus Context Plan + `docs/integrations/tiktok_corpora/README.md`
   + a catalog regen script on `main` (e.g. under `scripts/`). **No** new skill in v1.

7. **Phase gate:** only **Architect (Planning)** and **Meta** may open corpus
   catalogs/bodies (large-context models, e.g. Grok 4.5). **Executor** and
   **Review** must not — curated docs + ADRs only.

8. **Downstream distillate:** Architect/Meta distill raw-page findings into
   **ADRs and curated docs**. Lasting contracts promote before implement;
   ephemeral notes may land in PRD/issue/Meta cache but must not pass raw corpus
   paths to Executor as a substitute.

9. **Task → corpus defaults (Architect/Meta):** Academy for UI/product/seller
   policy; Business + Partner for webhooks/API/data-model; all three only for
   cross-surface synthesis or curated gap/conflict.

10. **Missing bodies:** fail soft — catalogs still load for discovery; if a body
    path is absent, state “corpus body unavailable,” use catalog metadata +
    curated docs; never invent page content.

## Consequences

- Focus must gain routing rows for TikTok corpora (Architect/Meta only;
  DO NOT Load for Executor/Review).
- One-time move/symlink from `.worktrees/adhoc/*_documents` → `Juli-AI-local/tiktok-corpora/`.
- Catalog regen + first committed catalogs are implementation follow-through
  (PRD/issues), not part of this ADR text.
- Crawlers may keep writing under adhoc during transition; output root should
  retarget to the shared local path.
- Embedding RAG remains an explicit non-goal until catalog retrieval proves
  insufficient.