import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  CardMeta,
  CardTitle,
  InteractiveCard,
} from "../card";
import { Button } from "../button";
import { loadUiStyles, loadUiStyleRules } from "./test-utils";

const styles = loadUiStyles();
const styleRules = loadUiStyleRules();

describe("Card", () => {
  it("renders a standard card with header, body, and footer regions", () => {
    render(
      <Card data-testid="standard-card">
        <CardHeader>
          <CardTitle id="shop-title">Thông tin cửa hàng</CardTitle>
          <CardMeta>Cập nhật hôm nay</CardMeta>
        </CardHeader>
        <CardBody>Shop ABC đang hoạt động bình thường.</CardBody>
        <CardFooter>
          <Button variant="secondary">Xem chi tiết</Button>
        </CardFooter>
      </Card>,
    );

    const card = screen.getByTestId("standard-card");

    expect(card).toHaveClass("juli-card");
    expect(screen.getByRole("heading", { name: "Thông tin cửa hàng" })).toHaveClass(
      "juli-card__title",
    );
    expect(screen.getByText("Cập nhật hôm nay")).toHaveClass("juli-card__meta");
    expect(screen.getByText(/Shop ABC/)).toHaveClass("juli-card__body");
    expect(screen.getByRole("button", { name: "Xem chi tiết" })).toBeInTheDocument();
  });

  it("renders an interactive card as a keyboard-reachable button", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();

    render(
      <InteractiveCard data-testid="interactive-card" onClick={onClick}>
        <CardTitle>Quyết định</CardTitle>
        <CardBody>Xem đề xuất cần phê duyệt.</CardBody>
      </InteractiveCard>,
    );

    const card = screen.getByTestId("interactive-card");

    expect(card.tagName).toBe("BUTTON");
    expect(card).toHaveClass("juli-card--interactive");

    await user.click(card);
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("renders an interactive card as a link when href is provided", () => {
    render(
      <InteractiveCard href="/decisions">
        <CardTitle>Phân tích</CardTitle>
      </InteractiveCard>,
    );

    const link = screen.getByRole("link", { name: /Phân tích/ });

    expect(link).toHaveAttribute("href", "/decisions");
    expect(link).toHaveClass("juli-card--interactive");
  });

  it("documents hover, pressed, and focus-visible interaction states in CSS", () => {
    expect(styles).toContain(".juli-card--interactive:hover");
    expect(styles).toContain(".juli-card--interactive:active");
    expect(styles).toContain(".juli-card--interactive:focus-visible");
    expect(styles).toContain("border-radius: var(--juli-radius)");
    expect(styles).toContain("box-shadow: var(--juli-shadow-small)");
    expect(styleRules).not.toMatch(/#[0-9a-f]{3,8}/i);
  });
});
