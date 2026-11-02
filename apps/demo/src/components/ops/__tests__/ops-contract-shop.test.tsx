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
    const api = {
      consent: vi.fn().mockResolvedValue(OFF),
      enableConsent: vi.fn().mockResolvedValue(ON),
      ingestTokens: vi.fn().mockResolvedValue({ data: [] }),
    };
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

describe("Kết nối dữ liệu", () => {
  const TOKEN = {
    id: "t1",
    client_label: "Juli Connector",
    created_at: "2026-11-02T07:00:00Z",
    expires_at: "2027-01-31T07:00:00Z",
    last_used_at: null,
    revoked_at: null,
    active: true,
  };

  it("shows a one-use code after 'Tạo mã kết nối' and revokes a source", async () => {
    const api = {
      consent: vi.fn().mockResolvedValue(ON),
      enableConsent: vi.fn(),
      createPairingCode: vi.fn().mockResolvedValue({ code: "ABCDE-FGHJK", expires_at: "2026-11-02T07:10:00Z", ttl_seconds: 600 }),
      ingestTokens: vi.fn().mockResolvedValueOnce({ data: [TOKEN] }).mockResolvedValue({ data: [{ ...TOKEN, active: false }] }),
      revokeIngestToken: vi.fn().mockResolvedValue(undefined),
    };
    render(<OpsShopConsent api={api} canEdit shopId="s1" />);
    expect(await screen.findByText("1 nguồn đang kết nối")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Tạo mã kết nối" }));
    expect(await screen.findByLabelText("Mã kết nối")).toHaveTextContent("ABCDE-FGHJK");
    expect(screen.getByLabelText("Mã kết nối")).toHaveTextContent("hết hạn sau 10 phút");
    fireEvent.click(screen.getByRole("button", { name: "Thu hồi" }));
    expect(await screen.findByText("Chưa có nguồn nào kết nối.")).toBeInTheDocument();
    expect(api.revokeIngestToken).toHaveBeenCalledWith("s1", "t1");
  });

  it("a viewer sees the sources but cannot make a code or revoke", async () => {
    const api = { consent: vi.fn().mockResolvedValue(ON), ingestTokens: vi.fn().mockResolvedValue({ data: [TOKEN] }) };
    render(<OpsShopConsent api={api} canEdit={false} shopId="s1" />);
    expect(await screen.findByText("1 nguồn đang kết nối")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tạo mã kết nối" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Thu hồi" })).toBeNull();
  });
});
