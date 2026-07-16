import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  ConfirmDialog,
  Dialog,
  DialogBody,
  DialogClose,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../dialog";
import { Button } from "../button";
import { loadUiStyles, loadUiStyleRules } from "./test-utils";

const styles = loadUiStyles();
const styleRules = loadUiStyleRules();

function DialogFixture({
  initialOpen = true,
  onOpenChange = vi.fn(),
}: {
  initialOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const [open, setOpen] = useState(initialOpen);

  return (
    <>
      <button
        data-testid="dialog-trigger"
        onClick={() => {
          setOpen(true);
          onOpenChange(true);
        }}
        type="button"
      >
        Mở hộp thoại
      </button>
      <Dialog
        onOpenChange={(nextOpen) => {
          setOpen(nextOpen);
          onOpenChange(nextOpen);
        }}
        open={open}
      >
        <DialogHeader>
          <DialogTitle>Xác nhận hành động</DialogTitle>
          <DialogClose />
        </DialogHeader>
        <DialogBody>
          <DialogDescription>
            Hành động này không thể hoàn tác sau khi thực hiện.
          </DialogDescription>
        </DialogBody>
        <DialogFooter>
          <Button variant="secondary">Hủy</Button>
        </DialogFooter>
      </Dialog>
    </>
  );
}

describe("Dialog", () => {
  it("renders with aria-modal, labelled title, and Vietnamese close label", () => {
    render(<DialogFixture />);

    const dialog = screen.getByRole("dialog");

    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAttribute(
      "aria-labelledby",
      screen.getByRole("heading", { name: "Xác nhận hành động" }).id,
    );
    expect(screen.getByTestId("juli-dialog-close")).toHaveAttribute(
      "aria-label",
      "Đóng",
    );
  });

  it("closes via the close button", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();

    render(<DialogFixture onOpenChange={onOpenChange} />);

    await user.click(screen.getByTestId("juli-dialog-close"));

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes via backdrop click", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();

    render(<DialogFixture onOpenChange={onOpenChange} />);

    await user.click(screen.getByTestId("juli-dialog-backdrop"));

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes via Escape key", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();

    render(<DialogFixture onOpenChange={onOpenChange} />);

    await user.keyboard("{Escape}");

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders ConfirmDialog with Vietnamese action labels", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const onOpenChange = vi.fn();

    render(
      <ConfirmDialog
        confirmLabel="Tiếp tục"
        description="Bạn sẽ không thể hoàn tác bước này."
        onConfirm={onConfirm}
        onOpenChange={onOpenChange}
        open
        title="Xác nhận thực thi"
      />,
    );

    expect(screen.getByRole("heading", { name: "Xác nhận thực thi" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hủy" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tiếp tục" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Tiếp tục" }));

    expect(onConfirm).toHaveBeenCalledOnce();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("documents modal backdrop, shadow, and focus-visible styles in CSS", () => {
    expect(styles).toContain(".juli-dialog__backdrop");
    expect(styles).toContain(".juli-dialog__panel");
    expect(styles).toContain(".juli-dialog__close:focus-visible");
    expect(styles).toContain("box-shadow: var(--juli-shadow-medium)");
    expect(styleRules).not.toMatch(/#[0-9a-f]{3,8}/i);
  });
});
