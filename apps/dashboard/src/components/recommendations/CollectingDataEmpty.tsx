export function CollectingDataEmpty({ entityType = "gợi ý" }: { entityType?: string }) {
  return (
    <div className="py-12 text-center" data-testid="recommendations-empty">
      <p className="text-lg font-medium" style={{ color: "var(--muted-foreground)" }}>
        Đang thu thập dữ liệu
      </p>
      <p className="mt-1 text-sm" style={{ color: "var(--muted-foreground)", opacity: 0.6 }}>
        Hệ thống đang xây dựng đồ thị {entityType} — quay lại sau vài phút
      </p>
    </div>
  );
}
