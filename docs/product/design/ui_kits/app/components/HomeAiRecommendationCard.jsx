// Current recommendation/execution demonstration. The similarly named source example is
// historical evidence only and does not define this card's current action contract.
function HomeAiRecommendationCard({ recommendation, onApprove, onReject }) {
  const [expanded, setExpanded] = React.useState(false);

  return (
    <article className="card" style={{ padding: 16 }} data-testid="recommendation-card">
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8 }}>
        <h2 style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 14, fontWeight: 600, color: "var(--primary)", margin: 0 }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M12 3v4M12 17v4M5 12H3M21 12h-2M6.5 6.5l1.5 1.5M16 16l1.5 1.5M17.5 6.5L16 8M8 16l-1.5 1.5" strokeLinecap="round" />
          </svg>
          Đề xuất
        </h2>
        <span className="badge badge-success">Độ tin cậy: Cao</span>
      </div>
      <p style={{ marginTop: 8, fontSize: 14, fontWeight: 600 }} data-testid="recommendation-headline">
        {recommendation.headline}
      </p>
      <p style={{ color: "var(--muted-foreground)", fontSize: 13 }}>
        Tác động dự kiến: <strong style={{ color: "var(--foreground)" }}>{recommendation.impact}</strong>
      </p>
      {expanded && (
        <div style={{ borderRadius: 12, border: "1px solid color-mix(in srgb, var(--info) 24%, var(--border))", background: "color-mix(in srgb, var(--info) 6%, transparent)", padding: 12 }}>
          <strong style={{ color: "var(--info)", fontSize: 13 }}>Lý do đề xuất</strong>
          <p style={{ margin: "6px 0 0", fontSize: 13 }}>{recommendation.reasoning}</p>
        </div>
      )}
      <div style={{ marginTop: 12, display: "flex", flexWrap: "wrap", gap: 8 }}>
        <button type="button" className="btn-primary" onClick={onApprove} style={{ flex: 1 }}>Phê duyệt</button>
        <button type="button" className="btn-secondary" onClick={onReject} style={{ flex: 1 }}>Từ chối</button>
        <button
          type="button"
          className="btn-secondary"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
          style={{ flexBasis: "100%" }}
        >
          {expanded ? "Thu gọn" : "Mở rộng"}
        </button>
      </div>
    </article>
  );
}

window.HomeAiRecommendationCard = HomeAiRecommendationCard;
