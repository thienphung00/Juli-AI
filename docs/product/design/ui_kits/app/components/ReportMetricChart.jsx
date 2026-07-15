function CategoryIcon({ symbol }) {
  return (
    <span className="metric-icon" aria-hidden="true">
      {symbol}
    </span>
  );
}

function MetricChart({ metric, range, preview = false, compare = false }) {
  const snapshot = metric.ranges[range];
  const height = preview ? 76 : 210;

  if (metric.chartType === "gauge") {
    const dash = Math.max(0, Math.min(100, snapshot.numericValue));
    return (
      <svg className="metric-chart" viewBox="0 0 240 140" height={height} role={preview ? undefined : "img"} aria-hidden={preview || undefined} aria-label={preview ? undefined : `${metric.label}: ${snapshot.value}`}>
        <path d="M35 115 A85 85 0 0 1 205 115" fill="none" stroke="var(--border)" strokeWidth="18" strokeLinecap="round" />
        {compare && <path d="M35 115 A85 85 0 0 1 205 115" fill="none" stroke="var(--muted-foreground)" strokeWidth="4" strokeDasharray="7 7" pathLength="100" strokeDashoffset={100 - Math.max(0, dash - 2)} />}
        <path d="M35 115 A85 85 0 0 1 205 115" fill="none" stroke="var(--success)" strokeWidth="18" strokeLinecap="round" pathLength="100" strokeDasharray={`${dash} 100`} />
        {!preview && <text x="120" y="108" textAnchor="middle" fill="var(--foreground)" fontSize="24" fontWeight="700">{snapshot.value}</text>}
      </svg>
    );
  }

  const points = snapshot.points.map((value, index) => `${20 + index * 40},${120 - value}`).join(" ");
  const forecastPoints = snapshot.forecast.map((value, index) => `${140 + index * 40},${120 - value}`).join(" ");
  return (
    <svg className="metric-chart" viewBox="0 0 300 140" height={height} role={preview ? undefined : "img"} aria-hidden={preview || undefined} aria-label={preview ? undefined : `${metric.label}: ${snapshot.value}, ${snapshot.deltaLabel}`}>
      {!preview && [35, 70, 105].map((y) => <line key={y} x1="16" x2="286" y1={y} y2={y} stroke="var(--border)" strokeWidth="1" />)}
      {compare && <polyline points="20,100 60,91 100,86 140,82 180,76 220,70 260,66" fill="none" stroke="var(--muted-foreground)" strokeWidth="2" strokeDasharray="6 6" />}
      <polyline points={points} fill="none" stroke="var(--success)" strokeWidth={preview ? "2" : "3"} strokeLinecap="round" strokeLinejoin="round" />
      <polyline points={forecastPoints} fill="none" stroke="var(--primary)" strokeWidth={preview ? "2" : "3"} strokeDasharray="6 5" strokeLinecap="round" />
      {!preview && <text x="18" y="134" fill="var(--muted-foreground)" fontSize="11">Thực tế</text>}
      {!preview && <text x="232" y="134" fill="var(--muted-foreground)" fontSize="11">Dự báo</text>}
    </svg>
  );
}

function EmptyChartPattern() {
  return (
    <svg className="metric-chart" viewBox="0 0 300 90" height="76" aria-hidden="true" focusable="false">
      {[24, 45, 66].map((y) => <line key={y} x1="12" x2="288" y1={y} y2={y} stroke="var(--border)" strokeWidth="1" strokeDasharray="5 6" />)}
    </svg>
  );
}

function AvailabilityPopover({ metric }) {
  const [isOpen, setIsOpen] = React.useState(false);
  const triggerRef = React.useRef(null);
  const popoverRef = React.useRef(null);
  const titleRef = React.useRef(null);
  const titleId = `unavailable-${metric.metricKey}-title`;
  const popoverId = `unavailable-${metric.metricKey}-popover`;

  React.useEffect(() => {
    if (!isOpen) return undefined;
    titleRef.current?.focus();
    const close = (event) => {
      if (event.key === "Escape" || (event.type === "mousedown" && !popoverRef.current?.contains(event.target) && !triggerRef.current?.contains(event.target))) {
        setIsOpen(false);
        requestAnimationFrame(() => triggerRef.current?.focus());
      }
    };
    document.addEventListener("keydown", close);
    document.addEventListener("mousedown", close);
    return () => {
      document.removeEventListener("keydown", close);
      document.removeEventListener("mousedown", close);
    };
  }, [isOpen]);

  return (
    <div className="availability-control">
      <button ref={triggerRef} type="button" className="info-button" aria-label={`Vì sao ${metric.label} chưa khả dụng?`} aria-expanded={isOpen} aria-controls={popoverId} onClick={() => setIsOpen((value) => !value)}>i</button>
      {isOpen && (
        <div
          ref={popoverRef}
          id={popoverId}
          className="availability-popover"
          role="dialog"
          aria-labelledby={titleId}
          onKeyDown={(event) => {
            if (event.key === "Tab") {
              event.preventDefault();
              popoverRef.current?.querySelector("button")?.focus();
            }
          }}
        >
          <h4 ref={titleRef} id={titleId} tabIndex="-1">{metric.label} chưa khả dụng</h4>
          <p><strong>Nguồn dữ liệu:</strong> {metric.missingSource}</p>
          <p>{metric.activation}</p>
          <button type="button" className="btn-secondary" onClick={() => { setIsOpen(false); triggerRef.current?.focus(); }}>Đóng</button>
        </div>
      )}
    </div>
  );
}

function MainKpiSelectorCard({ metric, range, onSelect }) {
  if (!metric.available) {
    return (
      <article className="card metric-selector unavailable-card">
        <div className="metric-preview"><EmptyChartPattern /></div>
        <div className="metric-card-content">
          <CategoryIcon symbol={metric.symbol} />
          <div>
            <p className="metric-category">{metric.category}</p>
            <h3>{metric.label}</h3>
            <p>{metric.description}</p>
          </div>
        </div>
        <div className="availability-row">
          <span className="badge">Chưa khả dụng</span>
          <AvailabilityPopover metric={metric} />
        </div>
      </article>
    );
  }

  const snapshot = metric.ranges[range];
  return (
    <button type="button" className="card card-interactive metric-selector available-card" onClick={(event) => onSelect(event.detail === 0)}>
      <div className="metric-preview"><MetricChart metric={metric} range={range} preview /></div>
      <div className="metric-card-content">
        <CategoryIcon symbol={metric.symbol} />
        <div>
          <p className="metric-category">{metric.category}</p>
          <h3>{metric.label}</h3>
          <p>{metric.description}</p>
          <strong className="selector-value">{snapshot.value} <span>{snapshot.deltaLabel}</span></strong>
        </div>
      </div>
    </button>
  );
}

function ReportMetricChart({ metric, range, compare, onCompareChange, headingRef }) {
  const snapshot = metric.ranges[range];
  return (
    <article className="card metric-hero">
      <section className="metric-hero-summary">
        <div className="hero-heading">
          <CategoryIcon symbol={metric.symbol} />
          <div>
            <p className="metric-category">{metric.category} · KPI chính</p>
            <h2 ref={headingRef} tabIndex="-1">{metric.label}</h2>
            <p>{metric.description}</p>
          </div>
        </div>
        <p className="hero-value">{snapshot.value} <span>{snapshot.deltaLabel}</span></p>
        <p className="hero-signal">{snapshot.signal}</p>
        <dl className="provenance">
          <div><dt>Nguồn dữ liệu</dt><dd>{metric.source}</dd></div>
          <div><dt>Cập nhật lần cuối</dt><dd>10:30, 15/07/2026 · Dữ liệu demo</dd></div>
        </dl>
        <label className="comparison-toggle">
          <input type="checkbox" checked={compare} onChange={(event) => onCompareChange(event.target.checked)} />
          <span>So sánh kỳ trước</span>
        </label>
      </section>
      <section className="metric-hero-chart" aria-label={`Biểu đồ ${metric.label}`}>
        <MetricChart metric={metric} range={range} compare={compare} />
        {compare && <p className="chart-legend"><span>— Kỳ hiện tại</span><span>┄ Kỳ trước</span></p>}
      </section>
    </article>
  );
}

window.ReportMetricChart = ReportMetricChart;
window.MainKpiSelectorCard = MainKpiSelectorCard;
