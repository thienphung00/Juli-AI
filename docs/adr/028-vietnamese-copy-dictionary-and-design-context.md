# ADR 028: Vietnamese copy dictionary and design-context split

## Status
Accepted

## Context

Juli is Vietnamese-first for seller-facing UI, reports, and copy-layer output. Agents
need a lookup catalog so they write Vietnamese directly instead of translating from
English (which loses nuance). The design package already had
`docs/product/design/context.md` (glossary + voice rules), but that path collided
naming-wise with root `CONTEXT.md` (English domain glossary) and was often skipped
in Focus / slice routing.

Alternatives considered: a single root `language.md` that absorbed everything; keeping
glossary inside the design package; embedding EN→VI in i18n JSON as the authoring
source of truth.

## Decision

- We will: Split authority with **zero content overlap**:
  - Root [`dictionary.md`](../../dictionary.md) — sole EN → VI **Keywords** and
    **Phrases** catalog (surface-first keys, EN gloss, VI string, optional `_Avoid_`).
  - [`docs/product/design/design-context.md`](../product/design/design-context.md) —
    voice and copy **rules only** (address form, naming conventions, money/dates,
    error/empty patterns, governance). Renamed from `context.md`.
- We will: Rewire Focus, design README / flows / ux_principles, and
  `agent-runtime/config/slice-routing.yml` to those paths — **no stub** at the old
  `context.md` path.
- We will: Require Focus to load **both** files for any UI, copy, report, or
  design-surface task.
- We will not: Duplicate glossary rows in Design context; treat i18n JSON as the
  authoring source of truth; ship invented Vietnamese only in code without a
  dictionary key.
- v1 harvest: migrate the existing design glossary + VI already present in
  Screens/Components/Flows; omit or mark TBD where design only has English — humans
  correct afterward.
- Missing-key escape hatch (recorded in Design context): if dictionary has no entry
  for needed UI/frontend copy, the agent may draft Vietnamese, then **must** add the
  keyed entry to `dictionary.md` in the same change so developers can fix wording.

## Consequences

- Agents have an unambiguous root dictionary for lookups and a smaller design-context
  for tone/rules.
- Design package precedence lists must cite `design-context.md` and point upward to
  `dictionary.md` for terms.
- Adding a new seller-facing string means updating `dictionary.md` first (new key),
  then using that VI in code/specs.
