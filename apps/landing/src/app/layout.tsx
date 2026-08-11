import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "Juli AI, trợ lý AI cho người bán TikTok Shop",
  description:
    "Juli tự động theo dõi cửa hàng, phân tích dữ liệu và đề xuất hành động phù hợp. Bạn phê duyệt, Juli thực hiện. Trải nghiệm ngay trên dữ liệu mẫu, không cần đăng ký.",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="vi">
      <body>{children}</body>
    </html>
  );
}
