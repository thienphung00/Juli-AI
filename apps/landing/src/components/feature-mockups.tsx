/**
 * Feature mockups rebuilt in code from the Figma reference — never shipped as
 * flattened bitmaps (MODULE.md invariant). Numbers are illustrative mock data,
 * consistent with the Figma frames.
 */

const DONUT_SEGMENTS = [
  { key: "good", label: "Tốt", value: 68, className: "lp-donut__segment--good" },
  { key: "mid", label: "Trung bình", value: 25, className: "lp-donut__segment--mid" },
  { key: "low", label: "Thấp", value: 7, className: "lp-donut__segment--low" },
] as const;

function DonutChart() {
  const radius = 15.9155; // circumference ≈ 100 → percentages map to dash lengths
  // Segment N starts where the previous ones end; 25 aligns the first with 12 o'clock.
  const offsets = DONUT_SEGMENTS.map((_, index) =>
    DONUT_SEGMENTS.slice(0, index).reduce(
      (offset, previous) => offset - previous.value,
      25,
    ),
  );
  return (
    <svg aria-hidden="true" className="lp-donut" viewBox="0 0 42 42">
      {DONUT_SEGMENTS.map((segment, index) => (
        <circle
          className={`lp-donut__segment ${segment.className}`}
          cx="21"
          cy="21"
          fill="none"
          key={segment.key}
          r={radius}
          strokeDasharray={`${segment.value} ${100 - segment.value}`}
          strokeDashoffset={offsets[index]}
          strokeWidth="6"
        />
      ))}
    </svg>
  );
}

function Sparkline() {
  return (
    <svg aria-hidden="true" className="lp-sparkline" preserveAspectRatio="none" viewBox="0 0 120 36">
      <path
        className="lp-sparkline__fill"
        d="M0 30 L14 26 L28 28 L42 21 L56 23 L70 16 L84 18 L98 10 L120 4 L120 36 L0 36 Z"
      />
      <path
        className="lp-sparkline__line"
        d="M0 30 L14 26 L28 28 L42 21 L56 23 L70 16 L84 18 L98 10 L120 4"
        fill="none"
      />
    </svg>
  );
}

export function AnalyticsMockup() {
  return (
    <div aria-hidden="true" className="lp-mockup">
      <div className="lp-mockup__panel">
        <p className="lp-mockup__panel-title">Sức khỏe tồn kho</p>
        <div className="lp-mockup__donut-row">
          <DonutChart />
          <ul className="lp-mockup__legend">
            {DONUT_SEGMENTS.map((segment) => (
              <li className="lp-mockup__legend-row" key={segment.key}>
                <span className={`lp-mockup__legend-dot lp-mockup__legend-dot--${segment.key}`} />
                {segment.label}
                <strong className="lp-mockup__legend-value">{segment.value}%</strong>
              </li>
            ))}
          </ul>
        </div>
      </div>
      <div className="lp-mockup__panel">
        <p className="lp-mockup__panel-title">Dự báo doanh thu (7 ngày tới)</p>
        <p className="lp-mockup__kpi">
          2.92B <span className="lp-mockup__delta">+16%</span>
        </p>
        <Sparkline />
      </div>
      <div className="lp-mockup__panel lp-mockup__panel--info">
        <p className="lp-mockup__chip lp-mockup__chip--info">✦ AI Insight</p>
        <p className="lp-mockup__panel-title">Doanh thu dự kiến tăng 18%</p>
        <p className="lp-mockup__panel-body">
          Phát hiện rủi ro tồn kho với 23 sản phẩm. Đề xuất nhập thêm để tối ưu
          doanh thu.
        </p>
        <p className="lp-mockup__panel-body">
          Đề xuất nhập thêm <strong className="lp-mockup__accent">320 sản phẩm</strong>
        </p>
      </div>
    </div>
  );
}

export function SuggestionsMockup() {
  return (
    <div aria-hidden="true" className="lp-mockup">
      <div className="lp-mockup__panel lp-mockup__panel--tinted">
        <p className="lp-mockup__chip">Ưu tiên cao</p>
        <div className="lp-mockup__media-row">
          <div>
            <p className="lp-mockup__panel-title">
              Tăng doanh thu với sản phẩm có hiệu suất cao
            </p>
            <p className="lp-mockup__panel-body">
              Đẩy mạnh quảng cáo và ưu đãi cho 23 sản phẩm đang có nhu cầu cao.
            </p>
            <p className="lp-mockup__kpi-small">
              Dự kiến doanh thu tăng{" "}
              <strong className="lp-mockup__accent">+18%</strong>
            </p>
          </div>
        </div>
        <span className="lp-mockup__button">Xem chi tiết</span>
      </div>
      <div className="lp-mockup__panel">
        <p className="lp-mockup__chip lp-mockup__chip--info">Tối ưu tồn kho</p>
        <div className="lp-mockup__media-row">
          <div>
            <p className="lp-mockup__panel-title">Bổ sung tồn kho kịp thời</p>
            <p className="lp-mockup__panel-body">
              23 sản phẩm có nguy cơ hết hàng trong 7 ngày tới. Đặt hàng sớm để
              tránh mất doanh thu.
            </p>
            <p className="lp-mockup__kpi-small">
              Đề xuất nhập thêm{" "}
              <strong className="lp-mockup__accent">320 sản phẩm</strong>
            </p>
          </div>
        </div>
        <span className="lp-mockup__button lp-mockup__button--secondary">Tạo đơn nhập</span>
      </div>
    </div>
  );
}

export function ExecutionMockup() {
  return (
    <div aria-hidden="true" className="lp-mockup">
      <div className="lp-mockup__panel lp-mockup__panel--tinted">
        <p className="lp-mockup__chip">Đang thực hiện</p>
        <div className="lp-mockup__media-row">
          <div>
            <p className="lp-mockup__panel-title">Tạo đơn nhập kho tự động</p>
            <p className="lp-mockup__panel-body">
              Đơn nhập 320 sản phẩm đã được tạo và gửi đến nhà cung cấp.
            </p>
          </div>
        </div>
        <div className="lp-mockup__progress">
          <span className="lp-mockup__progress-fill" style={{ width: "75%" }} />
        </div>
        <p className="lp-mockup__progress-label">75%</p>
      </div>
      <div className="lp-mockup__panel">
        <p className="lp-mockup__chip">Đang thực hiện</p>
        <div className="lp-mockup__media-row">
          <div>
            <p className="lp-mockup__panel-title">Cập nhật giá sản phẩm</p>
            <p className="lp-mockup__panel-body">
              Đang cập nhật giá cho 156 sản phẩm dựa trên phân tích thị trường.
            </p>
          </div>
        </div>
        <div className="lp-mockup__progress">
          <span className="lp-mockup__progress-fill" style={{ width: "60%" }} />
        </div>
        <p className="lp-mockup__progress-label">60%</p>
      </div>
    </div>
  );
}

export function ResultsMockup() {
  return (
    <div aria-hidden="true" className="lp-mockup">
      <div className="lp-mockup__panel lp-mockup__panel--tinted">
        <p className="lp-mockup__chip lp-mockup__chip--warning">Lên lịch</p>
        <div className="lp-mockup__media-row">
          <div>
            <p className="lp-mockup__panel-title">Chương trình khuyến mãi</p>
            <p className="lp-mockup__panel-body">
              Flash sale 20% sẽ được kích hoạt vào 20:00 hôm nay.
            </p>
          </div>
          <span className="lp-mockup__time">20:00</span>
        </div>
      </div>
      <div className="lp-mockup__panel">
        <p className="lp-mockup__chip lp-mockup__chip--success">Đã hoàn thành</p>
        <div className="lp-mockup__media-row">
          <div>
            <p className="lp-mockup__panel-title">Đẩy khuyến mãi mùa hè</p>
            <p className="lp-mockup__panel-body">
              Chương trình đã được kích hoạt thành công và đang hoạt động tốt.
            </p>
            <p className="lp-mockup__panel-body lp-mockup__panel-body--meta">Hôm qua, 10:30</p>
          </div>
          <span aria-hidden="true" className="lp-mockup__check">
            ✓
          </span>
        </div>
      </div>
    </div>
  );
}
