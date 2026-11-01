/**
 * Poll cadence for the run ledger's `GET /v1/demo/runs` refetch
 * (PUI-DESIGN.md §4/§8: "others refetch" -- every card not holding a live
 * per-run stream). P82 (Supabase egress): 15s, and only while the tab is
 * visible and some run in the list is still live -- a status change the seller
 * causes (approve, a confirmation, a revert) or a run's stream ending refreshes
 * the list at once, so the poll only has to catch what moves on its own.
 */
export const RUN_LEDGER_POLL_INTERVAL_MS = 15_000;
