import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { Badge } from "../badge";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableEmpty,
  TableHead,
  TableHeaderCell,
  TableRow,
  type SortDirection,
} from "../table";
import { loadUiStyles, loadUiStyleRules } from "./test-utils";

const styles = loadUiStyles();
const styleRules = loadUiStyleRules();

const rows = [
  {
    id: "DH-001",
    status: "Đang xử lý",
    total: "1.250.000 ₫",
  },
  {
    id: "DH-002",
    status: "Hoàn tất",
    total: "890.000 ₫",
  },
];

function OrdersTableFixture({
  sortDirection = "none" as SortDirection,
  onSort = vi.fn(),
  empty = false,
}: {
  empty?: boolean;
  onSort?: () => void;
  sortDirection?: SortDirection;
}) {
  return (
    <Table aria-label="Danh sách đơn hàng">
      <TableCaption>Đơn hàng đang thực hiện</TableCaption>
      <TableHead>
        <TableRow focusable={false}>
          <TableHeaderCell
            onSort={onSort}
            sortDirection={sortDirection}
            sortable
          >
            Mã đơn
          </TableHeaderCell>
          <TableHeaderCell>Trạng thái</TableHeaderCell>
          <TableHeaderCell>Tổng tiền</TableHeaderCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {empty ? (
          <TableEmpty />
        ) : (
          rows.map((row) => (
            <TableRow data-testid={`row-${row.id}`} key={row.id}>
              <TableCell label="Mã đơn">{row.id}</TableCell>
              <TableCell label="Trạng thái">
                <Badge variant="info">{row.status}</Badge>
              </TableCell>
              <TableCell label="Tổng tiền">{row.total}</TableCell>
            </TableRow>
          ))
        )}
      </TableBody>
    </Table>
  );
}

describe("Table", () => {
  it("renders labelled columns with Vietnamese copy and status badges", () => {
    render(<OrdersTableFixture />);

    expect(
      screen.getByRole("table", { name: "Danh sách đơn hàng" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Đơn hàng đang thực hiện")).toHaveClass(
      "juli-table__caption",
    );
    expect(screen.getByRole("columnheader", { name: /Mã đơn/ })).toBeInTheDocument();
    expect(screen.getByText("DH-001")).toBeInTheDocument();
    expect(screen.getByText("Đang xử lý")).toBeInTheDocument();
  });

  it("exposes sortable headers with aria-sort", async () => {
    const user = userEvent.setup();
    const onSort = vi.fn();

    render(<OrdersTableFixture onSort={onSort} sortDirection="asc" />);

    const sortButton = screen.getByRole("button", { name: "Sắp xếp theo Mã đơn" });

    expect(sortButton).toHaveAttribute("aria-sort", "ascending");

    await user.click(sortButton);

    expect(onSort).toHaveBeenCalledOnce();
  });

  it("navigates focusable rows with arrow keys", async () => {
    const user = userEvent.setup();

    render(<OrdersTableFixture />);

    const firstRow = screen.getByTestId("row-DH-001");
    const secondRow = screen.getByTestId("row-DH-002");

    firstRow.focus();
    await user.keyboard("{ArrowDown}");

    expect(secondRow).toHaveFocus();

    await user.keyboard("{ArrowUp}");

    expect(firstRow).toHaveFocus();
  });

  it("renders an empty state instead of a bare no-rows message", () => {
    render(<OrdersTableFixture empty />);

    expect(screen.getByTestId("table-empty-state")).toBeInTheDocument();
    expect(screen.getByText("Chưa có dữ liệu")).toBeInTheDocument();
    expect(
      screen.getByText(/Chưa có dữ liệu để hiển thị/),
    ).toBeInTheDocument();
  });

  it("preserves data-label attributes for responsive card collapse", () => {
    render(<OrdersTableFixture />);

    expect(screen.getByText("DH-001").closest("td")).toHaveAttribute(
      "data-label",
      "Mã đơn",
    );
  });

  it("documents row height, dividers, sort control, and focus-visible styles in CSS", () => {
    expect(styles).toContain(".juli-table__row");
    expect(styles).toContain("min-height: var(--juli-touch-target)");
    expect(styles).toContain(".juli-table__sort");
    expect(styles).toContain(".juli-table__sort:focus-visible");
    expect(styles).toContain(".juli-table__row--focusable:focus-visible");
    expect(styles).toContain(".juli-table__empty-state");
    expect(styles).toContain("@media (max-width: 56rem)");
    expect(styleRules).not.toMatch(/#[0-9a-f]{3,8}/i);
  });
});
