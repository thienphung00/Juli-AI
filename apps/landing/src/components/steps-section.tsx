const STEPS = [
  {
    key: "phan-tich",
    label: "Phân tích",
    description: "Juli quét toàn bộ shop và so từng chỉ số của mỗi luồng truy cập với kỳ trước.",
    icon: "🔍",
  },
  {
    key: "goi-y",
    label: "Gợi ý",
    description: "Chỉ ra chỉ số, sản phẩm và nội dung cần tối ưu, kèm hành động cụ thể.",
    icon: "💡",
  },
  {
    key: "thuc-hien",
    label: "Thực hiện",
    description: "Sau khi bạn xác nhận, Juli tự động thực hiện, giảm việc thủ công cho đội vận hành.",
    icon: "⚙️",
  },
  {
    key: "theo-doi",
    label: "Theo dõi",
    description: "Đo tác động lên GMV theo từng luồng truy cập và tiếp tục tối ưu mỗi tháng.",
    icon: "📈",
  },
] as const;

export function StepsSection() {
  return (
    <section aria-label="Juli làm việc như thế nào" className="lp-steps">
      <ol className="lp-steps__list">
        {STEPS.map((step) => (
          <li className="lp-steps__item" key={step.key}>
            <span aria-hidden="true" className="lp-steps__icon">
              {step.icon}
            </span>
            <div>
              <h2 className="lp-steps__label">{step.label}</h2>
              <p className="lp-steps__description">{step.description}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
