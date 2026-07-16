import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProgressBar, RealEstimatedProgressBar } from "../progress-bar";
import { loadUiStyles } from "./test-utils";

const styles = loadUiStyles();

describe("ProgressBar", () => {
  it("renders a labeled standard progress bar", () => {
    render(<ProgressBar label="Tiến độ quy trình" value={60} />);

    const bar = screen.getByRole("progressbar", { name: "Tiến độ quy trình" });

    expect(screen.getByText("Tiến độ quy trình")).toBeInTheDocument();
    expect(bar).toHaveAttribute("aria-valuenow", "60");
    expect(bar.querySelector(".juli-progress__fill")).toHaveStyle({
      width: "60%",
    });
  });

  it("clamps values to the 0-100 range", () => {
    render(<ProgressBar label="Tiến độ quy trình" value={140} />);

    expect(
      screen.getByRole("progressbar", { name: "Tiến độ quy trình" }),
    ).toHaveAttribute("aria-valuenow", "100");
  });

  it("renders real and estimated segments with a today marker", () => {
    render(
      <RealEstimatedProgressBar
        estimatedValue={25}
        label="Doanh thu thực tế và ước tính"
        realValue={45}
      />,
    );

    const bar = screen.getByRole("progressbar", {
      name: "Doanh thu thực tế và ước tính",
    });

    expect(bar.querySelector(".juli-progress__fill--real")).toHaveStyle({
      width: "45%",
    });
    expect(bar.querySelector(".juli-progress__fill--estimated")).toHaveStyle({
      left: "45%",
      width: "25%",
    });
    expect(bar.querySelector(".juli-progress__marker")).toBeInTheDocument();
  });

  it("uses theme tokens and disables estimated glow under reduced motion", () => {
    expect(styles).toContain("var(--juli-primary)");
    expect(styles).toContain("var(--juli-border)");
    expect(styles).toContain(".juli-progress__fill--estimated");
    expect(styles).toMatch(
      /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.juli-progress__fill--estimated[\s\S]*animation: none/,
    );
    expect(styles).not.toMatch(/\.juli-progress[\s\S]*#[0-9a-f]{3,8}/i);
  });
});
