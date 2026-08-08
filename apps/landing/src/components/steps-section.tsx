const STEPS = [
  {
    key: "phan-tich",
    label: "Phân tích",
    description: "AI giám sát và phân tích dữ liệu kinh doanh liên tục.",
    icon: "🔍",
  },
  {
    key: "goi-y",
    label: "Gợi ý",
    description: "Đề xuất hành động dựa trên dữ liệu thực tế.",
    icon: "💡",
  },
  {
    key: "thuc-hien",
    label: "Thực hiện",
    description: "Tự động thực thi trên các hệ thống và nền tảng.",
    icon: "⚙️",
  },
  {
    key: "ket-qua",
    label: "Kết quả",
    description: "Tăng trưởng doanh thu và tối ưu chi phí vận hành.",
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
