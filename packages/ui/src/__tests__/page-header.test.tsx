import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PageHeader } from "../page-header";
import { loadUiStyles } from "./test-utils";

const styles = loadUiStyles();

describe("PageHeader", () => {
  it("renders a sticky banner with Vietnamese title and subtitle", () => {
    render(
      <PageHeader
        subtitle="Theo dõi hiệu suất cửa hàng"
        title="Phân tích"
      />,
    );

    const header = screen.getByRole("banner");

    expect(header).toHaveClass("juli-page-header");
    expect(screen.getByRole("heading", { name: "Phân tích" })).toBeInTheDocument();
    expect(
      screen.getByText("Theo dõi hiệu suất cửa hàng"),
    ).toBeInTheDocument();
  });

  it("prefers shop metadata over subtitle when both are provided", () => {
    render(
      <PageHeader
        shopName="Cửa hàng Juli"
        shopStatus="Đang hoạt động"
        subtitle="Theo dõi hiệu suất cửa hàng"
        title="Trang chủ"
      />,
    );

    expect(screen.getByText("Cửa hàng Juli")).toBeInTheDocument();
    expect(screen.getByText("Đang hoạt động")).toBeInTheDocument();
    expect(
      screen.queryByText("Theo dõi hiệu suất cửa hàng"),
    ).not.toBeInTheDocument();
  });

  it("documents glass blur styling for scrolled content", () => {
    expect(styles).toContain(".juli-page-header");
    expect(styles).toContain("backdrop-filter");
  });
});
