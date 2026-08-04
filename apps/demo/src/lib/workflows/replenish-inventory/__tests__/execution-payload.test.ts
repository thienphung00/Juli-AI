import { describe, expect, it } from "vitest";

import { buildReplenishInventoryExecutionPayload } from "../execution-payload";

describe("buildReplenishInventoryExecutionPayload", () => {
  it("maps reorder_quantity to quantity for backend contract", () => {
    const approvedInputs = {
      sku_id: "SKU-SPF50-001",
      current_stock: "48",
      warehouse_id: "WH-HCM-01",
      reorder_quantity: "96",
      external_path: "supplier-x",
      received_quantity: "",
    };

    const payload = buildReplenishInventoryExecutionPayload(approvedInputs);

    expect(payload.quantity).toBe("96");
    expect(payload.reorder_quantity).toBeUndefined();
    expect(payload.sku_id).toBe("SKU-SPF50-001");
    expect(payload.current_stock).toBe("48");
  });

  it("handles empty reorder_quantity gracefully", () => {
    const approvedInputs = {
      sku_id: "SKU-SPF50-001",
      current_stock: "48",
      warehouse_id: "WH-HCM-01",
      reorder_quantity: "",
      external_path: "supplier-x",
      received_quantity: "",
    };

    const payload = buildReplenishInventoryExecutionPayload(approvedInputs);

    expect(payload.quantity).toBe("0");
    expect(payload.reorder_quantity).toBeUndefined();
  });

  it("allows seller to override suggested quantity", () => {
    const approvedInputs = {
      sku_id: "SKU-SPF50-001",
      current_stock: "48",
      warehouse_id: "WH-HCM-01",
      reorder_quantity: "150", // Seller overrides computed suggestion (96)
      external_path: "supplier-x",
      received_quantity: "",
    };

    const payload = buildReplenishInventoryExecutionPayload(approvedInputs);

    expect(payload.quantity).toBe("150");
  });
});
