/**
 * Transform approved workflow inputs into the backend execution payload.
 * Maps UI field names to backend API contract names.
 *
 * Returns the payload ready to serialize to `POST /v1/executions` body.
 * Resolves type mismatch by keeping all values as strings per approvedInputs contract;
 * backend handler converts via `int(payload["quantity"])`.
 */
export function buildReplenishInventoryExecutionPayload(
  approvedInputs: Record<string, string>,
): Record<string, string> {
  const payload = { ...approvedInputs };

  // Map reorder_quantity (UI field key) → quantity (backend API contract)
  if ("reorder_quantity" in payload) {
    const qty = payload.reorder_quantity;
    // Convert to integer string so backend int() parsing is unambiguous
    payload.quantity = qty ? String(Math.max(1, parseInt(qty, 10))) : "0";
    delete payload.reorder_quantity;
  }

  return payload;
}
