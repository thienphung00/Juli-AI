"use client";

import { simulateDecision } from "../../lib/reviewer/api-client";
import { SimulationDialog, type Simulate } from "./simulation-dialog";

/**
 * The partner trial account's Duyệt → Thực thi over the API (fast track
 * P32-A, contract p32-reviewer-access.md §4): the pinned (masked) shop's card
 * through `POST /v1/reviewer/decisions/{id}/simulate`. The real approve route
 * is never called; the server refuses it for a reviewer. The dialog itself is
 * `simulation-dialog.tsx` (shared with the sample shop, P32-D).
 */
export function ReviewerSimulation({
  cardId,
  token,
  shopId,
  onClose,
  simulate,
}: {
  readonly cardId: string;
  readonly token: string;
  readonly shopId: string;
  readonly onClose: () => void;
  readonly simulate?: Simulate;
}) {
  return (
    <SimulationDialog
      cardId={cardId}
      onClose={onClose}
      simulate={simulate ?? ((id, step) => simulateDecision(id, step, { token, shopId }))}
    />
  );
}
