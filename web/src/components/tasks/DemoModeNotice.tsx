"use client";

export function DemoModeNotice() {
  return (
    <p
      className="rounded-xl border px-3 py-2 text-xs leading-relaxed"
      style={{
        borderColor: "var(--border)",
        color: "var(--muted-foreground)",
        background: "var(--card)",
      }}
      data-testid="task-demo-notice"
      title="Phase 1 — dữ liệu mô phỏng, không gọi TikTok API"
    >
      <span className="font-semibold" style={{ color: "var(--foreground)" }}>
        Chế độ demo (Phase 1):
      </span>{" "}
      Phê duyệt hoặc bỏ qua chỉ cập nhật trên thiết bị của bạn — Juli chưa thực thi
      thao tác thật trên TikTok Shop.
    </p>
  );
}
