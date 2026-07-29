import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { RecommendationCard } from "../recommendation-card";

const baseProps = {
  eligibility: "Điều kiện mẫu",
  evidence: "Bằng chứng mẫu",
  knownLimits: "Giới hạn mẫu",
  onReject: () => {},
  reasoning: "Juli phát hiện khoảng trống nhu cầu chưa được đáp ứng.",
  risks: "Rủi ro mẫu",
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
    expect(within(card).getByText(baseProps.reasoning)).toBeInTheDocument();
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
});
