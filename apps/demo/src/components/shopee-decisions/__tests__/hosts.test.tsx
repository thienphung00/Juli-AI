import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { detailOf, summaryOf, voucherCard } from "../../../lib/shopee-decisions/__tests__/fixtures";
import { OpsViewAsShopeeDecisions, SellerShopeeDecisions } from "../hosts";

function api() {
  const seen: string[] = [];
  const f = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    seen.push(`${init?.method ?? "GET"} ${url}`);
    if (url.includes("/recommendations?queue=all")) return new Response(JSON.stringify({ platform: "shopee", xep_theo: "diem", cards: [summaryOf(voucherCard())], counts: { family: {}, section: {}, total: 1 } }));
    return new Response(JSON.stringify(detailOf(voucherCard())));
  }) as unknown as typeof fetch;
  return { f, seen };
}

describe("hosts", () => {
  it("seller /decisions: lists through the demo base with the shop header", async () => {
    const { f, seen } = api();
    render(<SellerShopeeDecisions fetchImpl={f} params={new URLSearchParams()} shop={{ id: "s1", name: "Shop" }} token="tok" />);
    await screen.findByTestId("sq-card-card-voucher");
    // the plan is on by default: the list also asks for the draft plan's card count
    expect(seen).toEqual(["GET /v1/demo/shopee/recommendations?queue=all", "GET /v1/demo/shopee/recommendations/plan"]);
    expect((f as unknown as ReturnType<typeof vi.fn>).mock.calls[0]![1].headers).toMatchObject({ "X-Shop-Id": "s1" });
  });

  it("an analytics card link (?the=<id>) opens that card's detail", async () => {
    const { f, seen } = api();
    render(<SellerShopeeDecisions fetchImpl={f} params={new URLSearchParams("the=card-voucher&from=phan-tich")} shop={{ id: "s1", name: "Shop" }} token="tok" />);
    await screen.findByTestId("sd-card-page");
    await waitFor(() => expect(seen).toContain("GET /v1/demo/shopee/recommendations/card-voucher"));
    expect(await screen.findByRole("link", { name: "Về Phân tích" })).toHaveAttribute("href", "/phan-tich");
  });

  it("Ops view-as: ops base, read-only, links stay inside view-as", async () => {
    window.sessionStorage.setItem("juli_demo_auth_session", JSON.stringify({ accessToken: "ops-tok", tokenType: "bearer" }));
    const { f, seen } = api();
    render(<OpsViewAsShopeeDecisions fetchImpl={f} params={new URLSearchParams()} shopId="abc" />);
    const row = await screen.findByTestId("sq-card-card-voucher");
    // "Xem như shop" reads the cards as the seller gets them: no unsent drafts
    expect(seen).toEqual(["GET /v1/ops/shops/abc/shopee/recommendations?queue=all&audience=seller"]);
    expect(row.querySelector("a")).toHaveAttribute("href", "/ops/shops/abc/xem?trang=quyet-dinh&the=card-voucher&from=quyet-dinh");
    expect(screen.getByText(/Chế độ xem/)).toBeInTheDocument();
  });
});
