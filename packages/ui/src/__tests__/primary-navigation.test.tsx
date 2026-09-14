import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { PrimaryNavigation } from "../primary-navigation";
import { isNavTabActive } from "../navigation-utils";
import { loadUiStyles } from "./test-utils";

const styles = loadUiStyles();

/** Mirrors `apps/demo/src/lib/mock-data.ts` `demoDestinations` — icon *names*
 * for Decisions/Analytics, literal glyphs for Home/Settings. The W6 gate walk
 * (#1903) saw the names rendered as raw English text beside the Vietnamese
 * labels, so this fixture must keep using names, not glyphs. */
const destinations = [
  { href: "/", label: "Trang chủ", icon: { glyph: "⌂" } },
  { href: "/decisions", label: "Quyết định", icon: "decisions" },
  { href: "/analytics", label: "Phân tích", icon: "analytics" },
  { href: "/settings", label: "Cài đặt", icon: { glyph: "⚙" } },
] as const;

describe("isNavTabActive", () => {
  it("marks the home route only on an exact match", () => {
    expect(isNavTabActive("/", "/")).toBe(true);
    expect(isNavTabActive("/analytics", "/")).toBe(false);
  });

  it("marks nested routes as active for their parent destination", () => {
    expect(isNavTabActive("/analytics/revenue", "/analytics")).toBe(true);
    expect(isNavTabActive("/decisions", "/analytics")).toBe(false);
  });
});

describe("PrimaryNavigation", () => {
  it("renders four Vietnamese destinations with the active route indicated", () => {
    render(
      <PrimaryNavigation
        activePath="/analytics/revenue"
        destinations={destinations}
        label="Điều hướng chính"
      />,
    );

    expect(screen.getByRole("link", { name: "Phân tích" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Trang chủ" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("renders icon names as SVG icons, never as raw English text (#1903)", () => {
    render(
      <PrimaryNavigation
        activePath="/decisions"
        destinations={destinations}
        label="Điều hướng chính"
      />,
    );

    const navigation = screen.getByRole("navigation", {
      name: "Điều hướng chính",
    });

    // The seller must never see the icon keys as words in the nav.
    expect(navigation.textContent).not.toMatch(/\bdecisions\b/);
    expect(navigation.textContent).not.toMatch(/\banalytics\b/);

    // Each name-carrying destination renders a real SVG icon instead.
    expect(
      screen.getByRole("link", { name: "Quyết định" }).querySelector("svg"),
    ).not.toBeNull();
    expect(
      screen.getByRole("link", { name: "Phân tích" }).querySelector("svg"),
    ).not.toBeNull();
  });

  it("still renders literal glyph icons for Home and Settings", () => {
    render(
      <PrimaryNavigation
        activePath="/"
        destinations={destinations}
        label="Điều hướng chính"
      />,
    );

    expect(
      screen.getByRole("link", { name: "Trang chủ" }).textContent,
    ).toContain("⌂");
    expect(
      screen.getByRole("link", { name: "Cài đặt" }).textContent,
    ).toContain("⚙");
  });

  it("is keyboard-operable across all destinations", async () => {
    const user = userEvent.setup();

    render(
      <PrimaryNavigation
        activePath="/"
        destinations={destinations}
        label="Điều hướng chính"
      />,
    );

    await user.tab();
    expect(screen.getByRole("link", { name: "Trang chủ" })).toHaveFocus();

    await user.tab();
    expect(screen.getByRole("link", { name: "Quyết định" })).toHaveFocus();

    await user.tab();
    expect(screen.getByRole("link", { name: "Phân tích" })).toHaveFocus();

    await user.tab();
    expect(screen.getByRole("link", { name: "Cài đặt" })).toHaveFocus();
  });

  it("documents visible focus-visible styling and non-color active state", () => {
    expect(styles).toContain(".juli-primary-nav__link:focus-visible");
    expect(styles).toContain('.juli-primary-nav__link[aria-current="page"]');
    expect(styles).toContain("font-weight: 800");
  });
});
