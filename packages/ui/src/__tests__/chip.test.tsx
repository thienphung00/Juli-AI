import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FilterChip, InputChip, StatusChip } from "../chip";
import { loadUiStyles } from "./test-utils";

const styles = loadUiStyles();

describe("Chip", () => {
  it("renders non-interactive status chips inline", () => {
    render(<StatusChip variant="warning">Đang chờ</StatusChip>);

    const chip = screen.getByText("Đang chờ");

    expect(chip.tagName).toBe("SPAN");
    expect(chip).toHaveClass("juli-chip--status", "juli-chip--warning");
  });

  it("renders filter chips as tabs with aria-selected state", async () => {
    const user = userEvent.setup();

    render(
      <div role="tablist" aria-label="Lọc quyết định">
        <FilterChip selected>Đề xuất</FilterChip>
        <FilterChip>Đang thực hiện</FilterChip>
      </div>,
    );

    const selected = screen.getByRole("tab", { name: "Đề xuất" });
    const inactive = screen.getByRole("tab", { name: "Đang thực hiện" });

    expect(selected).toHaveAttribute("aria-selected", "true");
    expect(inactive).toHaveAttribute("aria-selected", "false");
    expect(selected).toHaveClass("juli-chip--selected");

    await user.click(inactive);
  });

  it("renders closeable input chips with a 44px remove target", async () => {
    const user = userEvent.setup();
    const onRemove = vi.fn();

    render(
      <InputChip onRemove={onRemove} removeLabel="Xóa SKU ABC">
        SKU ABC
      </InputChip>,
    );

    const removeButton = screen.getByRole("button", { name: "Xóa SKU ABC" });

    expect(removeButton).toHaveClass("juli-chip__remove");
    expect(styles).toContain(".juli-chip__remove");
    expect(styles).toContain("min-width: var(--juli-touch-target)");

    await user.click(removeButton);
    expect(onRemove).toHaveBeenCalledOnce();
  });

  it("documents focus-visible and reduced-motion styles for interactive chips", () => {
    expect(styles).toContain(".juli-chip--filter:focus-visible");
    expect(styles).toContain(".juli-chip__remove:focus-visible");
    expect(styles).toContain(".juli-chip--selected");
  });
});
