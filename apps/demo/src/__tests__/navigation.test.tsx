import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AppNavigation } from "../components/app-shell/app-navigation";
import { APP_DESTINATIONS, JULI_LOCKED_HINT } from "../lib/app-navigation";

/**
 * ADR-109 decision 7 (AC-8.5): Trang chủ / Quyết định / Phân tích / Juli.
 * Cài đặt left the nav for the shop-avatar menu; Juli is shown but locked.
 * The rail (desktop) and the bottom bar (< 768px) are the SAME `<nav>` —
 * only CSS moves it — so this one render covers both.
 */
describe("app navigation — four destinations, Juli locked", () => {
  it("lists the four destinations in the video's order", () => {
    render(<AppNavigation activePath="/analytics" />);
    const nav = screen.getByRole("navigation", { name: "Điều hướng chính" });

    expect(within(nav).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Trang chủ",
      "Quyết định",
      "Phân tích",
      `Juli${JULI_LOCKED_HINT}`,
    ]);
    expect(APP_DESTINATIONS.map((d) => d.label)).toEqual([
      "Trang chủ",
      "Quyết định",
      "Phân tích",
      "Juli",
    ]);
    expect(nav).not.toHaveTextContent("Cài đặt");
  });

  it("navigates to three pages and marks the active one (pink tint via aria-current)", () => {
    render(<AppNavigation activePath="/analytics" />);
    const nav = screen.getByRole("navigation", { name: "Điều hướng chính" });

    expect(within(nav).getByRole("link", { name: "Trang chủ" })).toHaveAttribute("href", "/");
    expect(within(nav).getByRole("link", { name: "Quyết định" })).toHaveAttribute("href", "/decisions");
    const analytics = within(nav).getByRole("link", { name: "Phân tích" });
    expect(analytics).toHaveAttribute("href", "/analytics");
    expect(analytics).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Trang chủ" })).not.toHaveAttribute("aria-current");
  });

  it("shows Juli locked: aria-disabled, no href, a lock mark and the coming-soon tooltip", () => {
    render(<AppNavigation activePath="/" />);
    const juli = screen.getByTestId("nav-locked-juli");

    expect(juli).toHaveAttribute("role", "link");
    expect(juli).toHaveAttribute("aria-disabled", "true");
    expect(juli).not.toHaveAttribute("href");
    expect(juli.closest("a")).toBeNull();
    expect(juli).toHaveAttribute("title", JULI_LOCKED_HINT);
    expect(JULI_LOCKED_HINT).toBe("Sắp có: nhật ký 24 giờ");
    expect(juli).toHaveAccessibleName("Juli");
    expect(juli).toHaveAccessibleDescription(JULI_LOCKED_HINT);
    expect(juli.querySelector(".app-nav__lock")).not.toBeNull();
  });

  it("renders an SVG icon for every destination, never an icon key as text (#1903)", () => {
    render(<AppNavigation activePath="/" />);
    const nav = screen.getByRole("navigation", { name: "Điều hướng chính" });

    expect(nav.querySelectorAll(".app-nav__icon")).toHaveLength(4);
    expect(nav.textContent).not.toMatch(/\b(home|decisions|analytics)\b/);
  });

  it("keeps the Juli. wordmark outside the nav, linking Home", () => {
    render(<AppNavigation activePath="/" />);
    expect(screen.getByRole("link", { name: "Juli — Trang chủ" })).toHaveAttribute("href", "/");
    const nav = screen.getByRole("navigation", { name: "Điều hướng chính" });
    expect(within(nav).queryByRole("link", { name: "Juli — Trang chủ" })).toBeNull();
  });
});
