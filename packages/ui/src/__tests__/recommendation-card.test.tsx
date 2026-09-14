import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RecommendationCard } from "../recommendation-card";

const baseProps = {
  eligibility: "Điều kiện mẫu",
  evidence: "Bằng chứng mẫu",
  knownLimits: "Giới hạn mẫu",
  onReject: () => {},
  reasoning: "Juli phát hiện khoảng trống nhu cầu chưa được đáp ứng.",
  risks: "Rủi ro mẫu",
  sellerReason:
    "Thêm sản phẩm chăm sóc da giúp shop bắt kịp nhu cầu đang tăng.",
  signal:
    "Nhóm ngành chăm sóc da đang có nhu cầu tăng nhưng shop chưa có sản phẩm nào đáp ứng.",
  title: "Tạo sản phẩm nổi bật",
  workflowKey: "create_hero_product_1",
};

describe("RecommendationCard", () => {
  it("renders signal and one concise reason without confidence or capability badges", () => {
    render(<RecommendationCard {...baseProps} />);

    const card = screen.getByRole("article");

    expect(
      within(card).getByRole("heading", { level: 3, name: baseProps.title }),
    ).toBeInTheDocument();
    expect(within(card).getByText(baseProps.signal)).toBeInTheDocument();
    expect(within(card).getByText(baseProps.sellerReason)).toBeInTheDocument();
    expect(within(card).queryByText(/Độ tin cậy/i)).not.toBeInTheDocument();
    expect(
      within(card).queryByText(/Có thể thực thi qua FBS/i),
    ).not.toBeInTheDocument();
    expect(card.textContent).not.toContain("Tác động dự kiến:");
  });

  it("keeps verbose detail in the expandable panel only", async () => {
    const user = userEvent.setup();
    render(<RecommendationCard {...baseProps} />);

    const card = screen.getByRole("article");
    expect(within(card).queryByText(baseProps.evidence)).not.toBeInTheDocument();

    await user.click(within(card).getByRole("button", { name: "Mở rộng" }));

    expect(within(card).getByText(baseProps.evidence)).toBeInTheDocument();
    expect(within(card).getByText(baseProps.eligibility)).toBeInTheDocument();
    expect(within(card).getByText(baseProps.knownLimits)).toBeInTheDocument();
    expect(within(card).getByText(baseProps.risks)).toBeInTheDocument();
  });

  it("links the title to detailHref when provided", () => {
    render(
      <RecommendationCard
        {...baseProps}
        detailHref="/decisions/recommendations/create_hero_product_1"
      />,
    );

    const card = screen.getByRole("article");
    const titleLink = within(card).getByRole("link", { name: baseProps.title });

    expect(titleLink).toHaveAttribute(
      "href",
      "/decisions/recommendations/create_hero_product_1",
    );
  });
});

describe("RecommendationCard — v3 anatomy (issue #1916)", () => {
  const previewRows = [
    {
      label: "Tiêu đề SEO",
      change: "“Cũ” → “Mới”",
      kind: "change",
    },
    {
      label: "Giá bán",
      change: "Giữ nguyên",
      kind: "keep",
    },
  ] as const;

  it("renders subject-left/category-right header and the preview block instead of the raw signal", () => {
    render(
      <RecommendationCard
        {...baseProps}
        categoryLabel="Tối ưu sản phẩm"
        onSeeMore={() => {}}
        previewRows={previewRows}
      />,
    );

    const card = screen.getByRole("article");
    expect(within(card).getByText("Tối ưu sản phẩm")).toBeInTheDocument();

    const preview = within(card).getByTestId("recommendation-preview");
    expect(within(preview).getByText("Tiêu đề SEO")).toBeInTheDocument();
    expect(within(preview).getByText("“Cũ” → “Mới”")).toBeInTheDocument();
    expect(within(preview).getByText("Giữ nguyên")).toBeInTheDocument();
    expect(within(card).queryByText(baseProps.signal)).not.toBeInTheDocument();
  });

  it("renders Xem thêm when the caller owns the detail, and hides it while open", async () => {
    const user = userEvent.setup();
    const onSeeMore = vi.fn();
    const { rerender } = render(
      <RecommendationCard
        {...baseProps}
        onSeeMore={onSeeMore}
        previewRows={previewRows}
      />,
    );

    const card = screen.getByRole("article");
    expect(
      within(card).queryByRole("button", { name: "Mở rộng" }),
    ).not.toBeInTheDocument();

    await user.click(within(card).getByRole("button", { name: "Xem thêm" }));
    expect(onSeeMore).toHaveBeenCalledTimes(1);

    rerender(
      <RecommendationCard
        {...baseProps}
        onSeeMore={onSeeMore}
        previewRows={previewRows}
        seeMoreOpen
      />,
    );

    expect(
      within(card).queryByRole("button", { name: "Xem thêm" }),
    ).not.toBeInTheDocument();
    expect(
      within(card).getByRole("button", { name: "Phê duyệt" }),
    ).toBeInTheDocument();
    expect(
      within(card).getByRole("button", { name: "Từ chối" }),
    ).toBeInTheDocument();
  });

  it("keeps the legacy in-card accordion when no beside-list detail is wired", async () => {
    const user = userEvent.setup();
    render(<RecommendationCard {...baseProps} />);

    const card = screen.getByRole("article");
    await user.click(within(card).getByRole("button", { name: "Mở rộng" }));
    expect(within(card).getByText(baseProps.evidence)).toBeInTheDocument();
  });
});
