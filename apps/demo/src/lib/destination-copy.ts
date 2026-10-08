/**
 * The Quyết định destination's seller-facing name (dictionary `nav.decisions`;
 * route `/decisions`). Owner decision D21 (fast track, 2026-10-08) restores
 * "Quyết định", overriding #1910's interim "Hành động" label.
 *
 * ONE constant, three consumers — the nav fixture (`lib/mock-data.ts`),
 * the assistance aside's destination eyebrow (`components/demo-shell.tsx`),
 * and the run header's back control (`lib/run-surface/stage-copy.ts`'s
 * `RUN_HEADER_BACK_LABEL`) — so the nav and the back control cannot drift
 * apart again. Keep byte-identical with the dictionary entry (ADR-028).
 */
export const ACTIONS_DESTINATION_LABEL = "Quyết định";
