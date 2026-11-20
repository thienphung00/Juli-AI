import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AppNavigation } from "../components/app-shell/app-navigation";
import { APP_DESTINATIONS, SHOPEE_DESTINATIONS, destinationsFor } from "../lib/app-navigation";

/** ADR-120 decision 2 + one rail (owner, 2026-11-19): a Shopee shop's navigation and routes. */
describe("navigation for a Shopee shop", () => {
  it("lists Tổng quan / Phân tích / Quyết định / Dữ liệu shop, with no Trang chủ and no locked Juli", () => {
    render(<AppNavigation activePath="/tong-quan" platform="shopee" />);
    const nav = screen.getByRole("navigation", { name: "Điều hướng chính" });
    expect(within(nav).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Tổng quan", "Phân tích", "Quyết định", "Dữ liệu shop"]);
    expect(nav).not.toHaveTextContent("Cài đặt");
    expect(screen.queryByTestId("nav-locked-juli")).toBeNull();
  });

  it("points at the Shopee routes", () => {
    render(<AppNavigation activePath="/tong-quan" platform="shopee" />);
    const nav = screen.getByRole("navigation", { name: "Điều hướng chính" });
    expect(within(nav).getByRole("link", { name: "Tổng quan" })).toHaveAttribute("href", "/tong-quan");
    expect(within(nav).getByRole("link", { name: "Phân tích" })).toHaveAttribute("href", "/phan-tich");
    expect(within(nav).getByRole("link", { name: "Quyết định" })).toHaveAttribute("href", "/decisions");
    expect(within(nav).getByRole("link", { name: "Dữ liệu shop" })).toHaveAttribute("href", "/san-pham");
  });

  it("marks the active destination; Xếp hạng belongs to Phân tích and every Dữ liệu shop route to Dữ liệu shop", () => {
    const { rerender } = render(<AppNavigation activePath="/xep-hang" platform="shopee" />);
    expect(screen.getByRole("link", { name: "Phân tích" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Tổng quan" })).not.toHaveAttribute("aria-current");
    for (const path of ["/san-pham", "/san-pham/BEP-S5", "/tu-khoa", "/quang-cao", "/don-hang", "/luong-san-pham"]) {
      rerender(<AppNavigation activePath={path} platform="shopee" />);
      expect(screen.getByRole("link", { name: "Dữ liệu shop" })).toHaveAttribute("aria-current", "page");
      expect(screen.getByRole("link", { name: "Quyết định" })).not.toHaveAttribute("aria-current");
    }
    rerender(<AppNavigation activePath="/decisions" platform="shopee" />);
    expect(screen.getByRole("link", { name: "Quyết định" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Dữ liệu shop" })).not.toHaveAttribute("aria-current");
  });

  it("a TikTok shop (and a caller that says nothing) gets the same rail without Dữ liệu shop", () => {
    render(<AppNavigation activePath="/analytics" />);
    const nav = screen.getByRole("navigation", { name: "Điều hướng chính" });
    expect(within(nav).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Tổng quan", "Phân tích", "Quyết định"]);
    expect(screen.queryByTestId("nav-locked-juli")).toBeNull();
    expect(within(nav).getByRole("list")).not.toHaveClass("app-nav__list--many");
    expect(destinationsFor("tiktok")).toBe(APP_DESTINATIONS);
    expect(destinationsFor("shopee")).toBe(SHOPEE_DESTINATIONS);
  });
});
