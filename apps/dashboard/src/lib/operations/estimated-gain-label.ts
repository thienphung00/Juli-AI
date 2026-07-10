import { formatNumber, formatVND } from "@/lib/format";

const APPROVAL_SUFFIX = "nếu phê duyệt";

/** Formats a numeric delta with explicit +/−/0 sign (no "+-" artifacts). */
export function formatSignedDelta(delta: number, fractionDigits = 0): string {
  const factor = 10 ** fractionDigits;
  const rounded = Math.round(delta * factor) / factor;

  if (rounded === 0) {
    return fractionDigits > 0 ? (0).toFixed(fractionDigits) : "0";
  }

  const sign = rounded > 0 ? "+" : "−";
  const magnitude =
    fractionDigits > 0
      ? Math.abs(rounded).toFixed(fractionDigits)
      : String(Math.abs(Math.round(rounded)));

  return `${sign}${magnitude}`;
}

export function formatVndGainLabel(realVnd: number, estimatedVnd: number): string {
  const delta = estimatedVnd - realVnd;
  const sign = delta >= 0 ? "+" : "−";
  return `${sign}${formatVND(Math.abs(delta))} ${APPROVAL_SUFFIX}`;
}

export function formatCountGainLabel(
  real: number,
  estimated: number,
  unit: string,
): string {
  const delta = estimated - real;
  return `${formatSignedDelta(delta)} ${unit} ${APPROVAL_SUFFIX}`.trim();
}

export function formatRoasGainLabel(realRoas: number, estimatedRoas: number): string {
  const delta = estimatedRoas - realRoas;
  return `${formatSignedDelta(delta, 1)}x ROAS ${APPROVAL_SUFFIX}`;
}

export function formatRatePointGainLabel(realRate: number, estimatedRate: number): string {
  const reductionPoints = (realRate - estimatedRate) * 100;
  const sign = reductionPoints >= 0 ? "−" : "+";
  const magnitude = Math.abs(reductionPoints).toFixed(1);
  return `${sign}${magnitude}% ${APPROVAL_SUFFIX}`;
}

export function formatStaticGainLabel(message: string): string {
  return `${message} ${APPROVAL_SUFFIX}`;
}

export function formatHealthScoreGainLabel(
  current: number,
  estimated: number,
  metricLabel: string,
  unlockLabel?: string,
): string {
  const deltaLabel = formatSignedDelta(Math.round((estimated - current) * 10) / 10, 1);
  const base = `${deltaLabel} ${metricLabel} ${APPROVAL_SUFFIX}`;
  if (!unlockLabel) {
    return base;
  }
  return `${base} — mở khóa ${unlockLabel}`;
}
