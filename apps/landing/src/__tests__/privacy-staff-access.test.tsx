import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PrivacyPolicyPage from "../app/privacy/page";

describe("privacy: staff access to support and operate the service (D25.6)", () => {
  it("says so in Vietnamese and English, accepted when connecting a shop", () => {
    render(<PrivacyPolicyPage />);
    expect(screen.getByText(/hỗ trợ và vận hành dịch vụ — bạn đồng ý điều này khi kết nối shop/)).toBeInTheDocument();
    expect(screen.getByText(/to\s+support and operate the service/)).toBeInTheDocument();
    expect(screen.getByText(/which you accept when you connect a shop/)).toBeInTheDocument();
    expect(screen.getAllByText(/không bao giờ xem dữ liệu người mua|never buyer data/).length).toBe(2);
  });
});
