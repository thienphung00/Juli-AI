import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AppNavigation } from "../components/app-shell/app-navigation";
import { APP_DESTINATIONS, SHOPEE_DESTINATIONS, destinationsFor } from "../lib/app-navigation";

/** ADR-120 decision 2: a Shopee shop's navigation, isolated so a TikTok shop keeps today's. */
describe("navigation for a Shopee shop", () => {
  it("lists Tổng quan / Phân tích / Sản phẩm / Quyết định and the four read-only pages, with no Trang chủ and no locked Juli", () => {
    render(<AppNavigation activePath="/tong-quan" platform="shopee" />);
    const nav = screen.getByRole("navigation", { name: "Điều hướng chính" });
    expect(within(nav).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Tổng quan",
      "Phân tích",
      "Sản phẩm",
      "Quyết định",
      "Từ khóa",
      "Quảng cáo",
      "Đơn hàng",
      "Luồng",
    ]);
    expect(nav).not.toHaveTextContent("Cài đặt");
    expect(screen.queryByTestId("nav-locked-juli")).toBeNull();
  });

  it("points at the Shopee routes", () => {
    render(<AppNavigation activePath="/tong-quan" platform="shopee" />);
    const nav = screen.getByRole("navigation", { name: "Điều hướng chính" });
    expect(within(nav).getByRole("link", { name: "Tổng quan" })).toHaveAttribute("href", "/tong-quan");
    expect(within(nav).getByRole("link", { name: "Phân tích" })).toHaveAttribute("href", "/phan-tich");
    expect(within(nav).getByRole("link", { name: "Sản phẩm" })).toHaveAttribute("href", "/san-pham");
    expect(within(nav).getByRole("link", { name: "Quyết định" })).toHaveAttribute("href", "/decisions");
    // P92 B-8: the four read-only pages from Ops.
    expect(within(nav).getByRole("link", { name: "Từ khóa" })).toHaveAttribute("href", "/tu-khoa");
    expect(within(nav).getByRole("link", { name: "Quảng cáo" })).toHaveAttribute("href", "/quang-cao");
    expect(within(nav).getByRole("link", { name: "Đơn hàng" })).toHaveAttribute("href", "/don-hang");
    expect(within(nav).getByRole("link", { name: "Luồng" })).toHaveAttribute("href", "/luong-san-pham");
    expect(within(nav).getByRole("list")).toHaveClass("app-nav__list--many");
  });

  it("marks the active destination; an old Xếp hạng link and a product page belong to their parents", () => {
    // P96b: Xếp hạng is Phân tích's product table (/xep-hang redirects to /phan-tich).
    const { rerender } = render(<AppNavigation activePath="/xep-hang" platform="shopee" />);
    expect(screen.getByRole("link", { name: "Phân tích" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Tổng quan" })).not.toHaveAttribute("aria-current");
    rerender(<AppNavigation activePath="/san-pham/BEP-S5" platform="shopee" />);
    expect(screen.getByRole("link", { name: "Sản phẩm" })).toHaveAttribute("aria-current", "page");
    rerender(<AppNavigation activePath="/don-hang" platform="shopee" />);
    expect(screen.getByRole("link", { name: "Đơn hàng" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Sản phẩm" })).not.toHaveAttribute("aria-current");
    rerender(<AppNavigation activePath="/decisions" platform="shopee" />);
    expect(screen.getByRole("link", { name: "Quyết định" })).toHaveAttribute("aria-current", "page");
  });

  it("a TikTok shop (and a caller that says nothing) keeps today's four destinations", () => {
    render(<AppNavigation activePath="/analytics" />);
    const nav = screen.getByRole("navigation", { name: "Điều hướng chính" });
    expect(within(nav).getAllByRole("listitem").map((li) => li.textContent?.replace(/Sắp có.*$/, ""))).toEqual(["Trang chủ", "Quyết định", "Phân tích", "Juli"]);
    expect(screen.getByTestId("nav-locked-juli")).toBeInTheDocument();
    expect(within(nav).getByRole("list")).not.toHaveClass("app-nav__list--many");
    expect(destinationsFor("tiktok")).toBe(APP_DESTINATIONS);
    expect(destinationsFor("shopee")).toBe(SHOPEE_DESTINATIONS);
  });
});
