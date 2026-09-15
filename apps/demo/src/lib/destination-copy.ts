/**
 * The Hành động destination's seller-facing name (dictionary `nav.decisions`;
 * route `/decisions`). Owner decision on #1910 (2026-09-14): the tab is
 * Hành động — superseding the earlier "Quyết định" label.
 *
 * ONE constant, three consumers — the nav rail fixture (`lib/mock-data.ts`),
 * the assistance aside's destination eyebrow (`components/demo-shell.tsx`),
 * and the run header's back control (`lib/run-surface/stage-copy.ts`'s
 * `RUN_HEADER_BACK_LABEL`) — so the rail and the back control cannot drift
 * apart again. Keep byte-identical with the dictionary entry (ADR-028).
 */
export const ACTIONS_DESTINATION_LABEL = "Hành động";
