/**
 * Đo lường view model (ADR-109 Amendment 1 d.6; `Measure.dc.html`,
 * `Day7.dc.html`, `Day14.dc.html`) from the P10-B measurement (contract §6)
 * — pure. Every figure comes from the measurement; nothing is estimated here.
 */

import {
  countText,
  dateText,
  dayMonth,
  kpiPair,
  rangeText,
  ratioDecimals,
  signedPct,
  signedVnd,
  valueText,
  vndText,
} from "./p10-format";
import type { FinalLabel, Measurement, MeasurementBand, MeasurementRow, MeasurementStage, MeasureUnit } from "./p10-types";
import type { ChipTone } from "./run-model";

export type MeasureTab = "d0" | "d7" | "d14";

export const MEASURE_TABS: readonly { readonly id: MeasureTab; readonly label: string; readonly slug: string }[] = [
  { id: "d0", label: "Ngày 0", slug: "ngay-0" },
  { id: "d7", label: "Ngày 7 · kiểm tra", slug: "ngay-7" },
  { id: "d14", label: "Ngày 14 · chốt", slug: "ngay-14" },
];

export function tabOfStage(stage: MeasurementStage | null): MeasureTab {
  if (stage === "day7") return "d7";
  if (stage === "final") return "d14";
  return "d0";
}

/** "CTOR Thẻ sản phẩm" → "CTOR". */
export function shortMetric(label: string): string {
  return label.split(/[\s-]/)[0] || label;
}

export interface MeasureHead {
  readonly headline: string;
  readonly chip: { readonly label: string; readonly tone: ChipTone };
}

export function measureHead(m: Measurement): MeasureHead {
  if (m.stage === "waiting") {
    return { headline: "Đang chờ dữ liệu sau khi áp dụng", chip: { label: "Chờ đo · ngày 0", tone: "muted" } };
  }
  if (m.stage === "day7") {
    if (m.day7 && m.day7.within_band === false) {
      return {
        headline: "Ngày 7: một chỉ số ra ngoài khoảng bạn cho phép",
        chip: { label: "Ngày 7 · cần bạn quyết", tone: "warn" },
      };
    }
    const main = m.rows[0];
    const trend = main ? main.verdict.toLowerCase() : "đang tiến triển";
    return {
      headline: `Ngày 7: ${shortMetric(m.target.label)} ${trend}, các chỉ số khác trong khoảng`,
      chip: { label: "Ngày 7 · trong khoảng", tone: "ok" },
    };
  }
  // Day14.dc.html: the headline and chip say the verdict.
  switch (m.final?.label) {
    case "dat":
      return { headline: "Ngày 14: đạt mục tiêu", chip: { label: "Đạt", tone: "ok" } };
    case "gan_dat":
      return { headline: "Ngày 14: gần đạt mục tiêu", chip: { label: "Gần đạt", tone: "info" } };
    case "khong_dat":
      return { headline: "Ngày 14: không đạt mục tiêu", chip: { label: "Không đạt", tone: "warn" } };
    case "chua_ket_luan":
      return { headline: "Ngày 14: chưa đủ cơ sở kết luận", chip: { label: "Chưa kết luận", tone: "muted" } };
    default:
      return { headline: "Ngày 14: kết quả đã chốt", chip: { label: "Đã chốt · ngày 14", tone: "ok" } };
  }
}

export interface TargetBlock {
  readonly label: string;
  readonly pair: string;
  readonly note: string;
  readonly gmv: string | null;
}

export function targetBlock(m: Measurement): TargetBlock {
  const t = m.target;
  const fmt = (value: number | null) => valueText(value, t.unit);
  const perDay = m.expected_gmv_per_day;
  return {
    label: `Chỉ số mục tiêu · ${t.label}`,
    pair: kpiPair(t.current, t.target, t.unit),
    note: `Đạt khi ≥ ${fmt(t.target)}; đang tiến triển từ ${fmt(t.progress_from)} trở lên`,
    gmv: perDay === null ? null : `${signedVnd(perDay)}/ngày · ${signedVnd(perDay * 30)}/tháng`,
  };
}

export interface BandRowView {
  readonly key: string;
  readonly label: string;
  readonly before: string;
  readonly band: string;
  readonly range: string;
}

export function bandRows(m: Measurement): BandRowView[] {
  return m.bands.map((band: MeasurementBand) => ({
    key: band.key,
    label: band.label,
    before: valueText(band.before, band.unit),
    band: `±${countText(band.band_pct)} %`,
    range: rangeText(band.low, band.high, band.unit),
  }));
}

export interface ResultRowView {
  readonly key: string;
  readonly name: string;
  readonly before: string;
  readonly expected: string;
  readonly actual: string;
  readonly verdict: string;
  readonly tone: "ok" | "warn" | "muted";
}

function unitOf(m: Measurement, key: string): MeasureUnit {
  const band = m.bands.find((b) => b.key === key);
  if (band) return band.unit;
  if (key === "gmv" || key.startsWith("gmv")) return "vnd";
  if (key === "aov") return "vnd";
  return m.target.unit === "vnd" ? "vnd" : "ratio";
}

/** "10.029 (+1,2 %)" for band rows; the main row and GMV as they are. */
export function resultRows(m: Measurement): ResultRowView[] {
  return m.rows.map((row: MeasurementRow, index: number) => {
    const unit = unitOf(m, row.key);
    const isGmv = row.key === "gmv" || row.key.startsWith("gmv");
    const isBand = m.bands.some((band) => band.key === row.key);
    let actual = "—";
    if (row.actual !== null) {
      if (isGmv) actual = signedVnd(row.actual);
      else if (isBand && row.before) {
        const decimals = unit === "ratio" ? ratioDecimals(row.before) : 1;
        actual = `${valueText(row.actual, unit, decimals)} (${signedPct(row.actual / row.before - 1)})`;
      }
      else actual = valueText(row.actual, unit);
    }
    return {
      key: row.key,
      name: row.label,
      before: row.before === null ? "—" : isGmv ? vndText(row.before) : valueText(row.before, unit),
      expected: row.expected,
      actual,
      verdict: row.verdict,
      tone: index === 0 && row.tone === "muted" ? "muted" : row.tone,
    };
  });
}

/** The out-of-band sentence of the "Hoàn tác?" box. */
export function breachSentence(m: Measurement): string | null {
  const out = m.rows.find((row) => row.tone === "warn" && m.bands.some((band) => band.key === row.key));
  if (!out || out.actual === null) return null;
  const band = m.bands.find((b) => b.key === out.key)!;
  const rel = out.before ? signedPct(out.actual / out.before - 1) : "";
  return `${band.label === "AOV" || out.label === "AOV" ? "AOV" : out.label} còn ${valueText(out.actual, band.unit)}${rel ? ` (${rel})` : ""}, ngoài khoảng ${rangeText(band.low, band.high, band.unit)} bạn cho phép.`;
}

export interface MeasureStep {
  readonly label: string;
  readonly result: string;
  readonly time: string;
  readonly status: "done" | "current" | "upcoming" | "warn";
}

/** Day7.dc.html's five steps, from the measurement. */
export function day7Steps(m: Measurement, answer: "revert" | "keep" | null): MeasureStep[] {
  const main = m.rows[0];
  const metric = shortMetric(m.target.label);
  const within = m.day7?.within_band ?? true;
  const fmt = (value: number | null) => valueText(value, m.target.unit);
  const outBands = m.rows.filter((row) => row.tone === "warn" && m.bands.some((band) => band.key === row.key));
  const inBands = m.bands.filter((band) => !outBands.some((row) => row.key === band.key)).map((band) => band.label);
  const day = dayMonth(m.dates.day7);
  const bandLine = within
    ? `${m.bands.map((band) => band.label).join(", ")} đều trong khoảng`
    : [
        ...outBands.map((row) => {
          const band = m.bands.find((b) => b.key === row.key)!;
          return `${row.label} ${row.actual === null ? "—" : valueText(row.actual, band.unit)} ngoài khoảng ${rangeText(band.low, band.high, band.unit)}`;
        }),
        inBands.length > 0 ? `${inBands.join(", ")} trong khoảng` : null,
      ]
        .filter(Boolean)
        .join(" · ");
  const ask = !within;
  return [
    { label: "Đọc dữ liệu 7 ngày sau thay đổi", result: "So với 14 ngày trước khi đổi", time: day, status: "done" },
    {
      label: "So chỉ số mục tiêu",
      result: `${metric} ${fmt(m.target.current)} → ${main?.actual != null ? fmt(main.actual) : "—"} · mục tiêu ${fmt(m.target.target)}${main ? ` · ${main.verdict.toLowerCase()}` : ""}`,
      time: day,
      status: "done",
    },
    { label: "So ngưỡng giữ ổn định", result: bandLine, time: day, status: within ? "done" : "warn" },
    {
      label: ask ? "Hỏi bạn: Hoàn tác?" : "Báo kết quả sơ bộ",
      result: ask
        ? answer === "revert"
          ? "Bạn chọn Hoàn tác"
          : answer === "keep"
            ? "Bạn chọn giữ thay đổi"
            : "Đang chờ bạn"
        : "Đã gửi · không cần bạn làm gì",
      time: day,
      status: ask && !answer ? "current" : "done",
    },
    {
      label: "Chờ chốt ngày 14",
      result: answer === "revert" ? "Dừng đo vì đã hoàn tác" : dateText(m.dates.day14),
      time: "",
      status: answer === "revert" ? "done" : ask && !answer ? "upcoming" : "current",
    },
  ];
}

export const FINAL_LABELS: Readonly<Record<FinalLabel, string>> = {
  dat: "Đạt",
  gan_dat: "Gần đạt",
  khong_dat: "Không đạt",
  chua_ket_luan: "Chưa kết luận",
};

export interface FinalBox {
  readonly tone: "ok" | "info" | "warn" | "muted";
  readonly title: string;
  readonly body: string;
  readonly next: string;
  readonly offerRevert: boolean;
}

/** Day14.dc.html's box per label. `leverLabel` is the change type ("Mô tả"). */
export function finalBox(m: Measurement, leverLabel: string | null): FinalBox | null {
  const f = m.final;
  if (!f) return null;
  const metric = shortMetric(m.target.label);
  const fmt = (value: number | null) => valueText(value, m.target.unit);
  const main = m.rows[0];
  const actualMetric = main?.actual ?? null;
  const expectedMonth = m.expected_gmv_per_day === null ? null : signedVnd(m.expected_gmv_per_day * 30);
  const actualMonth = f.gmv_actual_per_day === null ? null : signedVnd(f.gmv_actual_per_day * 30);
  const gmvLine =
    actualMonth && expectedMonth ? `GMV thực tế ${actualMonth}/tháng so với dự kiến ${expectedMonth}/tháng.` : "";
  const lever = leverLabel ? `"${leverLabel}"` : "này";
  const next = "Đề xuất tiếp theo cho sản phẩm này ›";
  switch (f.label) {
    case "dat":
      return {
        tone: "ok",
        title: `Đạt: ${metric} ${actualMetric === null ? "—" : fmt(actualMetric)} ≥ mục tiêu ${fmt(m.target.target)}`,
        body: `${gmvLine} Thay đổi được giữ.`.trim(),
        next,
        offerRevert: false,
      };
    case "gan_dat":
      return {
        tone: "info",
        title: `Gần đạt: ${f.pct_of_expected ?? "—"} % mức kỳ vọng`,
        body: `${gmvLine} Thay đổi được giữ; mức kỳ vọng của đề xuất ${lever} sau sẽ thận trọng hơn.`.trim(),
        next,
        offerRevert: false,
      };
    case "khong_dat": {
      const lower = actualMetric !== null && m.target.current !== null && actualMetric < m.target.current ? ", thấp hơn trước khi đổi" : "";
      return {
        tone: "warn",
        title: `Không đạt: ${metric} ${actualMetric === null ? "—" : fmt(actualMetric)}${lower}`,
        body: "Juli đề xuất hoàn tác về nội dung cũ. Bạn quyết định — Juli không tự hoàn tác.",
        next: "Xem đề xuất khác cho sản phẩm này ›",
        offerRevert: true,
      };
    }
    case "chua_ket_luan":
      return {
        tone: "muted",
        title: "Chưa kết luận: chưa đủ cơ sở kết luận",
        body: "Quá ít dữ liệu để tách tác động của thay đổi khỏi dao động thường ngày. Thay đổi được giữ; kết quả này không dùng để điều chỉnh mức kỳ vọng.",
        next,
        offerRevert: false,
      };
  }
}

const COEF = (value: number) => value.toFixed(2).replace(".", ",");

/** Day14.dc.html's six steps, from the measurement. */
export function day14Steps(m: Measurement, leverLabel: string | null): MeasureStep[] {
  const f = m.final;
  const metric = shortMetric(m.target.label);
  const fmt = (value: number | null) => valueText(value, m.target.unit);
  const main = m.rows[0];
  const day = dayMonth(m.dates.day14);
  const gmv =
    f?.gmv_actual_per_day === null || f?.gmv_actual_per_day === undefined
      ? "Không tính được"
      : `${signedVnd(f.gmv_actual_per_day)}/ngày${
          f.pct_of_expected !== null ? ` · ${f.pct_of_expected} % dự kiến` : f.label === "khong_dat" ? " · không đạt" : ""
        }`;
  const coef =
    f?.label === "chua_ket_luan" || !f?.calibration
      ? `Giữ nguyên${f?.calibration ? ` ${COEF(f.calibration.from)}` : ""}`
      : `${COEF(f.calibration.from)} → ${COEF(f.calibration.to)}`;
  return [
    { label: "Đọc dữ liệu 14 ngày sau thay đổi", result: "So với 14 ngày trước khi đổi", time: day, status: "done" },
    {
      label: "So chỉ số mục tiêu",
      result: `${metric} ${fmt(m.target.current)} → ${main?.actual != null ? fmt(main.actual) : "—"} · mục tiêu ${fmt(m.target.target)}`,
      time: day,
      status: "done",
    },
    { label: "Tính GMV thực tế", result: gmv, time: day, status: "done" },
    { label: "Chốt kết quả", result: f ? FINAL_LABELS[f.label] : "—", time: day, status: "done" },
    {
      label: `Cập nhật mức kỳ vọng cho loại "${leverLabel ?? "thay đổi này"}"`,
      result: `Hệ số hiệu chỉnh ${coef}`,
      time: day,
      status: "done",
    },
    { label: "Mở khoá đề xuất tiếp theo", result: "Sản phẩm có thể nhận thẻ mới ở Đề xuất", time: day, status: "done" },
  ];
}

export function waitingLine(m: Measurement | null, day7Iso: string | null): string {
  const date = m ? dateText(m.dates.day7) : dateText(day7Iso);
  return `Đang chờ đủ 7 ngày dữ liệu ·  Kết quả ngày ${date}.`;
}

/** Day14.dc.html's footnote under the verdict. */
export const FINAL_RULE_NOTE =
  "Cách chốt: Đạt khi chỉ số mục tiêu ≥ mục tiêu và GMV ≥ 100 % dự kiến · Gần đạt 70–99 % · Không đạt dưới 70 % · Chưa kết luận khi dữ liệu quá ít hoặc có thay đổi khác cùng lúc trên sản phẩm.";
