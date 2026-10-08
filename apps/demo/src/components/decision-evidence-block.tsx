import type {
  DecisionEvidence,
  EvidenceConfidence,
  EvidenceMetric,
} from "../lib/decision-evidence";
import { change, money, num, pct, slashDate } from "../lib/vn-format";

/**
 * The funnel evidence on a Quyết định card (AC-7.6): the diagnosed stage, the
 * lever, and the product's funnel KPIs — 30 ngày gần đây vs 30 ngày trước,
 * daily averages, each with its confidence label. Rendered only when the
 * mapper (`lib/decision-evidence.ts`) found something to show.
 */

export const CONFIDENCE_BADGE: Record<EvidenceConfidence, string> = {
  "Rõ": "badge badge-success",
  "Tham khảo": "badge badge-warning",
  "Chưa đủ dữ liệu": "badge badge-neutral",
};

function formatMetric(metric: EvidenceMetric, value: number | null): string {
  if (metric.key === "impressions") return num(value);
  if (metric.key === "aov") return money(value);
  return pct(value);
}

export function DecisionEvidenceBlock({ evidence }: { readonly evidence: DecisionEvidence }) {
  return (
    <div className="decision-evidence" data-testid="decision-evidence">
      {(evidence.stage || evidence.lever) && (
        <dl className="decision-evidence__diagnosis">
          {evidence.stage && (
            <div>
              <dt>Giai đoạn cần cải thiện</dt>
              <dd>{evidence.stage}</dd>
            </div>
          )}
          {evidence.lever && (
            <div>
              <dt>Hướng tác động</dt>
              <dd>{evidence.lever}</dd>
            </div>
          )}
        </dl>
      )}
      {evidence.metrics.length > 0 && (
        <div className="decision-evidence__table-wrap">
          <table className="decision-evidence__table">
            <caption>
              Phễu của sản phẩm · trung bình mỗi ngày
              {evidence.asOf ? ` · đến ${slashDate(evidence.asOf)}` : ""}
            </caption>
            <thead>
              <tr>
                <th scope="col">Chỉ số</th>
                <th scope="col">30 ngày trước</th>
                <th scope="col">30 ngày gần đây</th>
                <th scope="col">Thay đổi</th>
                <th scope="col">Mức tin cậy</th>
              </tr>
            </thead>
            <tbody>
              {evidence.metrics.map((metric) => {
                const delta = change(metric.prior, metric.last);
                return (
                  <tr key={metric.key}>
                    <th scope="row">{metric.label}</th>
                    <td>{formatMetric(metric, metric.prior)}</td>
                    <td>{formatMetric(metric, metric.last)}</td>
                    <td>
                      <span className={`change-chip change-chip--${delta.tone}`}>
                        {delta.text}
                      </span>
                    </td>
                    <td>
                      {metric.confidence ? (
                        <span className={CONFIDENCE_BADGE[metric.confidence]}>
                          {metric.confidence}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
