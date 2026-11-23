import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AppNavigation } from "../components/app-shell/app-navigation";
import { APP_DESTINATIONS, SHOPEE_DESTINATIONS, TIKTOK_DESTINATIONS } from "../lib/app-navigation";

/**
 * One rail for TikTok Shop and Shopee (owner, 2026-11-19): the same labels in the same order;
 * only the routes differ. The rail (desktop) and the bottom bar (< 768px) are the SAME `<nav>` —
 * only CSS moves it — so this one render covers both.
 */
describe("app navigation — a TikTok shop", () => {
  it("lists Tổng quan / Phân tích / Quyết định, the Shopee order, without Cài đặt", () => {
    render(<AppNavigation activePath="/analytics" />);
    const nav = screen.getByRole("navigation", { name: "Điều hướng chính" });

    expect(within(nav).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Tổng quan", "Phân tích", "Quyết định"]);
    expect(nav).not.toHaveTextContent("Cài đặt");
    expect(nav).not.toHaveTextContent("Trang chủ");
  });

  it("uses the Shopee rail's labels and order, minus the entries TikTok has no page for yet", () => {
    const shopee = SHOPEE_DESTINATIONS.map((d) => d.label);
    const tiktok = TIKTOK_DESTINATIONS.map((d) => d.label);
    expect(tiktok).toEqual(shopee.filter((label) => tiktok.includes(label)));
    expect(shopee.filter((label) => !tiktok.includes(label))).toEqual(["Dữ liệu shop"]);
  });

  it("navigates a TikTok shop to the shared screens and marks the active one (pink tint via aria-current)", () => {
    render(<AppNavigation activePath="/phan-tich" />);
    const nav = screen.getByRole("navigation", { name: "Điều hướng chính" });

    expect(within(nav).getByRole("link", { name: "Tổng quan" })).toHaveAttribute("href", "/tong-quan");
    expect(within(nav).getByRole("link", { name: "Quyết định" })).toHaveAttribute("href", "/decisions");
    const analytics = within(nav).getByRole("link", { name: "Phân tích" });
    expect(analytics).toHaveAttribute("href", "/phan-tich");
    expect(analytics).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Tổng quan" })).not.toHaveAttribute("aria-current");
  });

  it("W3 U-4: the ADR-108 rail (Trang chủ /, Phân tích /analytics) stays reachable behind the one switch", () => {
    render(<AppNavigation activePath="/analytics" tiktokLegacy />);
    const nav = screen.getByRole("navigation", { name: "Điều hướng chính" });
    expect(within(nav).getByRole("link", { name: "Tổng quan" })).toHaveAttribute("href", "/");
    const analytics = within(nav).getByRole("link", { name: "Phân tích" });
    expect(analytics).toHaveAttribute("href", "/analytics");
    expect(analytics).toHaveAttribute("aria-current", "page");
    expect(APP_DESTINATIONS.map((d) => d.href)).toEqual(["/", "/analytics", "/decisions"]);
  });

  it("has no locked entry, and no Juli entry unless the shop has the tab enabled", () => {
    render(<AppNavigation activePath="/" />);
    const nav = screen.getByRole("navigation", { name: "Điều hướng chính" });
    expect(screen.queryByTestId("nav-locked-juli")).toBeNull();
    expect(within(nav).queryByRole("link", { name: "Juli" })).toBeNull();
    expect(APP_DESTINATIONS.some((d) => d.locked)).toBe(false);
  });

  it("shows Juli 4th (href /juli) when enabled: Tổng quan / Phân tích / Quyết định / Juli", () => {
    render(<AppNavigation activePath="/juli" juliEnabled />);
    const nav = screen.getByRole("navigation", { name: "Điều hướng chính" });
    expect(within(nav).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Tổng quan", "Phân tích", "Quyết định", "Juli"]);
    const juli = within(nav).getByRole("link", { name: "Juli" });
    expect(juli).toHaveAttribute("href", "/juli");
    expect(juli).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("list")).not.toHaveClass("app-nav__list--many");
  });

  it("renders an SVG icon for every destination, never an icon key as text (#1903)", () => {
    render(<AppNavigation activePath="/" />);
    const nav = screen.getByRole("navigation", { name: "Điều hướng chính" });

    expect(nav.querySelectorAll(".app-nav__icon")).toHaveLength(3);
    expect(nav.textContent).not.toMatch(/\b(overview|decisions|analytics)\b/);
  });

  it("keeps the Juli. wordmark outside the nav, linking Home", () => {
    render(<AppNavigation activePath="/" />);
    expect(screen.getByRole("link", { name: "Juli: Trang chủ" })).toHaveAttribute("href", "/");
    const nav = screen.getByRole("navigation", { name: "Điều hướng chính" });
    expect(within(nav).queryByRole("link", { name: "Juli: Trang chủ" })).toBeNull();
  });
});
