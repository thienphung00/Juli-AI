import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OpsApiError } from "../../../lib/ops/api";
import { OpsShopConsent } from "../ops-contract-shop";

/** Kết nối dữ liệu is on every shop. Contract shops are no longer created here. */

const TOKEN = {
  id: "t1",
  client_label: "Juli Connector",
  created_at: "2026-11-02T07:00:00Z",
  expires_at: "2027-01-31T07:00:00Z",
  last_used_at: null,
  revoked_at: null,
  active: true,
};

describe("Kết nối dữ liệu", () => {
  it("shows a one-use code after 'Tạo mã kết nối' and revokes a source", async () => {
    const api = {
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
    const api = { ingestTokens: vi.fn().mockResolvedValue({ data: [TOKEN] }) };
    render(<OpsShopConsent api={api} canEdit={false} shopId="s1" />);
    expect(await screen.findByText("1 nguồn đang kết nối")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tạo mã kết nối" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Thu hồi" })).toBeNull();
  });

  it("says when the shop has no data-use consent yet", async () => {
    const api = {
      createPairingCode: vi.fn().mockRejectedValue(new OpsApiError(409, "consent_required")),
      ingestTokens: vi.fn().mockResolvedValue({ data: [] }),
    };
    render(<OpsShopConsent api={api} canEdit shopId="s1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Tạo mã kết nối" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("chưa có đồng ý");
  });

  it("lists the readers that did not finish well: reader, short outcome, since", async () => {
    const api = {
      ingestTokens: vi.fn().mockResolvedValue({ data: [TOKEN] }),
      connectorProblems: vi.fn().mockResolvedValue({
        data: [
          { reader: "traffic", outcome: "blocked:password_recheck", since: "2026-11-18T03:00:00Z" },
          { reader: "orders", outcome: "partial:first_page", since: "2026-11-19T03:00:00Z" },
        ],
      }),
    };
    render(<OpsShopConsent api={api} canEdit={false} shopId="s1" />);
    const list = await screen.findByLabelText("Reader lỗi");
    expect(list).toHaveTextContent("traffic");
    expect(list).toHaveTextContent("Cần nhập lại mật khẩu");
    expect(list).toHaveTextContent("Đọc chưa đủ");
    expect(list).toHaveTextContent("orders");
  });

  it("shows no problem list when every reader is fine", async () => {
    const api = {
      ingestTokens: vi.fn().mockResolvedValue({ data: [TOKEN] }),
      connectorProblems: vi.fn().mockResolvedValue({ data: [] }),
    };
    render(<OpsShopConsent api={api} canEdit={false} shopId="s1" />);
    expect(await screen.findByText("1 nguồn đang kết nối")).toBeInTheDocument();
    expect(screen.queryByLabelText("Reader lỗi")).toBeNull();
  });
});
