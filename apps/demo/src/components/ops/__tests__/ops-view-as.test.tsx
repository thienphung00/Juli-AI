import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AUTH_SESSION_STORAGE_KEY } from "../../../lib/supabase-auth";
import { OpsViewAs } from "../ops-view-as";
import { ME, SHOP_ID, VIEW_SESSION } from "./fixtures";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/ops",
  useSearchParams: () => new URLSearchParams(),
}));

beforeEach(() => {
  window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "t", tokenType: "bearer" }));
});

describe("Xem như shop (OpsViewAs.dc.html, D25.3 amended: always read-only)", () => {
  it("shows the read-only banner, logs the session, disables every seller control and has no act toggle", async () => {
    const viewSession = vi.fn(async () => VIEW_SESSION);
    const fetchStub = vi.fn(async (url: string) =>
      url.endsWith("/view/decisions") || url.endsWith("/view/runs")
        ? new Response(JSON.stringify({ data: [] }), { status: 200 })
        : new Response(JSON.stringify({ detail: "none" }), { status: 404 }),
    );
    render(<OpsViewAs api={{ viewSession }} baseFetch={fetchStub as unknown as typeof fetch} me={ME} shopId={SHOP_ID} />);
    const banner = await screen.findByTestId("view-as-banner");
    await waitFor(() => expect(banner).toHaveTextContent("Đang xem như Mỹ phẩm Thảo Nhi · chỉ xem, không ghi được"));
    expect(banner).toHaveTextContent("Phiên xem được ghi nhật ký · không hiện dữ liệu người mua");
    expect(viewSession).toHaveBeenCalledWith(SHOP_ID, "view");
    expect(screen.queryByRole("button", { name: /Làm thay seller/ })).toBeNull();
    expect(screen.getByTestId("seller-view")).toBeDisabled();
    expect(screen.getByTestId("write-note")).toHaveTextContent("Mọi nút ghi đều khoá.");
    for (const name of ["Trang chủ", "Quyết định", "Phân tích", "Juli", "Quy tắc"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
    await waitFor(() => expect(fetchStub).toHaveBeenCalledWith(`/v1/ops/shops/${SHOP_ID}/view/decisions`, expect.anything()));
    const calls = fetchStub.mock.calls as unknown as [string, RequestInit | undefined][];
    expect(calls.every(([, init]) => (init?.method ?? "GET") === "GET")).toBe(true);
  });
});
