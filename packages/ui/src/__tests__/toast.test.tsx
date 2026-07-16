import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Toast, ToastViewport, type ToastItem } from "../toast";
import { loadUiStyles } from "./test-utils";

const styles = loadUiStyles();

const successToast: ToastItem = {
  id: "toast-1",
  message: "Đã phê duyệt đề xuất.",
  variant: "success",
};

const errorToast: ToastItem = {
  id: "toast-2",
  message: "Không thể lưu thay đổi. Vui lòng thử lại.",
  variant: "error",
};

describe("Toast", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders Vietnamese success copy with polite aria-live", () => {
    render(<Toast {...successToast} onDismiss={vi.fn()} />);

    const toast = screen.getByRole("status");

    expect(screen.getByText("Đã phê duyệt đề xuất.")).toBeInTheDocument();
    expect(toast).toHaveAttribute("aria-live", "polite");
    expect(toast).toHaveAttribute("data-testid", "juli-toast");
  });

  it("uses assertive aria-live for error toasts", () => {
    render(<Toast {...errorToast} onDismiss={vi.fn()} />);

    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "assertive");
    expect(screen.getByRole("status")).toHaveClass("juli-toast--error");
  });

  it("auto-dismisses success toasts after 4 seconds", () => {
    const onDismiss = vi.fn();

    render(<Toast {...successToast} onDismiss={onDismiss} />);

    act(() => {
      vi.advanceTimersByTime(3999);
    });
    expect(onDismiss).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(onDismiss).toHaveBeenCalledWith("toast-1");
  });

  it("auto-dismisses error and actionable toasts after 6 seconds", () => {
    const onDismiss = vi.fn();

    render(<Toast {...errorToast} onDismiss={onDismiss} />);

    act(() => {
      vi.advanceTimersByTime(5999);
    });
    expect(onDismiss).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(onDismiss).toHaveBeenCalledWith("toast-2");
  });

  it("pauses auto-dismiss while hovered or focused", () => {
    const onDismiss = vi.fn();

    render(<Toast {...successToast} onDismiss={onDismiss} />);

    const toast = screen.getByRole("status");

    fireEvent.mouseEnter(toast);

    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(onDismiss).not.toHaveBeenCalled();

    fireEvent.mouseLeave(toast);

    act(() => {
      vi.advanceTimersByTime(4000);
    });
    expect(onDismiss).toHaveBeenCalledWith("toast-1");
  });

  it("renders an optional undo action using the shared Button primitive", () => {
    const onAction = vi.fn();

    render(
      <Toast
        {...successToast}
        action={{ label: "Hoàn tác", onClick: onAction }}
        onDismiss={vi.fn()}
        variant="actionable"
      />,
    );

    const undoButton = screen.getByRole("button", { name: "Hoàn tác" });

    expect(undoButton).toHaveClass("juli-btn");
    fireEvent.click(undoButton);
    expect(onAction).toHaveBeenCalledOnce();
  });
});

describe("ToastViewport", () => {
  it("shows at most two toasts and queues the rest", () => {
    const toasts: ToastItem[] = [
      { id: "1", message: "Thông báo 1", variant: "success" },
      { id: "2", message: "Thông báo 2", variant: "success" },
      { id: "3", message: "Thông báo 3", variant: "success" },
    ];

    render(<ToastViewport onDismiss={vi.fn()} toasts={toasts} />);

    expect(screen.getAllByTestId("juli-toast")).toHaveLength(2);
    expect(screen.getByText("Thông báo 1")).toBeInTheDocument();
    expect(screen.getByText("Thông báo 2")).toBeInTheDocument();
    expect(screen.queryByText("Thông báo 3")).not.toBeInTheDocument();
  });

  it("uses theme elevation tokens without hardcoded palette values", () => {
    expect(styles).toContain(".juli-toast");
    expect(styles).toContain("var(--juli-shadow-medium)");
    expect(styles).toContain(".juli-toast-viewport");
    expect(styles).toMatch(
      /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.juli-toast[\s\S]*animation: none/,
    );
    expect(styles).not.toMatch(/\.juli-toast[\s\S]*#[0-9a-f]{3,8}/i);
  });
});
