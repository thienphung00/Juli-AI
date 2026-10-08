/**
 * Decision evidence mapper (AC-7.6) — the ONE place that reads the additive
 * P7-B fields of a `GET /v1/demo/decisions` item. The field names are not
 * final; when the backend lands, adjust the candidate key lists below and
 * nothing else.
 *
 * ASSUMED SHAPE (every field optional, all additive to `DemoDecisionItem`):
 *
 *   {
 *     ...DemoDecisionItem,
 *     diagnosis?: {
 *       stage?: string;          // code, e.g. "ctor" | "ctr" | "aov" | "before_cart"
 *       stage_label?: string;    // Vietnamese label, preferred when present
 *       lever?: string;          // code, e.g. "first_image" | "title" | "bmsm"
 *       lever_label?: string;    // Vietnamese label, preferred when present
 *     };
 *     funnel_evidence?: {
 *       window_days?: number;    // 30
 *       as_of?: string;          // ISO date of the last day in the window
 *       metrics: Array<{
 *         key: "impressions" | "ctr" | "add_to_cart_rate" | "ctor" | "aov";
 *         prior: number | null;  // daily average, 30 ngày trước
 *         last: number | null;   // daily average, 30 ngày gần đây
 *         confidence?: "Rõ" | "Tham khảo" | "Chưa đủ dữ liệu"
 *                    | "clear" | "reference" | "insufficient" | null;
 *       }>;
 *       // …or the same metrics as an object keyed by `key`.
 *     };
 *   }
 *
 * Rates (CTR, Tỷ lệ thêm vào giỏ hàng, CTOR) are fractions (0.045 = 4,5 %),
 * the ADR-108 report.json convention; AOV is đồng per SKU order.
 *
 * Tolerances: `diagnosis` may also be flat on the item (`stage`,
 * `diagnosed_stage`, `lever`); the evidence block may be named `evidence` or
 * `funnel`; values may be `prior`/`last`, `previous`/`current` or
 * `prior_30d`/`last_30d`. Anything unrecognised is dropped — the block
 * renders only when at least one metric has a number, and a raw code is
 * never shown to the seller (unknown codes are omitted).
 */

export type EvidenceMetricKey =
  | "impressions"
  | "ctr"
  | "add_to_cart_rate"
  | "ctor"
  | "aov";

export type EvidenceConfidence = "Rõ" | "Tham khảo" | "Chưa đủ dữ liệu";

export interface EvidenceMetric {
  readonly key: EvidenceMetricKey;
  /** TikTok's own Vietnamese KPI name (ADR-108 decision 1). */
  readonly label: string;
  readonly prior: number | null;
  readonly last: number | null;
  readonly confidence: EvidenceConfidence | null;
}

export interface DecisionEvidence {
  readonly stage: string | null;
  readonly lever: string | null;
  readonly metrics: readonly EvidenceMetric[];
  readonly asOf: string | null;
}

/** Candidate keys, in preference order — edit HERE when P7-B's names land. */
const DIAGNOSIS_KEYS = ["diagnosis", "stage_diagnosis"] as const;
const STAGE_LABEL_KEYS = ["stage_label", "diagnosed_stage_label"] as const;
const STAGE_CODE_KEYS = ["stage", "diagnosed_stage"] as const;
const LEVER_LABEL_KEYS = ["lever_label"] as const;
const LEVER_CODE_KEYS = ["lever"] as const;
const EVIDENCE_KEYS = ["funnel_evidence", "evidence", "funnel"] as const;
const PRIOR_KEYS = ["prior", "previous", "prior_30d", "before"] as const;
const LAST_KEYS = ["last", "current", "last_30d", "after"] as const;

export const EVIDENCE_METRIC_ORDER: readonly EvidenceMetricKey[] = [
  "impressions",
  "ctr",
  "add_to_cart_rate",
  "ctor",
  "aov",
];

export const EVIDENCE_METRIC_LABELS: Record<EvidenceMetricKey, string> = {
  impressions: "Lượt hiển thị sản phẩm",
  ctr: "CTR (Tỷ lệ nhấp)",
  add_to_cart_rate: "Tỷ lệ thêm vào giỏ hàng",
  ctor: "CTOR",
  aov: "AOV (SKU)",
};

const METRIC_ALIASES: Record<string, EvidenceMetricKey> = {
  impressions: "impressions",
  product_impressions: "impressions",
  ctr: "ctr",
  add_to_cart_rate: "add_to_cart_rate",
  atc_rate: "add_to_cart_rate",
  cart_rate: "add_to_cart_rate",
  ctor: "ctor",
  aov: "aov",
};

const STAGE_CODE_LABELS: Record<string, string> = {
  impressions: "Lượt hiển thị sản phẩm",
  ctr: "CTR (Tỷ lệ nhấp)",
  ctor: "CTOR",
  aov: "AOV (SKU)",
  card: "Thẻ sản phẩm",
  page: "Trang sản phẩm",
  before_cart: "Trước giỏ",
  after_cart: "Sau giỏ",
};

const LEVER_CODE_LABELS: Record<string, string> = {
  first_image: "Ảnh bìa",
  cover_image: "Ảnh bìa",
  image: "Hình ảnh",
  title: "Tiêu đề",
  description: "Mô tả",
  price: "Giá",
  discount: "Giảm giá sản phẩm",
  bmsm: "Mua nhiều giảm nhiều",
  voucher: "Voucher",
  shipping: "Phí vận chuyển",
};

const CONFIDENCE_ALIASES: Record<string, EvidenceConfidence> = {
  "rõ": "Rõ",
  clear: "Rõ",
  "tham khảo": "Tham khảo",
  reference: "Tham khảo",
  "chưa đủ dữ liệu": "Chưa đủ dữ liệu",
  insufficient: "Chưa đủ dữ liệu",
};

type Bag = Record<string, unknown>;

function isBag(value: unknown): value is Bag {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function firstString(source: Bag | null, keys: readonly string[]): string | null {
  if (!source) return null;
  for (const key of keys) {
    const value = source[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

function firstNumber(source: Bag, keys: readonly string[]): number | null {
  for (const key of keys) {
    const value = source[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) {
      return Number(value);
    }
  }
  return null;
}

function firstBag(source: Bag | null, keys: readonly string[]): Bag | null {
  if (!source) return null;
  for (const key of keys) {
    const value = source[key];
    if (isBag(value)) return value;
  }
  return null;
}

/** A code is shown only through its label table; a free-text Vietnamese
 *  label passes through. Snake-case codes never reach the screen. */
function labelOrCode(
  label: string | null,
  code: string | null,
  table: Record<string, string>,
): string | null {
  if (label) return label;
  if (!code) return null;
  const known = table[code.toLowerCase()];
  if (known) return known;
  return /^[a-z0-9_.-]+$/i.test(code) ? null : code;
}

function confidenceOf(value: unknown): EvidenceConfidence | null {
  if (typeof value !== "string") return null;
  return CONFIDENCE_ALIASES[value.trim().toLowerCase()] ?? null;
}

function metricEntries(raw: unknown): Array<[string, Bag]> {
  if (Array.isArray(raw)) {
    return raw
      .filter(isBag)
      .map((entry) => [String(entry.key ?? entry.metric ?? ""), entry] as [string, Bag]);
  }
  if (isBag(raw)) {
    return Object.entries(raw).filter((entry): entry is [string, Bag] => isBag(entry[1]));
  }
  return [];
}

export function mapDecisionEvidence(item: unknown): DecisionEvidence | null {
  if (!isBag(item)) return null;

  const diagnosis = firstBag(item, DIAGNOSIS_KEYS);
  const stage = labelOrCode(
    firstString(diagnosis, STAGE_LABEL_KEYS) ?? firstString(item, STAGE_LABEL_KEYS),
    firstString(diagnosis, STAGE_CODE_KEYS) ?? firstString(item, STAGE_CODE_KEYS),
    STAGE_CODE_LABELS,
  );
  const lever = labelOrCode(
    firstString(diagnosis, LEVER_LABEL_KEYS) ?? firstString(item, LEVER_LABEL_KEYS),
    firstString(diagnosis, LEVER_CODE_KEYS) ?? firstString(item, LEVER_CODE_KEYS),
    LEVER_CODE_LABELS,
  );

  const evidence = firstBag(item, EVIDENCE_KEYS) ?? firstBag(diagnosis, EVIDENCE_KEYS);
  const rawMetrics = evidence ? (evidence.metrics ?? evidence) : null;
  const byKey = new Map<EvidenceMetricKey, EvidenceMetric>();
  for (const [rawKey, entry] of metricEntries(rawMetrics)) {
    const key = METRIC_ALIASES[rawKey.toLowerCase()];
    if (!key || byKey.has(key)) continue;
    const prior = firstNumber(entry, PRIOR_KEYS);
    const last = firstNumber(entry, LAST_KEYS);
    if (prior === null && last === null) continue;
    byKey.set(key, {
      key,
      label: EVIDENCE_METRIC_LABELS[key],
      prior,
      last,
      confidence: confidenceOf(entry.confidence ?? entry.confidence_label),
    });
  }
  const metrics = EVIDENCE_METRIC_ORDER.flatMap((key) => {
    const metric = byKey.get(key);
    return metric ? [metric] : [];
  });

  if (!stage && !lever && metrics.length === 0) return null;
  return {
    stage,
    lever,
    metrics,
    asOf: evidence ? firstString(evidence, ["as_of"]) : null,
  };
}
