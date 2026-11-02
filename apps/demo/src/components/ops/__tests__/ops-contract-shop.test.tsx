import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OpsApiError } from "../../../lib/ops/api";
import type { ShopConsent } from "../../../lib/ops/types";
import { OpsAddContractShop, OpsShopConsent } from "../ops-contract-shop";

/** ADR-118 contract-client shops: "Thêm shop hợp đồng" and the no-field "Bật" consent button. */

const SCOPES = { service: false, llm_processing: false, llm_images: false, llm_media: false };
const OFF: ShopConsent = { scopes: SCOPES, enabled: false, contract_client: true };
const ON: ShopConsent = {
  scopes: { service: true, llm_processing: true, llm_images: true, llm_media: true },
  enabled: true,
  contract_client: true,
};

describe("Thêm shop hợp đồng", () => {
  it("sends the name and Shopee id, then reloads the list", async () => {
    const createContractShop = vi.fn().mockResolvedValue({ shop: { id: "s1", shop_name: "A", platform: "shopee", shopee_shop_id: "123" } });
    const onCreated = vi.fn();
    render(<OpsAddContractShop api={{ createContractShop }} onCreated={onCreated} />);
    fireEvent.click(screen.getByRole("button", { name: "+ Thêm shop hợp đồng" }));
    fireEvent.change(screen.getByLabelText("Tên shop"), { target: { value: " Shop A " } });
    fireEvent.change(screen.getByLabelText("Mã shop Shopee (không bắt buộc)"), { target: { value: "123" } });
    fireEvent.click(screen.getByRole("button", { name: "Tạo shop" }));
    await waitFor(() => expect(onCreated).toHaveBeenCalled());
    expect(createContractShop).toHaveBeenCalledWith("Shop A", "123");
  });

  it("says when the Shopee id is already in Juli", async () => {
    const createContractShop = vi.fn().mockRejectedValue(new OpsApiError(409, "taken"));
    render(<OpsAddContractShop api={{ createContractShop }} onCreated={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "+ Thêm shop hợp đồng" }));
    fireEvent.change(screen.getByLabelText("Tên shop"), { target: { value: "Shop A" } });
    fireEvent.click(screen.getByRole("button", { name: "Tạo shop" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("đã có trong Juli");
  });
});

describe("Đồng ý xử lý dữ liệu", () => {
  it("one press, no fields, turns consent on", async () => {
    const api = { consent: vi.fn().mockResolvedValue(OFF), enableConsent: vi.fn().mockResolvedValue(ON) };
    render(<OpsShopConsent api={api} canEdit shopId="s1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Bật" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Đã bật");
    expect(api.enableConsent).toHaveBeenCalledWith("s1");
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("a viewer sees the state but no button", async () => {
    const api = { consent: vi.fn().mockResolvedValue(OFF), enableConsent: vi.fn() };
    render(<OpsShopConsent api={api} canEdit={false} shopId="s1" />);
    expect(await screen.findByText("Đồng ý xử lý dữ liệu")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Bật" })).toBeNull();
  });

  it("a seller's shop shows nothing: their consent is their own", async () => {
    const api = { consent: vi.fn().mockResolvedValue({ ...OFF, contract_client: false }), enableConsent: vi.fn() };
    const { container } = render(<OpsShopConsent api={api} canEdit shopId="s1" />);
    await waitFor(() => expect(api.consent).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
