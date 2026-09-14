import { render, screen } from "@testing-library/react";
import { PrimaryNavigation } from "@juli/ui";
import { describe, expect, it } from "vitest";

import { demoDestinations } from "../lib/mock-data";

describe("four-destination shell navigation", () => {
  it("exposes exactly four ordered destinations and a non-color active state", () => {
    render(
      <PrimaryNavigation
        activePath="/analytics"
        destinations={demoDestinations}
        label="Điều hướng chính"
      />,
    );

    const navigation = screen.getByRole("navigation", {
      name: "Điều hướng chính",
    });
    const links = navigation.querySelectorAll("a");

    expect(links).toHaveLength(4);
    expect(Array.from(links, (link) => link.textContent)).toEqual([
      "⌂Trang chủ",
      "Quyết định",
      "Phân tích",
      "⚙Cài đặt",
    ]);
    expect(screen.getByRole("link", { name: "Phân tích" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("renders SVG icons for Decisions and Analytics — never their icon keys as text (#1903)", () => {
    render(
      <PrimaryNavigation
        activePath="/"
        destinations={demoDestinations}
        label="Điều hướng chính"
      />,
    );

    const navigation = screen.getByRole("navigation", {
      name: "Điều hướng chính",
    });

    expect(navigation.textContent).not.toMatch(/\bdecisions\b/);
    expect(navigation.textContent).not.toMatch(/\banalytics\b/);
    expect(
      screen.getByRole("link", { name: "Quyết định" }).querySelector("svg"),
    ).not.toBeNull();
    expect(
      screen.getByRole("link", { name: "Phân tích" }).querySelector("svg"),
    ).not.toBeNull();
  });
});
