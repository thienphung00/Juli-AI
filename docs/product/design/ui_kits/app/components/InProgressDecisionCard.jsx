// Execution card for one complete recommendation-to-outcome demonstration.
const IN_PROGRESS_STATUS_LABELS = {
  needs_input: "Cần thêm thông tin",
  executing: "Đang thực hiện",
  completed: "Hoàn tất",
};

function InProgressDecisionCard({ decision, onAdvance }) {
  const { workflow_id: workflowId, status } = decision;
  const statusLabel = IN_PROGRESS_STATUS_LABELS[status];

  return (
    <article
      className="card"
      style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12 }}
      data-testid={`in-progress-decision-${workflowId}`}
      data-status={status}
    >
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-start", justifyContent: "space-between", gap: 8 }}>
        <h3 style={{ fontSize: 16, fontWeight: 600, margin: 0, color: "var(--foreground)" }}>{decision.title}</h3>
        <span
          style={{ borderRadius: 100, padding: "2px 10px", fontSize: 12, fontWeight: 500, background: "color-mix(in srgb, var(--primary) 12%, transparent)", color: "var(--primary)", whiteSpace: "nowrap" }}
        >
          {statusLabel}
        </span>
      </div>

      <p style={{ color: "var(--muted-foreground)", fontSize: 14, margin: 0 }}>
        Tác động dự kiến: +{decision.estimated_impact.value} {decision.estimated_impact.metric}
      </p>

      {status === "needs_input" && (
        <div style={{ display: "grid", gap: 8 }}>
          <label style={{ fontSize: 13, fontWeight: 600 }} htmlFor={`${workflowId}-quantity`}>Số lượng xử lý</label>
          <input id={`${workflowId}-quantity`} className="field-input" defaultValue="3 đơn hàng" />
          <button type="button" className="btn-primary" onClick={onAdvance}>Bắt đầu thực thi</button>
        </div>
      )}

      {status === "executing" && (
        <div>
          <p style={{ fontSize: 14, color: "var(--muted-foreground)", margin: "0 0 10px" }}>
            Đã xác nhận 2/3 đơn hàng. Juli đang chờ kết quả bước cuối.
          </p>
          <button type="button" className="btn-primary" style={{ width: "100%" }} onClick={onAdvance}>Mô phỏng hoàn tất</button>
        </div>
      )}

      {status === "completed" && (
        <div style={{ borderRadius: 12, background: "var(--success-tint)", color: "var(--success)", padding: 12, fontSize: 14 }}>
          Hoàn tất 3/3 đơn hàng đúng hạn. Kết quả đã được ghi nhận.
        </div>
      )}
    </article>
  );
}

window.InProgressDecisionCard = InProgressDecisionCard;
