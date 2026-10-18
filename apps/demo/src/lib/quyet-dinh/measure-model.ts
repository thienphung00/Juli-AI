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
import type { ExternalChange, FinalLabel, Measurement, MeasurementBand, MeasurementRow, MeasurementStage, MeasureUnit } from "./p10-types";
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

const DAY7_VERDICT = {
  rising: { word: "Đang lên", tone: "ok" },
  unclear: { word: "Chưa rõ", tone: "muted" },
} as const;

const DAY14_VERDICT = {
  met: { chip: "Đạt", headline: "Ngày 14: đạt mục tiêu", tone: "ok" },
  partial: { chip: "Một phần", headline: "Ngày 14: đạt một phần", tone: "info" },
  not_met: { chip: "Không đạt", headline: "Ngày 14: không đạt mục tiêu", tone: "warn" },
} as const;

/** D31.7: a met verdict whose change is not clearly above both windows' noise. */
export const MET_UNSURE_LABEL = "Đạt · chưa chắc chắn";

function metUnsure(m: Measurement): boolean {
  const s = m.verdict?.strength;
  return m.verdict?.day14 === "met" && (s === "likely" || s === "noise");
}

/** P23 (D29.8): the day-14 verdict word when the backend sends one (D31.7: "Đạt · chưa chắc chắn"). */
export function day14VerdictLabel(m: Measurement): string | null {
  const v = m.verdict?.day14;
  if (!v || !(v in DAY14_VERDICT)) return null;
  return metUnsure(m) ? MET_UNSURE_LABEL : DAY14_VERDICT[v].chip;
}

export function measureHead(m: Measurement): MeasureHead {
  const d7 = m.verdict?.day7;
  const d14 = m.verdict?.day14;
  if (m.stage === "day7" && d7 && d7 in DAY7_VERDICT && !(m.day7 && m.day7.within_band === false)) {
    const v = DAY7_VERDICT[d7];
    return { headline: `Ngày 7: ${shortMetric(m.target.label)} ${v.word.toLowerCase()}`, chip: { label: v.word, tone: v.tone } };
  }
  if (m.stage === "final" && d14 && d14 in DAY14_VERDICT) {
    const v = DAY14_VERDICT[d14];
    return { headline: v.headline, chip: { label: day14VerdictLabel(m) ?? v.chip, tone: v.tone } };
  }
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
      return { headline: "Ngày 14: đạt một phần", chip: { label: "Một phần", tone: "info" } };
    case "khong_dat":
      return { headline: "Ngày 14: không đạt mục tiêu", chip: { label: "Không đạt", tone: "warn" } };
    case "chua_ket_luan":
      // V5: the old "Chưa kết luận" reads as "Một phần"; the headline says why.
      return { headline: "Ngày 14: chưa đủ dữ liệu để chốt rõ", chip: { label: "Một phần", tone: "muted" } };
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
  /** V8: "Bạn đặt" / "Juli gợi ý"; null when the payload does not say. */
  readonly source: string | null;
  readonly range: string;
}

/** V8: the source tag next to a Ngưỡng giữ ổn định value. */
export const BAND_SOURCE_LABELS: Readonly<Record<"seller" | "default", string>> = {
  seller: "Bạn đặt",
  default: "Juli gợi ý",
};

export function bandRows(m: Measurement): BandRowView[] {
  return m.bands.map((band: MeasurementBand) => ({
    key: band.key,
    label: band.label,
    before: valueText(band.before, band.unit),
    band: `±${countText(band.band_pct)} %`,
    source: band.source ? BAND_SOURCE_LABELS[band.source] : null,
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

/** V5: old payload labels map onto the day-14 set (Đạt / Một phần / Không đạt). */
export const FINAL_LABELS: Readonly<Record<FinalLabel, string>> = {
  dat: "Đạt",
  gan_dat: "Một phần",
  khong_dat: "Không đạt",
  chua_ket_luan: "Một phần",
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
  const next = "Đề xuất tiếp theo cho sản phẩm này ›";
  const v = m.verdict?.day14;
  const label: FinalLabel = v === "met" ? "dat" : v === "partial" ? "gan_dat" : v === "not_met" ? "khong_dat" : f.label;
  switch (label) {
    case "dat":
      return {
        tone: "ok",
        title: `${metUnsure(m) ? MET_UNSURE_LABEL : "Đạt"}: ${metric} ${actualMetric === null ? "—" : fmt(actualMetric)} ≥ mục tiêu ${fmt(m.target.target)}`,
        body: `${gmvLine} Thay đổi được giữ.`.trim(),
        next,
        offerRevert: false,
      };
    case "gan_dat":
      return {
        tone: "info",
        title: `Một phần: ${f.pct_of_expected ?? "—"} % GMV dự kiến`,
        body: `${gmvLine} Thay đổi được giữ.`.trim(),
        next,
        offerRevert: false,
      };
    case "khong_dat": {
      const lower = actualMetric !== null && m.target.current !== null && actualMetric < m.target.current ? ", thấp hơn trước khi đổi" : "";
      return {
        tone: "warn",
        title: `Không đạt: ${metric} ${actualMetric === null ? "—" : fmt(actualMetric)}${lower}`,
        body: "Juli đề xuất hoàn tác về nội dung cũ. Bạn quyết định, Juli không tự hoàn tác.",
        next: "Xem đề xuất khác cho sản phẩm này ›",
        offerRevert: true,
      };
    }
    case "chua_ket_luan":
      return {
        tone: "muted",
        title: "Một phần: chưa đủ dữ liệu để chốt rõ",
        body: "Quá ít dữ liệu để tách tác động của thay đổi khỏi dao động thường ngày. Thay đổi được giữ.",
        next,
        offerRevert: false,
      };
  }
}

/**
 * Day14.dc.html's steps, from the measurement. D61: the calibration step (the lever's
 * coefficient) is not shown to sellers; `leverLabel` is kept for the callers.
 */
export function day14Steps(m: Measurement, _leverLabel: string | null): MeasureStep[] {
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
  return [
    { label: "Đọc dữ liệu 14 ngày sau thay đổi", result: "So với 14 ngày trước khi đổi", time: day, status: "done" },
    {
      label: "So chỉ số mục tiêu",
      result: `${metric} ${fmt(m.target.current)} → ${main?.actual != null ? fmt(main.actual) : "—"} · mục tiêu ${fmt(m.target.target)}`,
      time: day,
      status: "done",
    },
    { label: "Tính GMV thực tế", result: gmv, time: day, status: "done" },
    { label: "Chốt kết quả", result: day14VerdictLabel(m) ?? (f ? FINAL_LABELS[f.label] : "—"), time: day, status: "done" },
    { label: "Mở khoá đề xuất tiếp theo", result: "Sản phẩm có thể nhận thẻ mới ở Đề xuất", time: day, status: "done" },
  ];
}

export function waitingLine(m: Measurement | null, day7Iso: string | null): string {
  const date = m ? dateText(m.dates.day7) : dateText(day7Iso);
  return `Đang chờ đủ 7 ngày dữ liệu ·  Kết quả ngày ${date}.`;
}

/** Day14.dc.html's footnote under the verdict. */
export const FINAL_RULE_NOTE =
  "Cách chốt: Đạt khi chỉ số mục tiêu tăng rõ, chạm mục tiêu và GMV giữ được · Đạt · chưa chắc chắn khi đạt nhưng mức tăng chưa đủ rõ để loại trừ may rủi · Một phần khi chỉ tăng rõ hoặc chỉ chạm mục tiêu, hoặc khi dữ liệu quá ít · Không đạt khi không tăng rõ và không chạm mục tiêu.";

const FIELD_NAMES: Readonly<Record<string, string>> = {
  title: "Tiêu đề",
  description: "Mô tả",
  main_images: "Ảnh",
  images: "Ảnh",
  cover_image: "Ảnh bìa",
  video: "Video",
  price: "Giá",
  sku_price: "Giá",
  skus: "SKU",
  attributes: "Thuộc tính",
  product_attributes: "Thuộc tính",
  category: "Ngành hàng",
  category_id: "Ngành hàng",
};

const PROMO_NAMES: Readonly<Record<string, string>> = {
  flash_sale: "Flash sale",
  flashsale: "Flash sale",
  product_discount: "Giảm giá SP",
  direct_discount: "Giảm giá SP",
  fixed_price: "Giảm giá SP",
  buy_more_save_more: "Mua nhiều giảm nhiều",
  bmsm: "Mua nhiều giảm nhiều",
  shipping_discount: "Giảm phí ship",
  voucher: "Voucher",
  coupon: "Voucher",
};

function externalText(change: ExternalChange): string {
  const kind = (change.kind ?? "").toLowerCase();
  const fields = (change.fields ?? []).map((f) => String(f).toLowerCase());
  const promo = [...fields, kind.replace(/^(promotion|activity)_?/, "")].map((f) => PROMO_NAMES[f]).find(Boolean);
  if (promo || kind.startsWith("promotion") || kind.startsWith("activity")) {
    const verb = /end|deactivat|stop|expire/.test(kind) ? "kết thúc" : /update|change/.test(kind) ? "thay đổi" : "bắt đầu";
    return `${promo ?? "Khuyến mãi"} ${verb}`;
  }
  if (kind.includes("price") && fields.length === 0) return "Giá đổi ngoài Juli";
  const names = [...new Set(fields.map((f) => FIELD_NAMES[f]).filter(Boolean))];
  if (names.length === 0) return "Sản phẩm sửa ngoài Juli";
  const joined = names.map((n, i) => (i === 0 || n === "SKU" ? n : n.toLowerCase())).join(", ");
  return `${joined} sửa ngoài Juli`;
}

/**
 * P23 (D30.4): "Bị ảnh hưởng bởi thay đổi khác" lines ("Tiêu đề sửa ngoài Juli · 12/10",
 * "Flash sale bắt đầu · 14/10"), oldest first; null when nothing overlaps.
 */
export function externalChangeLines(m: Measurement): string[] | null {
  const changes = m.external_changes ?? [];
  if (!m.verdict?.affected_by_external_change && changes.length === 0) return null;
  return [...changes]
    .sort((a, b) => Date.parse(a.occurred_at ?? "") - Date.parse(b.occurred_at ?? ""))
    .map((change) => {
      const date = dayMonth(change.occurred_at);
      return date === "—" ? externalText(change) : `${externalText(change)} · ${date}`;
    });
}

export const EXTERNAL_CHANGE_TITLE = "Bị ảnh hưởng bởi thay đổi khác";
