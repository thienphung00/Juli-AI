// Current four-destination demonstration. Historical source examples are provenance,
// not authority for this composition.
const MAIN_KPIS = [
  {
    metricKey: "sps",
    category: "Trạng thái shop",
    label: "SPS",
    description: "Điểm hiệu suất và tiến độ sức khỏe shop.",
    symbol: "S",
    available: false,
    missingSource: "TikTok Shop Account health",
    activation: "KPI sẽ hoạt động sau khi hợp đồng dữ liệu chính thức được xác minh và kết nối.",
  },
  {
    metricKey: "net-revenue",
    category: "Doanh thu",
    label: "Net Revenue",
    description: "Doanh thu thuần sau hoàn tiền và điều chỉnh.",
    symbol: "₫",
    available: true,
    chartType: "forecast",
    source: "Đơn hàng và hoàn tiền TikTok Shop",
    ranges: {
      7: { value: "84,2tr₫", deltaLabel: "▲ 4,8%", numericValue: 84, points: [26, 34, 31, 45], forecast: [45, 52, 58, 64], signal: "Doanh thu tăng 4,8% → đà tăng ổn định → tiếp tục theo dõi sản phẩm dẫn đầu." },
      30: { value: "342,8tr₫", deltaLabel: "▲ 12,4%", numericValue: 88, points: [22, 32, 44, 57], forecast: [57, 64, 70, 76], signal: "Doanh thu tăng 12,4% → cơ hội tăng trưởng → ưu tiên sản phẩm có biên lợi nhuận tốt." },
      90: { value: "968,5tr₫", deltaLabel: "▲ 18,1%", numericValue: 92, points: [18, 28, 47, 62], forecast: [62, 69, 77, 82], signal: "Doanh thu tăng 18,1% → tăng trưởng dài hạn tích cực → duy trì nhịp bổ sung hàng." },
    },
  },
  {
    metricKey: "roas",
    category: "Quảng cáo",
    label: "ROAS",
    description: "Hiệu quả doanh thu trên chi tiêu quảng cáo.",
    symbol: "↗",
    available: false,
    missingSource: "TikTok Promotion API",
    activation: "KPI sẽ hoạt động sau khi luồng dữ liệu Promotion API được kết nối.",
  },
  {
    metricKey: "inventory-turnover",
    category: "Tồn kho",
    label: "Inventory Turnover",
    description: "Tốc độ bán và thay mới lượng hàng tồn.",
    symbol: "↻",
    available: true,
    chartType: "forecast",
    source: "Sản phẩm, tồn kho và đơn hàng TikTok Shop",
    ranges: {
      7: { value: "5,8×", deltaLabel: "▲ 0,3×", numericValue: 78, points: [38, 44, 50, 55], forecast: [55, 58, 61, 63], signal: "Vòng quay tăng 0,3× → vốn lưu động cải thiện → giữ mức bổ sung hàng hiện tại." },
      30: { value: "5,4×", deltaLabel: "▼ 0,4×", numericValue: 72, points: [60, 54, 49, 45], forecast: [45, 42, 39, 37], signal: "Vòng quay giảm 0,4× → rủi ro vốn mắc kẹt → kiểm tra SKU bán chậm." },
      90: { value: "5,1×", deltaLabel: "▼ 0,7×", numericValue: 68, points: [64, 57, 49, 42], forecast: [42, 39, 36, 34], signal: "Vòng quay giảm 0,7× → hàng tồn lâu hơn → ưu tiên xử lý lượng dư." },
    },
  },
  {
    metricKey: "fulfillment-accuracy-rate",
    category: "Vận hành",
    label: "Fulfillment Accuracy Rate",
    description: "Tỷ lệ đơn được xử lý đúng sản phẩm và số lượng.",
    symbol: "✓",
    available: true,
    chartType: "gauge",
    source: "Đơn hàng và dữ liệu fulfillment TikTok Shop",
    ranges: {
      7: { value: "98,8%", deltaLabel: "▲ 0,4%", numericValue: 98.8, points: [], forecast: [], signal: "Độ chính xác tăng 0,4% → vận hành ổn định → duy trì kiểm tra trước bàn giao." },
      30: { value: "97,6%", deltaLabel: "▼ 0,8%", numericValue: 97.6, points: [], forecast: [], signal: "Độ chính xác giảm 0,8% → lỗi xử lý đang tăng → rà soát các đơn sai gần đây." },
      90: { value: "97,9%", deltaLabel: "▲ 0,2%", numericValue: 97.9, points: [], forecast: [], signal: "Độ chính xác tăng 0,2% → chất lượng phục hồi → tiếp tục theo dõi lỗi lặp lại." },
    },
  },
  {
    metricKey: "csat",
    category: "Chăm sóc khách hàng",
    label: "CSAT",
    description: "Mức hài lòng của khách hàng sau mua.",
    symbol: "☺",
    available: false,
    missingSource: "Đánh giá hoặc hội thoại người mua hợp pháp",
    activation: "KPI sẽ hoạt động khi có nguồn văn bản hợp pháp và hợp đồng sử dụng rõ ràng.",
  },
];

const MOCK_RECOMMENDATION = {
  headline: "Xử lý ba đơn hàng sắp quá hạn giao",
  impact: "Giảm 3 đơn trễ hạn",
  reasoning: "Ba đơn hàng còn dưới 6 giờ để bàn giao. Phê duyệt mở quy trình với danh sách đơn được điền sẵn để bạn kiểm tra trước khi thực thi.",
};

function AppHeader({ shopName }) {
  return (
    <header className="app-header" style={{ position: "sticky", top: 0, zIndex: 40, padding: "14px 16px" }}>
      <div style={{ maxWidth: 1120, margin: "0 auto", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span className="brand-wordmark brand-wordmark-sm">Juli</span>
        <span style={{ fontSize: 13, color: "var(--muted-foreground)" }}>{shopName}</span>
      </div>
    </header>
  );
}

function JuliAssist({ children }) {
  return (
    <aside style={{ borderRadius: 12, border: "1px solid color-mix(in srgb, var(--info) 24%, var(--border))", background: "color-mix(in srgb, var(--info) 6%, transparent)", padding: 12, fontSize: 13 }}>
      <strong style={{ color: "var(--info)" }}>Juli hỗ trợ</strong>
      <p style={{ margin: "4px 0 0" }}>{children}</p>
    </aside>
  );
}

function HomeTab({ onNavigate }) {
  const launchers = [
    { id: "decisions", title: "Quyết định", copy: "Xem đề xuất cần bạn xem xét và theo dõi quy trình đang thực hiện." },
    { id: "analytics", title: "Phân tích", copy: "Mở báo cáo, KPI, sức khỏe shop và xu hướng hiệu suất." },
  ];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <h1 style={{ fontSize: 20, margin: "0 0 6px" }}>Chào bạn</h1>
        <p style={{ color: "var(--muted-foreground)", fontSize: 14, margin: 0 }}>Bạn muốn bắt đầu từ đâu?</p>
      </div>
      {launchers.map((launcher) => (
        <button key={launcher.id} className="card card-interactive" onClick={() => onNavigate(launcher.id)} style={{ minHeight: 150, padding: 20, textAlign: "left", background: "var(--card)", color: "var(--foreground)" }}>
          <h2 style={{ fontSize: 18, margin: "0 0 8px" }}>{launcher.title}</h2>
          <p style={{ color: "var(--muted-foreground)", fontSize: 14, margin: 0 }}>{launcher.copy}</p>
          <span style={{ display: "inline-block", marginTop: 20, color: "var(--primary)", fontWeight: 700 }}>Mở →</span>
        </button>
      ))}
    </div>
  );
}

function DecisionsTab({ workflow, setWorkflow }) {
  const [subTab, setSubTab] = React.useState("recommendations");
  const hasWorkflow = workflow && typeof workflow === "object";
  const approve = () => {
    setWorkflow({ workflow_id: "fulfill-three-orders", title: "Xử lý ba đơn hàng sắp quá hạn giao", status: "needs_input", estimated_impact: { value: "3 đơn đúng hạn", metric: "" } });
    setSubTab("in-progress");
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <h1 style={{ fontSize: 18, fontWeight: 700, letterSpacing: "-0.02em", margin: 0 }}>Quyết định</h1>

      <div role="tablist" style={{ display: "flex", gap: 8, borderBottom: "1px solid var(--border)" }}>
        {[
          { id: "recommendations", label: "Đề xuất" },
          { id: "in-progress", label: "Đang thực hiện" },
        ].map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={subTab === t.id}
            onClick={() => setSubTab(t.id)}
            style={{
              border: "none",
              background: "transparent",
              padding: "8px 4px",
              fontSize: 14,
              fontWeight: 600,
              cursor: "pointer",
              color: subTab === t.id ? "var(--primary)" : "var(--muted-foreground)",
              borderBottom: subTab === t.id ? "2px solid var(--primary)" : "2px solid transparent",
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {subTab === "recommendations" ? (
        hasWorkflow ? (
          <p className="card" style={{ padding: 16, color: "var(--muted-foreground)", fontSize: 14 }}>Đề xuất đã được phê duyệt. Theo dõi trong Đang thực hiện.</p>
        ) : workflow === "rejected" ? (
          <p className="card" style={{ padding: 16, color: "var(--muted-foreground)", fontSize: 14 }}>Đề xuất đã được từ chối và gỡ khỏi danh sách.</p>
        ) : (
          <window.HomeAiRecommendationCard recommendation={MOCK_RECOMMENDATION} onApprove={approve} onReject={() => setWorkflow("rejected")} />
        )
      ) : (
        hasWorkflow
          ? <window.InProgressDecisionCard decision={workflow} onAdvance={() => setWorkflow({ ...workflow, status: workflow.status === "needs_input" ? "executing" : "completed" })} />
          : <p className="card" style={{ padding: 16, color: "var(--muted-foreground)", fontSize: 14 }}>Chưa có quyết định nào đang thực hiện.</p>
      )}
      <JuliAssist>Hỏi về lý do đề xuất hoặc bước thực thi hiện tại ngay trong ngữ cảnh này.</JuliAssist>
    </div>
  );
}

function analyticsRoute(metricKey) {
  return `/analytics/${metricKey}`;
}

function writeAnalyticsRoute(metricKey, replace = false) {
  const route = analyticsRoute(metricKey);
  const nextUrl = /^https?:$/.test(window.location.protocol) ? route : `${window.location.pathname}#${route}`;
  window.history[replace ? "replaceState" : "pushState"]({ metricKey }, "", nextUrl);
}

function AnalyticsTab() {
  const [selectedKey, setSelectedKey] = React.useState("net-revenue");
  const [gridKeys, setGridKeys] = React.useState(["sps", "roas", "inventory-turnover", "fulfillment-accuracy-rate", "csat"]);
  const [range, setRange] = React.useState(30);
  const [compare, setCompare] = React.useState(false);
  const heroHeadingRef = React.useRef(null);
  const selectedMetric = MAIN_KPIS.find((metric) => metric.metricKey === selectedKey);

  React.useEffect(() => {
    writeAnalyticsRoute("net-revenue", true);
  }, []);

  React.useEffect(() => {
    const restoreSelection = (event) => {
      const key = event.state?.metricKey;
      const metric = MAIN_KPIS.find((item) => item.metricKey === key && item.available);
      if (!metric || metric.metricKey === selectedKey) return;
      setGridKeys((keys) => keys.map((item) => item === metric.metricKey ? selectedKey : item));
      setSelectedKey(metric.metricKey);
      setCompare(false);
    };
    window.addEventListener("popstate", restoreSelection);
    return () => window.removeEventListener("popstate", restoreSelection);
  }, [selectedKey]);

  const selectMetric = (metricKey, shouldMoveFocus) => {
    const index = gridKeys.indexOf(metricKey);
    if (index < 0) return;
    const nextGrid = [...gridKeys];
    nextGrid[index] = selectedKey;
    setGridKeys(nextGrid);
    setSelectedKey(metricKey);
    setCompare(false);
    writeAnalyticsRoute(metricKey);
    if (shouldMoveFocus) requestAnimationFrame(() => heroHeadingRef.current?.focus());
  };

  return (
    <div className="analytics-layout">
      <div className="analytics-toolbar">
        <div>
          <h1 style={{ fontSize: 20, margin: 0 }}>Phân tích</h1>
          <p className="text-muted" style={{ margin: "4px 0 0", fontSize: 13 }}>Sáu KPI chính của shop · dữ liệu demo</p>
        </div>
        <div className="range-control" role="group" aria-label="Khoảng thời gian">
          {[7, 30, 90].map((days) => (
            <button key={days} type="button" aria-pressed={range === days} onClick={() => setRange(days)}>{days} ngày</button>
          ))}
        </div>
      </div>
      <window.ReportMetricChart metric={selectedMetric} range={range} compare={compare} onCompareChange={setCompare} headingRef={heroHeadingRef} />
      <section aria-labelledby="other-kpis-title">
        <h2 id="other-kpis-title" style={{ fontSize: 16, margin: "4px 0 12px" }}>KPI chính khác</h2>
        <div className="metric-grid">
          {gridKeys.map((metricKey) => {
            const metric = MAIN_KPIS.find((item) => item.metricKey === metricKey);
            return <window.MainKpiSelectorCard key={metric.metricKey} metric={metric} range={range} onSelect={(shouldMoveFocus) => selectMetric(metric.metricKey, shouldMoveFocus)} />;
          })}
        </div>
      </section>
      <JuliAssist>Tôi có thể giải thích biến động hoặc liên kết một tín hiệu với đề xuất liên quan.</JuliAssist>
    </div>
  );
}

function SettingsTab() {
  return (
    <div style={{ display: "grid", gap: 12 }}>
      <h1 style={{ fontSize: 18, margin: 0 }}>Cài đặt</h1>
      <section className="card" style={{ padding: 16 }}>
        <h2 style={{ fontSize: 16, marginTop: 0 }}>Mẫu quy trình và ngưỡng</h2>
        <label htmlFor="deadline-threshold" style={{ display: "block", fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Cảnh báo đơn sắp quá hạn</label>
        <input id="deadline-threshold" className="field-input" defaultValue="6 giờ" />
        <button type="button" className="btn-primary" style={{ width: "100%", marginTop: 12 }}>Lưu cài đặt</button>
      </section>
      <JuliAssist>Tôi có thể giải thích ngưỡng này ảnh hưởng đến đề xuất nào.</JuliAssist>
    </div>
  );
}

function App() {
  const [active, setActive] = React.useState("home");
  const [workflow, setWorkflow] = React.useState(null);
  return (
    <div style={{ minHeight: "100vh", background: "var(--background)", paddingBottom: 84 }}>
      <AppHeader shopName="Cửa hàng Hoa Mai" />
      <main className="app-main">
        {active === "home" && <HomeTab onNavigate={setActive} />}
        {active === "decisions" && <DecisionsTab workflow={workflow} setWorkflow={setWorkflow} />}
        {active === "analytics" && <AnalyticsTab />}
        {active === "settings" && <SettingsTab />}
      </main>
      <window.NavBar active={active} onNavigate={setActive} />
    </div>
  );
}

window.App = App;
