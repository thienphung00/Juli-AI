import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  LoadingIndicator,
  LoadingSkeleton,
  LoadingSpinner,
} from "../loading-indicator";
import { loadUiStyles } from "./test-utils";

const styles = loadUiStyles();

describe("LoadingSpinner", () => {
  it("announces loading state through a live region with Vietnamese copy", () => {
    render(<LoadingSpinner />);

    const status = screen.getByRole("status");

    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText("Đang tải")).toHaveClass("juli-sr-only");
    expect(status.querySelector(".juli-spinner")).toBeInTheDocument();
  });

  it("supports the inline spinner variant for button-sized actions", () => {
    render(<LoadingSpinner size="inline" />);

    expect(screen.getByRole("status").querySelector(".juli-spinner--inline")).toBeInTheDocument();
  });

  it("accepts a custom accessible label", () => {
    render(<LoadingSpinner label="Đang phê duyệt đề xuất" />);

    expect(screen.getByText("Đang phê duyệt đề xuất")).toBeInTheDocument();
  });
});

describe("LoadingSkeleton", () => {
  it("renders a shape-matching skeleton placeholder", () => {
    render(
      <LoadingSkeleton
        className="juli-skeleton--card"
        data-testid="decisions-skeleton"
      />,
    );

    const skeleton = screen.getByTestId("decisions-skeleton");

    expect(skeleton).toHaveClass("juli-skeleton");
    expect(skeleton).toHaveClass("juli-skeleton--card");
    expect(skeleton).toHaveAttribute("aria-hidden", "true");
  });
});

describe("LoadingIndicator", () => {
  it("routes to spinner or skeleton variants", () => {
    const { rerender } = render(
      <LoadingIndicator label="Đang tải" variant="spinner" />,
    );

    expect(screen.getByRole("status")).toBeInTheDocument();

    rerender(
      <LoadingIndicator
        className="juli-skeleton--tile"
        data-testid="metric-skeleton"
        variant="skeleton"
      />,
    );

    expect(screen.getByTestId("metric-skeleton")).toHaveClass("juli-skeleton");
  });

  it("reuses spinner motion tokens and honors reduced motion in CSS", () => {
    expect(styles).toContain(".juli-spinner");
    expect(styles).toContain("animation: juli-spinner-spin 0.7s linear infinite");
    expect(styles).toContain("var(--juli-primary)");
    expect(styles).toContain("var(--juli-border)");
    expect(styles).toContain(".juli-skeleton");
    expect(styles).toMatch(
      /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.juli-spinner[\s\S]*animation: juli-spinner-pulse/,
    );
    expect(styles).toMatch(
      /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.juli-skeleton[\s\S]*animation: none/,
    );
    expect(styles).not.toMatch(/\.juli-spinner[\s\S]*#[0-9a-f]{3,8}/i);
  });
});
