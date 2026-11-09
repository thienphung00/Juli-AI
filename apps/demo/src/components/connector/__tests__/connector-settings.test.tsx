import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SettingsTabs } from "../../quyet-dinh/settings-rules";
import { ConnectorSettings } from "../connector-settings";

/** P96 (owner, 2026-11-06): the seller pairs their own Chrome — "Mã kết nối" in Cài đặt. */

const FAKE_CODE = "AAAAA-BBBBB"; // placeholder, not a real pairing code

function fakeFetch(tokens: unknown[] = []) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    if (url === "/v1/ingest/pairing-codes" && method === "POST") {
      return new Response(JSON.stringify({ code: FAKE_CODE, expires_at: "2026-11-06T04:10:00Z", ttl_seconds: 600 }), { status: 201 });
    }
    if (url === "/v1/ingest/tokens" && method === "GET") return new Response(JSON.stringify({ data: tokens }), { status: 200 });
    if (url.startsWith("/v1/ingest/tokens/") && method === "DELETE") return new Response(null, { status: 204 });
    return new Response("{}", { status: 404 });
  });
}

describe("Cài đặt › Juli Connector", () => {
  it("issues a one-time code with the shop header and shows the steps", async () => {
    const fetchImpl = fakeFetch();
    render(<ConnectorSettings auth={{ token: "t", shopId: "s1", fetchImpl: fetchImpl as unknown as typeof fetch }} shopName="ORY" />);
    fireEvent.click(await screen.findByRole("button", { name: "Tạo mã kết nối" }));
    expect(await screen.findByLabelText("Mã kết nối")).toHaveTextContent(FAKE_CODE);
    expect(screen.getByText(/dùng một lần, hết hạn sau 10 phút/)).toBeInTheDocument();
    expect(screen.getByText(/Mở Seller Centre/)).toBeInTheDocument();
    const post = (fetchImpl.mock.calls as unknown as [string, RequestInit][]).find(([u, i]) => u === "/v1/ingest/pairing-codes" && i?.method === "POST")!;
    const headers = new Headers(post[1].headers);
    expect(headers.get("Authorization")).toBe("Bearer t");
    expect(headers.get("X-Shop-Id")).toBe("s1");
  });

  it("lists connected browsers and revokes one", async () => {
    const fetchImpl = fakeFetch([
      { id: "tk1", client_label: "Chrome · máy văn phòng", last_used_at: "2026-11-06T03:00:00Z", active: true },
      { id: "tk2", client_label: "cũ", last_used_at: null, active: false },
    ]);
    render(<ConnectorSettings auth={{ token: "t", shopId: "s1", fetchImpl: fetchImpl as unknown as typeof fetch }} shopName="ORY" />);
    expect(await screen.findByText("Chrome · máy văn phòng")).toBeInTheDocument();
    expect(screen.queryByText("cũ")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Ngắt kết nối" }));
    await waitFor(() =>
      expect((fetchImpl.mock.calls as unknown as [string, RequestInit][]).some(([u, i]) => u === "/v1/ingest/tokens/tk1" && i?.method === "DELETE")).toBe(true),
    );
  });

  it("the tab exists only for a Shopee shop", () => {
    const { rerender } = render(<SettingsTabs active="rules" onChange={vi.fn()} />);
    expect(screen.queryByRole("tab", { name: "Juli Connector" })).toBeNull();
    rerender(<SettingsTabs active="rules" onChange={vi.fn()} showConnector />);
    expect(screen.getByRole("tab", { name: "Juli Connector" })).toBeInTheDocument();
  });
});
