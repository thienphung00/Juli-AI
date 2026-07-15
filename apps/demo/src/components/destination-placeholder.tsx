interface DestinationPlaceholderProps {
  description: string;
  recoveryHref?: string;
  recoveryLabel?: string;
  state?: "preview" | "loading" | "empty" | "error";
  title: string;
}

const kickerByState = {
  preview: "Bản xem trước",
  loading: "Đang tải",
  empty: "Chưa có dữ liệu",
  error: "Chưa thể tải nội dung",
} as const;

export function DestinationPlaceholder({
  description,
  recoveryHref = "/",
  recoveryLabel = "Về Trang chủ",
  state = "preview",
  title,
}: DestinationPlaceholderProps) {
  return (
    <section
      className="demo-placeholder"
      role={state === "error" ? "alert" : "status"}
      aria-label={title}
      aria-live={state === "error" ? "assertive" : "polite"}
    >
      <p className="demo-kicker">{kickerByState[state]}</p>
      <h1>{title}</h1>
      <p>{description}</p>
      <a className="demo-placeholder__recovery" href={recoveryHref}>
        {recoveryLabel}
      </a>
    </section>
  );
}
