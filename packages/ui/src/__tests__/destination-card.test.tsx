import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DestinationCard } from "../destination-card";
import { DestinationIcon } from "../destination-icons";
import { loadUiStyles } from "./test-utils";

const styles = loadUiStyles();

describe("DestinationCard", () => {
  it("renders a Lucide-backed destination icon with token-aligned styling", () => {
    render(
      <DestinationCard
        actionLabel="Mở trang"
        description="Xem các đề xuất rõ ràng."
        eyebrow="Bạn là người quyết định"
        href="/decisions"
        icon={<DestinationIcon name="decisions" />}
        title="Quyết định"
      />,
    );

    const link = screen.getByRole("link", { name: /Quyết định/ });
    const icon = link.querySelector(".juli-destination-card__icon svg");

    expect(icon).toBeInTheDocument();
    expect(icon).toHaveClass("juli-destination-icon");
    expect(styles).toContain(".juli-destination-icon");
    expect(styles).toContain("color: var(--juli-primary-text)");
  });

  it("supports analytics and decisions icon variants", () => {
    render(
      <>
        <DestinationIcon name="decisions" />
        <DestinationIcon name="analytics" />
      </>,
    );

    const icons = document.querySelectorAll(".juli-destination-icon");

    expect(icons).toHaveLength(2);
    expect(icons[0]).toHaveAttribute("aria-hidden", "true");
    expect(icons[1]).toHaveAttribute("aria-hidden", "true");
  });
});
