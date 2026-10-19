import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PrivacyPolicyPage from "../app/privacy/page";
import TermsOfServicePage from "../app/terms/page";

/**
 * P42 (2026-10-16): layer 1 (data rights) and layer 2 (processing and AI
 * providers) of the legal pages. Every processor and every item sent to the
 * AI provider was checked against the code (fasttrack/LOG.md, P42 entry).
 */

/** The processor list, identical in the Vietnamese and English Privacy §7. */
const PROCESSORS_VI = [
  "Supabase",
  "TikTok Shop API",
  "OpenAI",
  "Nhà cung cấp máy chủ (VPS)",
  "Cloudflare",
  "Amazon Web Services (AWS)",
  "Google Workspace",
  "Zalo (Zalo OA) và Google Firebase (dự kiến)",
  "Viettel-CA (dự kiến)",
  "TikTok Pixel",
] as const;

const PROCESSORS_EN = [
  "Supabase",
  "TikTok Shop API",
  "OpenAI",
  "Server (VPS) provider",
  "Cloudflare",
  "Amazon Web Services (AWS)",
  "Google Workspace",
  "Zalo (Zalo OA) and Google Firebase (planned)",
  "Viettel-CA (planned)",
  "TikTok Pixel",
] as const;

function englishPart(container: HTMLElement) {
  const part = container.querySelector("#english");
  expect(part).not.toBeNull();
  return part as HTMLElement;
}

describe("/terms §8 — data rights (layer 1)", () => {
  function section() {
    render(<TermsOfServicePage />);
    const heading = screen.getByRole("heading", { level: 2, name: /^8\. Dữ liệu của bạn/ });
    return heading.closest("section") as HTMLElement;
  }

  it("states ownership, the seller's warranty and the controller / processor split", () => {
    const s = section();
    expect(s).toHaveTextContent("Dữ liệu shop và dữ liệu kinh doanh của bạn thuộc về bạn");
    expect(s).toHaveTextContent(
      /Bạn bảo đảm mình có quyền cho phép Juli xử lý dữ liệu shop của bạn, bao gồm dữ liệu cá nhân của người mua/,
    );
    expect(s).toHaveTextContent(/bạn là bên kiểm soát dữ liệu và Juli là bên xử lý dữ liệu thay mặt bạn/);
    const commitments = within(s).getByRole("list", {
      name: "Cam kết của Juli khi xử lý dữ liệu người mua",
    });
    expect(commitments).toHaveTextContent(/không bán, không tiết lộ và không chuyển giao/);
    expect(commitments).toHaveTextContent(/chậm nhất 72 giờ/);
    expect(commitments).toHaveTextContent(/mục 8 của Chính sách bảo mật/);
  });

  it("covers third-party content, buyer reviews, trade secrets and market data", () => {
    const s = section();
    expect(s).toHaveTextContent(/giọng nói, hình ảnh của người khác/);
    expect(s).toHaveTextContent(/âm nhạc/);
    expect(s).toHaveTextContent(/loại bỏ tên và thông tin định danh của người mua/);
    expect(s).toHaveTextContent(/thông tin bạn không được phép chia sẻ/);
    expect(s).toHaveTextContent(/FastMoss/);
    expect(s).toHaveTextContent(/không lấy từ dữ liệu riêng của các shop khác dùng Juli/);
  });

  it("makes de-identified model improvement a condition of use, never on buyer data (D68.2, D68.3)", () => {
    const s = section();
    expect(s).toHaveTextContent(/sau khi đã\s*được khử định danh/);
    expect(s).toHaveTextContent(/tinh chỉnh \(fine-tune\)/);
    expect(s).toHaveTextContent(/Đây\s*là điều kiện để sử dụng Juli/);
    expect(s).toHaveTextContent(/dữ liệu của người mua không bao giờ được\s*dùng để huấn luyện mô hình/);
    expect(s).toHaveTextContent(/không thể huỷ ngang, có hiệu lực vĩnh viễn/);
    expect(s).toHaveTextContent(/Juli không huấn luyện lại các mô hình đó/);
    expect(s).not.toHaveTextContent(/yêu cầu ngừng sử dụng dữ liệu của mình cho mục đích này/);
    expect(s).toHaveTextContent(/không được dùng để tạo gợi ý cho shop khác/);
    // Points to the full processor list instead of repeating it.
    expect(s).toHaveTextContent(/mục 7 của\s*Chính sách bảo mật/);
  });
});

describe("/privacy — processing and AI providers (layer 2)", () => {
  it("lists the same processors, in the same order, in Vietnamese and English", () => {
    const { container } = render(<PrivacyPolicyPage />);
    const vi = screen.getByRole("list", { name: "Bên xử lý dữ liệu" });
    const en = within(englishPart(container)).getByRole("list", { name: "Data processors" });
    const viItems = within(vi).getAllByRole("listitem").map((li) => li.textContent ?? "");
    const enItems = within(en).getAllByRole("listitem").map((li) => li.textContent ?? "");
    expect(viItems).toHaveLength(PROCESSORS_VI.length);
    expect(enItems).toHaveLength(PROCESSORS_EN.length);
    PROCESSORS_VI.forEach((name, i) => expect(viItems[i], name).toContain(name));
    PROCESSORS_EN.forEach((name, i) => expect(enItems[i], name).toContain(name));
    // Shopee shares the marketplace bullet with TikTok Shop.
    expect(viItems[1]).toContain("Shopee Open Platform");
    expect(enItems[1]).toContain("Shopee Open Platform");
    // FastMoss is a market-data source, not a processor of shop data.
    expect(vi).not.toHaveTextContent("FastMoss");
    expect(en).not.toHaveTextContent("FastMoss");
  });

  it("says exactly what goes to OpenAI, in both languages, and what never does", () => {
    const { container } = render(<PrivacyPolicyPage />);
    const vi = screen.getByRole("list", { name: "Dữ liệu gửi cho OpenAI" });
    const en = within(englishPart(container)).getByRole("list", { name: "Data sent to OpenAI" });
    expect(within(vi).getAllByRole("listitem")).toHaveLength(5);
    expect(within(en).getAllByRole("listitem")).toHaveLength(5);
    expect(vi).toHaveTextContent(/không gửi nguyên\s*file/);
    expect(en).toHaveTextContent(/never sends the whole file/);
    expect(container).toHaveTextContent(/không qua ứng dụng ChatGPT/);
    expect(container).toHaveTextContent(/not through the consumer ChatGPT app/);
    expect(container).toHaveTextContent(
      /Juli không gửi cho OpenAI thông tin liên hệ hay mã định danh của người mua/,
    );
    expect(container).toHaveTextContent(/Juli does not send OpenAI buyers’ contact information or identifiers/);
    expect(container).toHaveTextContent(/chế độ lưu\s*trữ phản hồi của OpenAI được tắt/);
    expect(container).toHaveTextContent(/response storage turned\s*off/);
    expect(container).toHaveTextContent(/giám sát lạm dụng/);
    expect(container).toHaveTextContent(/monitor for abuse/);
  });

  it("states the controller / processor split, cross-border safeguards and the 72-hour notice in both languages", () => {
    const { container } = render(<PrivacyPolicyPage />);
    const en = englishPart(container);
    expect(container).toHaveTextContent(/người bán là bên kiểm soát dữ liệu và Juli xử lý dữ\s*liệu đó thay mặt người bán/);
    expect(en).toHaveTextContent(/the seller is the controller and Juli processes that data on the seller’s behalf/);
    expect(container).toHaveTextContent(/chủ yếu tại Hoa Kỳ/);
    expect(en).toHaveTextContent(/mainly in the United States/);
    expect(container).toHaveTextContent(/mã hoá dữ liệu khi truyền/);
    expect(en).toHaveTextContent(/encrypting data in transit/);
    expect(container).toHaveTextContent(/thông báo cho bạn chậm nhất 72 giờ sau khi phát hiện/);
    expect(en).toHaveTextContent(/no later than 72 hours after discovering it/);
  });

  it("covers uploads, buyer reviews and market data in §4, in both languages", () => {
    const { container } = render(<PrivacyPolicyPage />);
    const en = englishPart(container);
    expect(container.querySelector("#noi-dung-ban-cung-cap")).not.toBeNull();
    expect(container.querySelector("#content-you-provide")).not.toBeNull();
    expect(container).toHaveTextContent(/xoá tự động sau khoảng 24 giờ/);
    expect(en).toHaveTextContent(/deleted automatically after about 24 hours/);
    expect(container).toHaveTextContent(/Juli không gửi dữ liệu shop của\s*bạn \(đơn hàng, số liệu kinh doanh, dữ liệu người mua\) cho FastMoss/);
    expect(en).toHaveTextContent(/Juli does not send your shop data \(orders, business figures, buyer data\) to FastMoss/);
  });

  it("shows the date only (no version, D68.13) in both languages, and no counsel note", () => {
    const { container } = render(<PrivacyPolicyPage />);
    expect(screen.getByText(/^Cập nhật lần cuối: 18\/10\/2026/)).toBeInTheDocument();
    expect(container).not.toHaveTextContent(/Phiên bản/);
    expect(englishPart(container)).toHaveTextContent(/Last updated \(effective date\): October 18, 2026/);
    expect(englishPart(container)).not.toHaveTextContent(/Version \d/);
    expect(container).not.toHaveTextContent(/cần luật sư/);
  });
});
