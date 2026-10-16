/**
 * The partner trial account's sample shop, kept for the browser session (fast
 * track P32-E, D42 amendment 2, owner 2026-10-15). With no reference shop
 * pinned the reviewer uses every feature over the bundled sample: Duyệt /
 * Từ chối / consent edits / photo / Seller Center / content cards / Hoàn tác /
 * Quy tắc all change ONE in-memory store (`createSampleQdClients`), shared by
 * Quyết định and Cài đặt so a rule saved on one page shows on the other.
 *
 * Module state only: nothing is written to browser storage, nothing is sent —
 * no request call site in this module's graph (`replay-module-graph.test.ts`
 * walks it from the sample Quyết định). A full reload, sign-out or
 * "Đặt lại dữ liệu mẫu" starts the sample over.
 *
 * P37 (D47.2): the one sample store of the tab — the signed-out visitor and a
 * seller with no shop use it too, and Phân tích reads its cards
 * (`fetchDeskDecisions`), so every sample view follows the same lifecycle.
 */

import { createSampleQdClients, type SampleClientsOptions, type SampleQdClients } from "../quyet-dinh/sample-clients";

let store: SampleQdClients | null = null;
let options: SampleClientsOptions = {};
let epoch = 0;
const listeners = new Set<() => void>();

/** The session's sample store (created on first use). */
export function reviewerSampleClients(): SampleQdClients {
  if (!store) store = createSampleQdClients(options);
  return store;
}

/** Bumped by every reset: pages key their sample views on it. */
export function reviewerSampleEpoch(): number {
  return epoch;
}

export function subscribeReviewerSample(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * "Đặt lại dữ liệu mẫu": drop every simulated decision, run and rule.
 * `next` is a test seam (`stepMs: 0`); it sticks until the next reset.
 */
export function resetReviewerSample(next?: SampleClientsOptions): void {
  if (next) options = next;
  store = null;
  epoch += 1;
  for (const listener of listeners) listener();
}
