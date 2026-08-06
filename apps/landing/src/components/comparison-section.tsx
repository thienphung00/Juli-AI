import { DEMO_URL, SECTION_IDS } from "../lib/site";
import { CtaLink } from "./cta-link";

interface ComparisonColumn {
  key: string;
  title: string;
  highlight?: boolean;
  pros: string[];
  cons: string[];
}

const COLUMNS: ComparisonColumn[] = [
  {
    key: "self",
    title: "Tự vận hành",
    pros: ["Chủ động", "Tiết kiệm chi phí", "Phù hợp cho đơn vị nhỏ"],
    cons: [
      "Kém phù hợp cho điện thoại",
      "Thiếu tính ổn định và chuyên nghiệp",
      "Khó theo kịp những thay đổi của nền tảng",
    ],
  },
  {
    key: "juli",
    title: "Juli",
    highlight: true,
    pros: [
      "Tiết kiệm hơn so với Agency",
      "Đa cửa hàng và đa nền tảng",
      "Đơn giản và dễ sử dụng",
      "Tiến độ và kết quả trực tiếp",
      "Bám sát mọi thay đổi",
    ],
    cons: ["Cần thời gian để tối ưu các tính năng", "Không thay thế người bán"],
  },
  {
    key: "agency",
    title: "Thuê Agency",
    pros: ["Có người hỗ trợ", "Có kinh nghiệm vận hành", "Đa cửa hàng và đa nền tảng"],
    cons: [
      "Chi phí cao",
      "Thiếu thông tin về tiến độ",
      "Khó đánh giá hiệu quả thực tế",
    ],
  },
];

export function ComparisonSection() {
  return (
    <section
      aria-labelledby="comparison-heading"
      className="lp-comparison"
      id={SECTION_IDS.comparison}
    >
      <h2 className="lp-comparison__heading" id="comparison-heading">
        Giải pháp trên thị trường
      </h2>
      <div className="lp-comparison__grid">
        {COLUMNS.map((column) => (
          <article
            className={
              column.highlight
                ? "lp-comparison__card lp-comparison__card--highlight"
                : "lp-comparison__card"
            }
            key={column.key}
          >
            <h3 className="lp-comparison__title">
              {column.highlight ? `→ ${column.title} ←` : column.title}
            </h3>
            <ul className="lp-comparison__list">
              {column.pros.map((item) => (
                <li className="lp-comparison__row" key={item}>
                  <span aria-hidden="true" className="lp-comparison__mark lp-comparison__mark--pro">
                    ✓
                  </span>
                  {item}
                </li>
              ))}
              {column.cons.map((item) => (
                <li className="lp-comparison__row" key={item}>
                  <span aria-hidden="true" className="lp-comparison__mark lp-comparison__mark--con">
                    ✕
                  </span>
                  {item}
                </li>
              ))}
            </ul>
          </article>
        ))}
      </div>
      <div className="lp-comparison__cta">
        <CtaLink data-testid="comparison-demo-cta" href={DEMO_URL} size="large">
          Xem Juli làm việc trong Demo
        </CtaLink>
      </div>
    </section>
  );
}
