import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { PrimaryNavigation } from "../primary-navigation";
import { isNavTabActive } from "../navigation-utils";
import { loadUiStyles } from "./test-utils";

const styles = loadUiStyles();

const destinations = [
  { href: "/", label: "Trang chủ", icon: "⌂" },
  { href: "/decisions", label: "Quyết định", icon: "✓" },
  { href: "/analytics", label: "Phân tích", icon: "↗" },
  { href: "/settings", label: "Cài đặt", icon: "⚙" },
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
