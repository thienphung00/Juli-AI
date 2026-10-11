import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OpsOverview } from "../ops-overview";
import { OpsSimulatePicker } from "../ops-simulate-picker";
import { ME, OVERVIEW, SHOP_ID } from "./fixtures";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }), usePathname: () => "/ops" }));

describe("Mô phỏng tab (owner, 2026-10-11)", () => {
  it("is in the main Ops nav and lists connected shops linking to their simulation", async () => {
    render(<OpsSimulatePicker me={ME} api={{ overview: () => Promise.resolve(OVERVIEW) }} />);
    expect(screen.getByText("Mô phỏng", { selector: "[aria-current='page']" })).toBeInTheDocument();
    const links = await screen.findAllByTestId("simulate-shop-link");
    expect(links[0]).toHaveAttribute("href", `/ops/shops/${SHOP_ID}/mo-phong`);
  });

  it("every overview row has a Mô phỏng link", async () => {
    render(<OpsOverview me={ME} api={{ overview: () => Promise.resolve(OVERVIEW), disconnect: vi.fn() }} />);
    const link = (await screen.findAllByRole("link", { name: "Mô phỏng" })).find((a) => a.getAttribute("href")?.endsWith("/mo-phong"));
    expect(link).toBeDefined();
    expect(screen.getAllByRole("link", { name: "Mô phỏng" }).some((a) => a.getAttribute("href") === "/ops/mo-phong")).toBe(true);
  });
});
