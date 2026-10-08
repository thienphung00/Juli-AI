import type {
  DecisionEvidence,
  EvidenceConfidence,
  EvidenceMetric,
} from "../lib/decision-evidence";
import { money, num, pct, slashDate, type ChangeTone } from "../lib/vn-format";

/**
 * The Optimize Product evidence on a Quyết định card (AC-7.6): the diagnosed
 * stage, the lever, the trigger, the rule-based recoverable GMV, and the
 * product's funnel KPIs — N ngày trước vs N ngày gần đây, daily averages,
 * each with its confidence label. Rendered only for cards that carry an
 * ADR-106 diagnosis (see `lib/decision-evidence.ts`).
 */

export const CONFIDENCE_BADGE: Record<EvidenceConfidence, string> = {
  "Rõ": "badge badge-success",
  "Tham khảo": "badge badge-warning",
  "Chưa đủ dữ liệu": "badge badge-neutral",
};

function formatValue(metric: EvidenceMetric, value: number | null): string {
  if (metric.unit === "ratio") return pct(value);
  if (metric.unit === "vnd") return money(value);
  return num(value);
}

/** Relative change (`current ÷ previous − 1`, as the backend sends it). */
function formatChange(ratio: number | null): { text: string; tone: ChangeTone } {
  if (ratio === null) return { text: "—", tone: "flat" };
  const tone: ChangeTone = ratio > 0.005 ? "up" : ratio < -0.005 ? "down" : "flat";
  const sign = ratio >= 0 ? "+" : "−";
  return { text: `${sign}${num(Math.abs(ratio) * 100, 1)} %`, tone };
}

export function recoverableSentence(value: number): string {
  return `Có thể lấy lại khoảng ${money(value)} GMV mỗi ngày (ước tính theo quy tắc, chưa phải mô hình)`;
}

export function DecisionEvidenceBlock({ evidence }: { readonly evidence: DecisionEvidence }) {
  const days = evidence.windowDays;
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
      {evidence.trigger && (
        <p className="decision-evidence__trigger">{evidence.trigger}</p>
      )}
      {evidence.recoverableGmvPerDay !== null && (
        <p className="decision-card__impact" data-testid="decision-recoverable-gmv">
          <strong>{recoverableSentence(evidence.recoverableGmvPerDay)}</strong>
        </p>
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
                <th scope="col">{days} ngày trước</th>
                <th scope="col">{days} ngày gần đây</th>
                <th scope="col">Thay đổi</th>
                <th scope="col">Mức tin cậy</th>
              </tr>
            </thead>
            <tbody>
              {evidence.metrics.map((metric) => {
                const delta = formatChange(metric.change);
                return (
                  <tr key={metric.key}>
                    <th scope="row">
                      {metric.label}
                      {metric.note && (
                        <span className="decision-evidence__note">{metric.note}</span>
                      )}
                    </th>
                    <td>{formatValue(metric, metric.previous)}</td>
                    <td>{formatValue(metric, metric.current)}</td>
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
      {evidence.notes.length > 0 && (
        <ul className="decision-evidence__notes">
          {evidence.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
