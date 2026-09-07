/**
 * Poll cadence for the run ledger's `GET /v1/demo/runs` refetch
 * (PUI-DESIGN.md §4/§8: "others refetch" -- every card not holding a live
 * per-run stream). 5s balances "the seller sees a status change promptly"
 * against "the shop's runs list is not hammered every second".
 */
export const RUN_LEDGER_POLL_INTERVAL_MS = 5_000;
