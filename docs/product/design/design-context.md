# Design Context — Vietnamese Copy Rules

> Voice and copy **rules** for every screen, component, and flow in this design
> system. Terminology lookups live in the root dictionary — not here.

**Authority split:** [ADR-028](../../../docs/adr/028-vietnamese-copy-dictionary-and-design-context.md)
defines the split between this file and [`dictionary.md`](../../../dictionary.md).
For Vietnamese labels, keywords, and reusable phrases, use dictionary keys only.

## Product information architecture

Juli has exactly four primary destinations on every platform. Use **English
concept names** in specs and code; resolve user-visible Vietnamese labels from
[`dictionary.md`](../../../dictionary.md) (e.g. `nav.home`, `nav.decisions`,
`nav.analytics`, `nav.settings`).

1. **Home** — a sparse launchpad with two prominent cards: Decisions and
   Analytics.
2. **Decisions** — recommendations and approved work.
3. **Analytics** — all metrics, KPIs, forecasts, and reporting.
4. **Settings** — workflow templates, thresholds, and related configuration.

Juli is contextual assistance within these destinations, not a standalone tab.
She explains the active metric, recommendation, workflow, or setting without
replacing the Decisions approval flow.

## Address form

Juli addresses the seller as **"bạn"** — informal-respectful, never the more
distant "quý khách" or the overly casual "em/anh/chị". This applies to every
first-person and second-person string Juli writes, including empty states,
errors, and contextual assistance.

- Correct: "Bạn có thể xem lại đề xuất này trước khi phê duyệt."
- Avoid: "Quý khách vui lòng xem lại..." (too formal/distant)
- Avoid: "Anh/chị xem lại..." (assumes gender/seniority)

## Naming conventions

- Component names stay in English in code and `Components/*.md`; user-visible
  copy is Vietnamese from [`dictionary.md`](../../../dictionary.md).
- Primary route labels use dictionary keys (`nav.*`); route paths stay English
  (`/`, `/decisions`, `/analytics`, `/settings`). Do not hard-code Vietnamese
  nav strings in specs when a dictionary key exists.
- Workflow display names are Vietnamese in `Screens/` and `Flows/`; stable
  `workflow_id` values remain English slugs. Look up or add workflow names in
  the dictionary.
- Never call a recommendation an "AI Action Card" or "recommendation card" in
  user-facing copy; those are internal terms. Use the dictionary term for
  *Recommendation* (`keywords.recommendation` or equivalent).
- Keep canonical KPI names (SPS, Net Revenue, ROAS, Inventory Turnover,
  Fulfillment Accuracy Rate, CSAT) unchanged; use the dictionary entry for
  *Main KPI* for the set or role, not as a replacement for an individual KPI
  name.

## Money, dates, and numbers

| Type | Rule |
|---|---|
| Currency | Use the currency formatter (`₫` suffix and thousands separator); never hand-format |
| Dates | Use ICT and the date/date-time formatter; never expose a raw ISO string |
| Numbers | Format impact values consistently for separators and rounding |

## Error and empty-state patterns

Every **error** message must state the **problem** and the **recovery step**
in one sentence. Do not leave the seller guessing what went wrong or what to
do next. Draft the Vietnamese using address form and dictionary phrase keys
where available (`phrases.errors.*`).

Every **empty state** must explain **why the surface is empty** and **what
happens next** (or what action the seller can take). Avoid generic "no data"
copy when a specific reason applies (e.g. sync in progress, filters too
narrow, source not connected). Use dictionary phrase keys where they exist
(`phrases.empty.*`).

## Financial data handling

Seller financial fields may appear in formatted UI, but:

- Never leak raw values into logs, prompts, or handoff documents.
- Prefer deltas, trend direction, and tier labels in explanatory copy.
- Mask sensitive drill-down values where the underlying data requires it.

## Missing dictionary entries

When an agent needs UI/frontend copy and [`dictionary.md`](../../../dictionary.md)
has no matching key:

1. Draft Vietnamese consistent with address form and these rules.
2. **In the same change**, add a keyed **Keywords** or **Phrases** entry to
   root [`dictionary.md`](../../../dictionary.md) (surface-first key, EN gloss,
   VI string, `_Avoid_` if known).
3. Use that VI string in the UI/spec via the new key — never only inline.
4. Mark or note so developers can correct wording later (e.g. optional
   `Status: needs_review` on the new dictionary entry).

Never leave invented Vietnamese only in code/specs without a dictionary key.

## Governance

- **Terminology authority** is root [`dictionary.md`](../../../dictionary.md)
  (Keywords and Phrases).
- **This file** is voice and copy-rules authority only (address form, IA
  structure, naming conventions, formatting, error/empty patterns, financial
  handling).
- `Screens/`, `Flows/`, and `Components/` must match dictionary keys **and**
  these rules.
- For new terms or changed copy: update [`dictionary.md`](../../../dictionary.md)
  first, then propagate to specs and code. Lower-tier evidence cannot redefine
  glossary entries.
- Slice routing and design-package precedence lists may cite this file; when
  in doubt, dictionary wins for *what to say*, design-context wins for *how to
  say it*.
