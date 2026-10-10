import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AUTH_SESSION_STORAGE_KEY } from "../../../lib/supabase-auth";
import { OpsViewAs } from "../ops-view-as";
import { ME, SHOP_ID, VIEW_SESSION } from "./fixtures";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/ops",
  useSearchParams: () => new URLSearchParams(),
}));

function baseFetch() {
  return vi.fn(async (url: string) => {
    if (url.endsWith("/view/decisions")) return new Response(JSON.stringify({ data: [] }), { status: 200 });
    return new Response(JSON.stringify({ detail: "none" }), { status: 404 });
  });
}

beforeEach(() => {
  window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "t", tokenType: "bearer" }));
});

describe("Xem như shop (OpsViewAs.dc.html)", () => {
  it("opens read-only with the dark banner, logs the session, and switches to act mode", async () => {
    const viewSession = vi.fn(async () => VIEW_SESSION);
    const fetchStub = baseFetch();
    render(<OpsViewAs api={{ viewSession }} baseFetch={fetchStub as unknown as typeof fetch} me={ME} shopId={SHOP_ID} />);
    const banner = await screen.findByTestId("view-as-banner");
    await waitFor(() => expect(banner).toHaveTextContent("Đang xem như Mỹ phẩm Thảo Nhi · chỉ xem"));
    expect(banner).toHaveTextContent("Phiên xem được ghi nhật ký · không hiện dữ liệu người mua");
    expect(viewSession).toHaveBeenCalledWith(SHOP_ID, "view");
    expect(screen.getByTestId("seller-view")).toBeDisabled();
    expect(screen.getByTestId("write-note")).toHaveTextContent("Chỉ xem. Seller đã đồng ý cho đội ngũ làm thay (10/10/2026).");
    await waitFor(() => expect(fetchStub).toHaveBeenCalledWith(`/v1/ops/shops/${SHOP_ID}/view/decisions`, expect.anything()));
    fireEvent.click(screen.getByRole("button", { name: "Làm thay seller" }));
    await waitFor(() => expect(banner).toHaveAttribute("data-act", "true"));
    expect(viewSession).toHaveBeenLastCalledWith(SHOP_ID, "act");
    expect(banner).toHaveTextContent("Đang làm thay Mỹ phẩm Thảo Nhi · mọi thao tác được ghi nhật ký");
    expect(screen.getByTestId("seller-view")).not.toBeDisabled();
    expect(screen.getByTestId("write-note")).toHaveTextContent('Thao tác sẽ ghi "bởi thien.phung (Admin) thay seller"');
  });

  it("cannot act without the shop flag and the seller's consent", async () => {
    const viewSession = vi.fn(async () => ({ ...VIEW_SESSION, act_allowed: false, can_act: false, seller_consent_at: null }));
    render(<OpsViewAs api={{ viewSession }} baseFetch={baseFetch() as unknown as typeof fetch} me={ME} shopId={SHOP_ID} />);
    expect(await screen.findByRole("button", { name: "Làm thay seller" })).toBeDisabled();
    expect(screen.getByTestId("write-note")).toHaveTextContent("Chỉ xem.");
  });
});
