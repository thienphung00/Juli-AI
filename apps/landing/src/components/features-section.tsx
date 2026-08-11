import type { ReactNode } from "react";

import { DEMO_URL, SECTION_IDS } from "../lib/site";
import { CtaLink } from "./cta-link";
import {
  AnalyticsMockup,
  ExecutionMockup,
  ResultsMockup,
  SuggestionsMockup,
} from "./feature-mockups";

interface Feature {
  key: string;
  icon: string;
  title: string;
  description: string;
  mockup: ReactNode;
}

const FEATURES: Feature[] = [
  {
    key: "phan-tich",
    icon: "🔍",
    title: "Phân tích",
    description:
      "Dữ liệu TMĐT như doanh thu, lợi nhuận, tồn kho, hiệu suất sản phẩm được phân tích trực tiếp trên điện thoại hoặc máy tính.",
    mockup: <AnalyticsMockup />,
  },
  {
    key: "goi-y",
    icon: "💡",
    title: "Gợi ý",
    description:
      "Đưa ra đề xuất các hành động phù hợp. Bạn có thể xem, sửa đổi, đặt câu hỏi và tiến đến bước thực hiện ngay.",
    mockup: <SuggestionsMockup />,
  },
  {
    key: "thuc-hien",
    icon: "⚙️",
    title: "Thực hiện",
    description:
      "Sau khi bạn xác nhận, Juli tự động thực hiện các hành động như tạo đơn nhập hàng, đồng bộ tồn kho, cập nhật sản phẩm.",
    mockup: <ExecutionMockup />,
  },
  {
    key: "ket-qua",
    icon: "📈",
    title: "Kết quả",
    description:
      "Tăng hiệu suất cửa hàng, tiết kiệm thời gian, và vận hành chuyên nghiệp hơn.",
    mockup: <ResultsMockup />,
  },
];

export function FeaturesSection() {
  return (
    <section
      aria-labelledby="features-heading"
      className="lp-features"
      id={SECTION_IDS.features}
    >
      <h2 className="lp-features__heading" id="features-heading">
        Vận hành TMĐT mọi lúc, mọi nơi, chỉ cần một cú chạm
      </h2>
      <p className="lp-features__subheading">
        Quản lý cửa hàng, theo dõi hiệu suất và tối ưu chiến dịch chỉ với vài
        thao tác trên điện thoại cùng trợ lý Juli.
      </p>
      <div className="lp-features__grid">
        {FEATURES.map((feature) => (
          <article className="lp-features__card" key={feature.key}>
            {feature.mockup}
            <h3 className="lp-features__title">
              <span aria-hidden="true" className="lp-features__icon">
                {feature.icon}
              </span>
              {feature.title}
            </h3>
            <p className="lp-features__description">{feature.description}</p>
          </article>
        ))}
      </div>
      <div className="lp-features__cta">
        <CtaLink data-testid="features-demo-cta" href={DEMO_URL} size="large">
          Trải nghiệm ngay
        </CtaLink>
      </div>
    </section>
  );
}
