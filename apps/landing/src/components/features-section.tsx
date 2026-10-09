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
      "GMV, đơn hàng, AOV và chỉ số từng luồng truy cập, xem ngay trên điện thoại hoặc máy tính.",
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
    key: "theo-doi",
    icon: "📈",
    title: "Theo dõi",
    description:
      "Theo dõi tác động lên GMV mỗi tháng, tiết kiệm ~1,7 giờ/ngày cho mỗi nhân sự.",
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
        Tối ưu từng luồng truy cập, từ Thẻ sản phẩm đến Live
      </h2>
      <p className="lp-features__subheading">
        Mỗi luồng truy cập có chỉ số riêng: Hiển thị, CTR, CTOR, AOV. Juli tìm
        đúng chỉ số đang kéo GMV xuống và đề xuất cách sửa.
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
