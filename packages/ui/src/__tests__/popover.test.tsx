import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
  UnavailableKpiPopover,
} from "../popover";
import { loadUiStyles, loadUiStyleRules } from "./test-utils";

const styles = loadUiStyles();
const styleRules = loadUiStyleRules();

function PopoverFixture({
  initialOpen = false,
  onOpenChange = vi.fn(),
}: {
  initialOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const [open, setOpen] = useState(initialOpen);

  return (
    <Popover
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen);
        onOpenChange(nextOpen);
      }}
      open={open}
    >
      <PopoverTrigger label="Vì sao ROAS chưa khả dụng?">
        <span aria-hidden="true">ℹ️</span>
      </PopoverTrigger>
      <PopoverContent heading="ROAS chưa khả dụng">
        <p>Thiếu nguồn dữ liệu quảng cáo.</p>
      </PopoverContent>
    </Popover>
  );
}

describe("Popover", () => {
  it("exposes expanded state and Vietnamese trigger labeling", async () => {
    const user = userEvent.setup();

    render(<PopoverFixture />);

    const trigger = screen.getByTestId("juli-popover-trigger");

    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveAttribute(
      "aria-label",
      "Vì sao ROAS chưa khả dụng?",
    );

    await user.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("dialog")).toHaveAttribute(
      "aria-labelledby",
      screen.getByRole("heading", { name: "ROAS chưa khả dụng" }).id,
    );
    expect(screen.getByRole("dialog")).not.toHaveAttribute("aria-modal");
  });

  it("closes via the close button with Vietnamese aria-label", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();

    render(<PopoverFixture initialOpen onOpenChange={onOpenChange} />);

    const closeButton = screen.getByTestId("juli-popover-close");

    expect(closeButton).toHaveAttribute("aria-label", "Đóng giải thích");

    await user.click(closeButton);

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes via Escape key", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();

    render(<PopoverFixture initialOpen onOpenChange={onOpenChange} />);

    await user.keyboard("{Escape}");

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes via outside click", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();

    render(
      <div>
        <button data-testid="outside-target" type="button">
          Bên ngoài
        </button>
        <PopoverFixture initialOpen onOpenChange={onOpenChange} />
      </div>,
    );

    await user.click(screen.getByTestId("outside-target"));

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders UnavailableKpiPopover with source and activation copy", async () => {
    const user = userEvent.setup();

    function UnavailableFixture() {
      const [open, setOpen] = useState(false);

      return (
        <UnavailableKpiPopover
          activationRequirement="Kết nối tài khoản quảng cáo để kích hoạt ROAS."
          dataSource="TikTok Ads"
          kpiName="ROAS"
          onOpenChange={setOpen}
          open={open}
        />
      );
    }

    render(<UnavailableFixture />);

    const trigger = screen.getByRole("button", {
      name: "Vì sao ROAS chưa khả dụng?",
    });

    expect(trigger).toHaveClass("juli-popover__trigger");

    await user.click(trigger);

    expect(screen.getByRole("heading", { name: "ROAS chưa khả dụng" })).toBeInTheDocument();
    expect(screen.getByText(/TikTok Ads/)).toBeInTheDocument();
    expect(screen.getByText(/Kết nối tài khoản quảng cáo/)).toBeInTheDocument();
  });

  it("documents touch target and focus-visible styles in CSS", () => {
    expect(styles).toContain(".juli-popover__trigger");
    expect(styles).toContain("min-height: var(--juli-touch-target)");
    expect(styles).toContain(".juli-popover__trigger:focus-visible");
    expect(styles).toContain("box-shadow: var(--juli-shadow-medium)");
    expect(styleRules).not.toMatch(/#[0-9a-f]{3,8}/i);
  });
});
