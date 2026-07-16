"use client";

import {
  useCallback,
  useRef,
  type ComponentPropsWithoutRef,
  type KeyboardEvent,
  type ReactNode,
} from "react";

export type SortDirection = "asc" | "desc" | "none";

export interface TableProps extends ComponentPropsWithoutRef<"table"> {
  children: ReactNode;
}

export function Table({ className, children, ...rest }: TableProps) {
  const classNames = ["juli-table", className].filter(Boolean).join(" ");

  return (
    <div className="juli-table-wrapper">
      <table className={classNames} {...rest}>
        {children}
      </table>
    </div>
  );
}

export interface TableCaptionProps extends ComponentPropsWithoutRef<"caption"> {
  children: ReactNode;
}

export function TableCaption({ className, children, ...rest }: TableCaptionProps) {
  const classNames = ["juli-table__caption", className]
    .filter(Boolean)
    .join(" ");

  return (
    <caption className={classNames} {...rest}>
      {children}
    </caption>
  );
}

export interface TableHeadProps {
  children: ReactNode;
}

export function TableHead({ children }: TableHeadProps) {
  return <thead className="juli-table__head">{children}</thead>;
}

export interface TableBodyProps {
  children: ReactNode;
  keyboardNav?: boolean;
}

export function TableBody({ children, keyboardNav = true }: TableBodyProps) {
  const bodyRef = useRef<HTMLTableSectionElement>(null);

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTableSectionElement>) => {
      if (!keyboardNav) {
        return;
      }

      const rows = bodyRef.current?.querySelectorAll<HTMLTableRowElement>(
        "tr.juli-table__row--focusable",
      );

      if (!rows?.length) {
        return;
      }

      const active = document.activeElement;
      const currentIndex = Array.from(rows).findIndex((row) => row === active);

      if (currentIndex === -1) {
        return;
      }

      if (event.key === "ArrowDown" && currentIndex < rows.length - 1) {
        event.preventDefault();
        rows[currentIndex + 1]?.focus();
      }

      if (event.key === "ArrowUp" && currentIndex > 0) {
        event.preventDefault();
        rows[currentIndex - 1]?.focus();
      }
    },
    [keyboardNav],
  );

  return (
    <tbody
      ref={bodyRef}
      className="juli-table__body"
      onKeyDown={handleKeyDown}
    >
      {children}
    </tbody>
  );
}

export interface TableRowProps extends ComponentPropsWithoutRef<"tr"> {
  children: ReactNode;
  focusable?: boolean;
}

export function TableRow({
  className,
  children,
  focusable = true,
  tabIndex,
  ...rest
}: TableRowProps) {
  const classNames = [
    "juli-table__row",
    focusable ? "juli-table__row--focusable" : null,
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <tr
      className={classNames}
      tabIndex={focusable ? (tabIndex ?? -1) : undefined}
      {...rest}
    >
      {children}
    </tr>
  );
}

export interface TableHeaderCellProps extends ComponentPropsWithoutRef<"th"> {
  children: ReactNode;
  onSort?: () => void;
  sortDirection?: SortDirection;
  sortable?: boolean;
}

export function TableHeaderCell({
  children,
  className,
  onSort,
  sortDirection = "none",
  sortable = false,
  ...rest
}: TableHeaderCellProps) {
  const classNames = ["juli-table__header", className]
    .filter(Boolean)
    .join(" ");

  if (sortable) {
    const sortLabel =
      typeof children === "string" ? children : "cột này";

    return (
      <th className={classNames} scope="col" {...rest}>
        <button
          aria-label={`Sắp xếp theo ${sortLabel}`}
          aria-sort={
            sortDirection === "none"
              ? "none"
              : sortDirection === "asc"
                ? "ascending"
                : "descending"
          }
          className="juli-table__sort"
          data-testid="table-sort-button"
          onClick={onSort}
          type="button"
        >
          <span>{children}</span>
          <span aria-hidden="true" className="juli-table__sort-icon">
            {sortDirection === "asc"
              ? "↑"
              : sortDirection === "desc"
                ? "↓"
                : "↕"}
          </span>
        </button>
      </th>
    );
  }

  return (
    <th className={classNames} scope="col" {...rest}>
      {children}
    </th>
  );
}

export interface TableCellProps extends ComponentPropsWithoutRef<"td"> {
  children: ReactNode;
  label?: string;
}

export function TableCell({
  className,
  children,
  label,
  ...rest
}: TableCellProps) {
  const classNames = ["juli-table__cell", className]
    .filter(Boolean)
    .join(" ");

  return (
    <td className={classNames} data-label={label} {...rest}>
      {children}
    </td>
  );
}

export interface TableEmptyProps {
  message?: string;
  title?: string;
}

export function TableEmpty({
  message = "Chưa có dữ liệu để hiển thị. Hãy thử lại sau khi có đơn hàng mới.",
  title = "Chưa có dữ liệu",
}: TableEmptyProps) {
  return (
    <tr className="juli-table__empty">
      <td colSpan={100}>
        <div className="juli-table__empty-state" data-testid="table-empty-state">
          <strong>{title}</strong>
          <p>{message}</p>
        </div>
      </td>
    </tr>
  );
}
