# TikTok document corpora — catalog retrieval playbook

Agent access path for three large TikTok markdown archives used during **planning**
and **ad-hoc vendor verification**. Implementation code and Review validation stay on
curated integrations docs — not raw corpora.

**Canonical decision:** [ADR-051](../../adr/051-tiktok-corpora-catalog-retrieval.md) ·
**PRD:** [tiktok-corpora-catalog](../../product/phases/tiktok-corpora-catalog/PRD.md)

## Corpora

| Corpus directory | Source | Use for |
|------------------|--------|---------|
| `business_documents/` | TikTok Business API | Webhooks, API contracts, data-model depth |
| `academy_documents/` | TikTok Academy | UI, product copy, seller-facing policy |
| `partner_documents/` | TikTok Partner API + webhooks | Webhooks, API contracts, data-model depth |

## Body residency (shared local root)

Markdown **bodies** live outside git so every worktree can reach them when present:

```
/Users/macos/Juli-AI-local/tiktok-corpora/
├── business_documents/
├── academy_documents/
└── partner_documents/
```

**Override:** set `JULI_TIKTOK_CORPORA_ROOT` to another directory; keep the same
`{business,academy,partner}_documents/` layout underneath.

**Bootstrap:** one-time move or symlink from `.worktrees/adhoc/*_documents` into the
shared root above. Do not commit markdown bodies to `main`.

**Crawler output:** retarget crawlers to write directly into
`$JULI_TIKTOK_CORPORA_ROOT/{business,academy,partner}_documents/` (default:
`/Users/macos/Juli-AI-local/tiktok-corpora/…`). Legacy adhoc-only output is
transitional — new crawls should land on the shared root, then regen catalogs.

## In-repo indexes (committed on `main`)

Thin JSON catalogs live next to this playbook:

```
docs/integrations/tiktok_corpora/
├── README.md                 ← this playbook
├── business-catalog.json
├── academy-catalog.json
└── partner-catalog.json
```

Regenerate catalogs after every crawl (script on `main` under `scripts/`). Catalogs
contain **metadata only** — never full page bodies.

**Minimum entry fields:** `corpus`, `path` (relative to that corpus directory),
`title`, `url`, `slug`, `section`, `nav_path`, `page_kind`, `last_crawled`; optional
`method`, `api_path`, `version` when present in front matter.

**Partner `_raw/` exclusion:** `partner_documents/_raw/**` is omitted from catalogs
and default Grep — use clean markdown siblings only.

## Retrieval protocol (v1)

No embedding RAG in v1. Approved flow:

1. **Catalog** — load the playbook and the relevant `{business,academy,partner}-catalog.json`.
2. **Grep** — search catalog fields (title, slug, section, nav_path, api_path, …) for
   candidates; for cross-surface questions, search all three catalogs.
3. **Selective Read** — open only matched pages under the shared local root:
   `$JULI_TIKTOK_CORPORA_ROOT/<corpus>_documents/<path>`.

Do not load whole corpora or whole documents by default.

## Layered authority

| Layer | Role |
|-------|------|
| `docs/integrations/tiktok_api/` + `docs/integrations/tiktok_platform/` | **Juli implementation / code SoT** — Executor and Review use these (+ ADRs) |
| TikTok corpora (this playbook + catalogs + local bodies) | Vendor depth, gap-fill, verification for Architect/Meta only |
| ADRs + promoted curated docs | Lasting contracts distilled from corpus findings |

On conflict, cite both sources. Curated docs bind code until a change is promoted via
`api-docs` / `platform-docs` or an ADR. Do not silently override curated mappings
with raw corpus text.

**Downstream distillate:** Architect/Meta turn raw-page findings into ADRs and curated
docs before Executor work. Ephemeral notes may land in PRD/issue/Meta cache but must
**not** pass raw corpus paths to Executor as a substitute for durable SoT.

## Phase gate (non-negotiable)

| Agent phase | Corpus catalogs | Local corpus bodies |
|-------------|-----------------|---------------------|
| **Architect (Planning)** | May load playbook + selected catalog(s) | May Read matched pages (protocol above) |
| **Meta** (planning, ad-hoc vendor depth) | May load playbook + selected catalog(s) | May Read matched pages |
| **Executor** | **DO NOT Load** | **NEVER Read** |
| **Review** | **DO NOT Load** | **NEVER Read** |

Executor and Review implement and validate from curated `tiktok_api` / `tiktok_platform`
and ADRs only. Composer / small-context agents must not ingest raw corpora.

## Task → corpus defaults (Architect/Meta)

| Task type | Default catalog(s) |
|-----------|-------------------|
| UI, product copy, seller policy | **Academy** |
| Webhooks, API contracts, data model | **Business** + **Partner** |
| Cross-surface synthesis, curated gap/conflict | **All three** |

Escalate to all three catalogs when a question spans surfaces or when curated docs
and one corpus disagree.

## Missing bodies (fail soft)

Catalogs still load for discovery when the local root is absent or a page file is
missing.

If a body path is unavailable:

1. State **“corpus body unavailable.”**
2. Use catalog metadata (title, url, section, …) plus curated integrations docs.
3. **Never invent** vendor page content.

Do not hard-fail the entire answer when only bodies are absent.

## Quick reference

| Item | Value |
|------|-------|
| Local root (default) | `/Users/macos/Juli-AI-local/tiktok-corpora/` |
| Env override | `JULI_TIKTOK_CORPORA_ROOT` |
| Catalogs | `docs/integrations/tiktok_corpora/*-catalog.json` |
| Code SoT (Executor/Review) | `docs/integrations/tiktok_api/`, `tiktok_platform/` |
| Excluded from index/Grep | `partner_documents/_raw/**` |
| After crawl | Regen catalogs; do not commit bodies |
