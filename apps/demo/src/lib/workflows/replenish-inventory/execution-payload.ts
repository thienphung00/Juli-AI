/**
 * Transform approved workflow inputs into the backend execution payload.
 * Maps UI field names to backend API contract names.
 */
export function buildReplenishInventoryExecutionPayload(
  approvedInputs: Record<string, string>,
): Record<string, string | number> {
  const payload = { ...approvedInputs } as Record<string, string | number>;

  // Map reorder_quantity (UI field) → quantity (backend contract)
  if ("reorder_quantity" in payload) {
    const qty = payload.reorder_quantity as string;
    payload.quantity = qty ? parseInt(qty, 10) : 0;
    delete payload.reorder_quantity;
  }

  return payload;
}
