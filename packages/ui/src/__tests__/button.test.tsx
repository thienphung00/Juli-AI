import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Button } from "../button";
import { loadUiStyles, loadUiStyleRules } from "./test-utils";

const styles = loadUiStyles();
const styleRules = loadUiStyleRules();

describe("Button", () => {
  it("renders primary, secondary, and ghost variants with Vietnamese labels", () => {
    render(
      <>
        <Button variant="primary">Phê duyệt</Button>
        <Button variant="secondary">Từ chối</Button>
        <Button variant="ghost">Mở rộng</Button>
      </>,
    );

    expect(screen.getByRole("button", { name: "Phê duyệt" })).toHaveClass(
      "juli-btn--primary",
    );
    expect(screen.getByRole("button", { name: "Từ chối" })).toHaveClass(
      "juli-btn--secondary",
    );
    expect(screen.getByRole("button", { name: "Mở rộng" })).toHaveClass(
      "juli-btn--ghost",
    );
  });

  it("applies size classes and meets the 44px touch-target contract", () => {
    render(
      <>
        <Button size="large">Phê duyệt</Button>
        <Button size="default">Từ chối</Button>
        <Button size="small">Mở rộng</Button>
      </>,
    );

    expect(screen.getByRole("button", { name: "Phê duyệt" })).toHaveClass(
      "juli-btn--large",
    );
    expect(screen.getByRole("button", { name: "Từ chối" })).toHaveClass(
      "juli-btn--default",
    );
    expect(screen.getByRole("button", { name: "Mở rộng" })).toHaveClass(
      "juli-btn--small",
    );
    expect(styles).toContain("min-height: var(--juli-touch-target)");
    expect(styles).toContain(".juli-btn:focus-visible");
  });

  it("disables interaction while loading and exposes a spinner", () => {
    render(<Button loading>Phê duyệt</Button>);

    const button = screen.getByRole("button", { name: "Phê duyệt" });

    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(button.querySelector(".juli-btn__spinner")).toBeInTheDocument();
  });

  it("honors the disabled state", () => {
    render(<Button disabled>Từ chối</Button>);

    expect(screen.getByRole("button", { name: "Từ chối" })).toBeDisabled();
  });

  it("fires click handlers when enabled", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();

    render(<Button onClick={onClick}>Phê duyệt</Button>);
    await user.click(screen.getByRole("button", { name: "Phê duyệt" }));

    expect(onClick).toHaveBeenCalledOnce();
  });

  it("documents hover, pressed, and reduced-motion interaction states in CSS", () => {
    expect(styles).toContain(".juli-btn--primary:hover:not(:disabled)");
    expect(styles).toContain(".juli-btn:active:not(:disabled)");
    expect(styles).toContain("@media (prefers-reduced-motion: reduce)");
    expect(styles).toContain(".juli-btn__spinner");
    expect(styleRules).not.toMatch(/#[0-9a-f]{3,8}/i);
  });
});
