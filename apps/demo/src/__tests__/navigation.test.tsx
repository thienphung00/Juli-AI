import { render, screen } from "@testing-library/react";
import { PrimaryNavigation } from "@juli/ui";
import { describe, expect, it } from "vitest";

const destinations = [
  { href: "/", label: "Trang chủ", icon: "⌂" },
  { href: "/decisions", label: "Quyết định", icon: "✓" },
  { href: "/analytics", label: "Phân tích", icon: "↗" },
  { href: "/settings", label: "Cài đặt", icon: "⚙" },
] as const;

describe("four-destination shell navigation", () => {
  it("exposes exactly four ordered destinations and a non-color active state", () => {
    render(
      <PrimaryNavigation
        activePath="/analytics"
        destinations={destinations}
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
      "✓Quyết định",
      "↗Phân tích",
      "⚙Cài đặt",
    ]);
    expect(screen.getByRole("link", { name: "Phân tích" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});
