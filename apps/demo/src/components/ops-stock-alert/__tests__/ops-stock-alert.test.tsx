import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { OpsStockAlert, createStockAlertApi, type StockAlertApi, type StockAlertSettings } from "../ops-stock-alert";

function fake(initial: StockAlertSettings): StockAlertApi & { put: ReturnType<typeof vi.fn> } {
  let current = initial;
  return {
    get: vi.fn(async () => current),
    put: vi.fn(async (body: { status?: StockAlertSettings["status"]; days?: number }) => {
      current = { status: body.status ?? current.status, days: body.days ?? current.days };
      return current;
    }),
  };
}

describe("OpsStockAlert", () => {
  it("shows the current values from GET and saves the new ones with PUT", async () => {
    const api = fake({ status: "preview", days: 14 });
    render(<OpsStockAlert api={api} canEdit shopId="shop-1" />);
    const preview = await screen.findByRole("radio", { name: "Xem trước" });
    await waitFor(() => expect(preview).toBeChecked());
    expect(screen.getByLabelText("Số ngày cảnh báo")).toHaveValue(14);
    await userEvent.click(screen.getByRole("radio", { name: "Bật" }));
    const days = screen.getByLabelText("Số ngày cảnh báo");
    await userEvent.clear(days);
    await userEvent.type(days, "10");
    await userEvent.click(screen.getByRole("button", { name: "Lưu" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith({ status: "on", days: 10 }));
    expect(screen.getByRole("radio", { name: "Bật" })).toBeChecked();
  });

  it("will not save days outside 1-60 and is read-only for Xem", async () => {
    const api = fake({ status: "off", days: 7 });
    const { rerender } = render(<OpsStockAlert api={api} canEdit shopId="shop-1" />);
    const days = await screen.findByLabelText("Số ngày cảnh báo");
    await waitFor(() => expect(days).toBeEnabled());
    await userEvent.clear(days);
    await userEvent.type(days, "61");
    expect(screen.getByRole("button", { name: "Lưu" })).toBeDisabled();
    rerender(<OpsStockAlert api={api} canEdit={false} shopId="shop-1" />);
    expect(screen.getByRole("button", { name: "Lưu" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: "Bật" })).toBeDisabled();
  });

  it("shows the backend's sentence when the save is refused", async () => {
    const api = fake({ status: "off", days: 7 });
    api.put.mockRejectedValueOnce(new Error("Shop mẫu không bật được."));
    render(<OpsStockAlert api={api} canEdit shopId="shop-1" />);
    await waitFor(() => expect(screen.getByRole("radio", { name: "Bật" })).toBeEnabled());
    await userEvent.click(screen.getByRole("radio", { name: "Bật" }));
    await userEvent.click(screen.getByRole("button", { name: "Lưu" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Shop mẫu không bật được.");
  });

  it("the client calls /v1/ops/shops/{id}/stock-alert with the token", async () => {
    const f = vi.fn(async () => new Response(JSON.stringify({ status: "off", days: 7 }), { status: 200 }));
    const client = createStockAlertApi("abc", "tok", f as unknown as typeof fetch);
    await client.put({ days: 9 });
    expect(f).toHaveBeenCalledWith(
      "/v1/ops/shops/abc/stock-alert",
      expect.objectContaining({ method: "PUT", body: JSON.stringify({ days: 9 }) }),
    );
  });
});
