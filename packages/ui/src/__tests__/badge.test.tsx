import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Badge, ConfidenceBadge } from "../badge";
import { loadUiStyles } from "./test-utils";

const styles = loadUiStyles();

describe("Badge", () => {
  it("renders semantic variants with Vietnamese labels", () => {
    render(
      <>
        <Badge variant="success">Tăng trưởng</Badge>
        <Badge variant="destructive">Từ chối</Badge>
        <Badge variant="warning">Cần chú ý</Badge>
        <Badge variant="info">Gợi ý Juli</Badge>
        <Badge variant="live">Đang thực hiện</Badge>
      </>,
    );

    expect(screen.getByText("Tăng trưởng")).toHaveClass("juli-badge--success");
    expect(screen.getByText("Từ chối")).toHaveClass("juli-badge--destructive");
    expect(screen.getByText("Cần chú ý")).toHaveClass("juli-badge--warning");
    expect(screen.getByText("Gợi ý Juli")).toHaveClass("juli-badge--info");
    expect(screen.getByText("Đang thực hiện")).toHaveClass("juli-badge--live");
  });

  it("renders confidence badges with Vietnamese text labels", () => {
    render(
      <>
        <ConfidenceBadge level="high" />
        <ConfidenceBadge level="medium" />
        <ConfidenceBadge level="low" />
      </>,
    );

    expect(screen.getByText("Độ tin cậy: Cao")).toBeInTheDocument();
    expect(screen.getByText("Độ tin cậy: Trung bình")).toBeInTheDocument();
    expect(screen.getByText("Độ tin cậy: Thấp")).toBeInTheDocument();
    expect(screen.queryByText(/Confidence/i)).not.toBeInTheDocument();
  });

  it("uses theme tokens and disables live pulse under reduced motion", () => {
    expect(styles).toContain("var(--juli-success-tint)");
    expect(styles).toContain("var(--juli-info-tint)");
    expect(styles).toContain(".juli-badge--live::before");
    expect(styles).toMatch(
      /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.juli-badge--live::before[\s\S]*animation: none/,
    );
  });
});
