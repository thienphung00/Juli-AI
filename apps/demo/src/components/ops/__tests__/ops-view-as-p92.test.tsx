import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AUTH_SESSION_STORAGE_KEY } from "../../../lib/supabase-auth";
import { OpsViewAs } from "../ops-view-as";
import { ME, SETTINGS, SHOP_ID } from "./fixtures";

/** P92: Loại trừ sản phẩm in "Xem như shop" (read-only) and the settings area of Ops. */

let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/ops",
  useSearchParams: () => new URLSearchParams(search),
}));

const SHOPEE_SESSION = { shop: { ...SETTINGS.shop, platform: "shopee" as const }, stage: "trial" as const, read_only: true as const };
const OPS = `/v1/ops/shops/${SHOP_ID}/shopee`;

beforeEach(() => {
  search = "";
  window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "t", tokenType: "bearer" }));
});

describe("Xem như shop: Loại trừ sản phẩm", () => {
  it("is a nav entry on a Shopee shop and shows the list read-only through the Ops builder base", async () => {
    search = "trang=loai-tru";
    const calls: { url: string; method: string }[] = [];
    const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, method: init?.method ?? "GET" });
      if (url === `${OPS}/exclusions`) {
        return new Response(
          JSON.stringify({
            excluded: [{ item_id: "17820466113", name: "Bình giữ nhiệt inox X", reason: "ngung_ban", reason_label: "Ngừng bán", set_at: "2026-10-28T10:15:00+07:00" }],
            count: 1,
            reasons: [{ key: "ngung_ban", label: "Ngừng bán" }],
          }),
          { status: 200 },
        );
      }
      return new Response("{}", { status: 404 });
    }) as unknown as typeof fetch;
    render(<OpsViewAs api={{ viewSession: async () => SHOPEE_SESSION }} baseFetch={fn} me={ME} shopId={SHOP_ID} />);
    expect(await screen.findByTestId("view-as-exclusions")).toBeInTheDocument();
    expect(await screen.findByTestId("sx-row-17820466113")).toHaveTextContent("Bình giữ nhiệt inox X");
    expect(screen.getByRole("button", { name: "Loại trừ" })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByTestId("sx-add")).toBeNull();
    expect(screen.queryByRole("button", { name: "Hoàn tác" })).toBeNull();
    await waitFor(() => expect(calls.some((c) => c.url === `${OPS}/exclusions`)).toBe(true));
    expect(calls.every((c) => c.method === "GET")).toBe(true);
  });
});
