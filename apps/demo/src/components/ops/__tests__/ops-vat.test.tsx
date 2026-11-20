import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OpsVat, type OpsVatApi, type VatRates } from "../ops-vat";

/** F6.3: Ops "Thuế VAT": the shop default and a rate per product, written for the item and every variation. Synthetic data. */

const fake = (state: { rates: VatRates }): OpsVatApi => ({
  read: vi.fn(async () => state.rates),
  put: vi.fn(async () => undefined),
  remove: vi.fn(async () => undefined),
  search: vi.fn(async () => [{ item_id: "111", name: "Nước rửa mẫu" }]),
  variationIds: vi.fn(async () => ["1", "2"]),
});

describe("Ops · Thuế VAT", () => {
  it("sets the shop default through the rules route", async () => {
    const api = fake({ rates: { default: null, rates: [] } });
    render(<OpsVat api={api} canEdit shopId="s1" />);
    const select = await screen.findByLabelText("Thuế VAT mặc định");
    await waitFor(() => expect(select).not.toBeDisabled());
    fireEvent.change(select, { target: { value: "8" } });
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("vat_rate_default", null, 8));
  });

  it("a product rate is written for the item and for every variation", async () => {
    const api = fake({ rates: { default: 8, rates: [] } });
    render(<OpsVat api={api} canEdit shopId="s1" />);
    await screen.findByLabelText("Thuế VAT mặc định");
    fireEvent.change(screen.getByLabelText("Tìm sản phẩm"), { target: { value: "nước" } });
    fireEvent.click(await screen.findByRole("button", { name: "Nước rửa mẫu 10%" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(3));
    expect(api.put).toHaveBeenCalledWith("vat_rate", "111", 10);
    expect(api.put).toHaveBeenCalledWith("vat_rate", "111:1", 10);
    expect(api.put).toHaveBeenCalledWith("vat_rate", "111:2", 10);
  });

  it("lists current rates per product and removes the item with its variations", async () => {
    const api = fake({
      rates: {
        default: 8,
        rates: [
          { scope_ref: "111", value: 10 },
          { scope_ref: "111:1", value: 10 },
          { scope_ref: "111:2", value: 10 },
          { scope_ref: "222:9", value: 5 },
        ],
      },
    });
    render(<OpsVat api={api} canEdit shopId="s1" />);
    const row = await screen.findByTestId("vat-rate-111");
    expect(row).toHaveTextContent("10%");
    expect(screen.getByTestId("vat-rate-222")).toHaveTextContent("5%");
    expect(screen.getByLabelText("Thuế VAT mặc định")).toHaveValue("8");
    fireEvent.click(screen.getByRole("button", { name: "Bỏ 111" }));
    await waitFor(() => expect(api.remove).toHaveBeenCalledTimes(3));
    expect(api.remove).toHaveBeenCalledWith("vat_rate", "111:2");
  });

  it("Xem only reads", async () => {
    render(<OpsVat api={fake({ rates: { default: 8, rates: [{ scope_ref: "111", value: 10 }] } })} canEdit={false} shopId="s1" />);
    await screen.findByTestId("vat-rate-111");
    expect(screen.queryByLabelText("Tìm sản phẩm")).toBeNull();
    expect(screen.queryByRole("button", { name: /Bỏ/ })).toBeNull();
    expect(screen.getByLabelText("Thuế VAT mặc định")).toBeDisabled();
  });
});
