/** Vietnamese number formats used across the ops pages (match the artboards). */

export function fmtInt(n: number): string {
  return Math.round(n).toLocaleString("vi-VN");
}

export function fmtPct(fraction: number | null | undefined, digits = 2): string {
  if (fraction === null || fraction === undefined) return "—";
  return `${(fraction * 100).toFixed(digits).replace(".", ",")} %`;
}

export function fmtRate(fraction: number | null | undefined): string {
  if (fraction === null || fraction === undefined) return "—";
  return `${Math.round(fraction * 100)} %`;
}

export function fmtUsd(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `$${n.toFixed(1).replace(".", ",")}`;
}

export function fmtK(vnd: number | null | undefined): string {
  if (vnd === null || vnd === undefined) return "—";
  return `${Math.round(vnd / 1000)}k ₫`;
}

export function fmtM(vnd: number | null | undefined): string {
  if (vnd === null || vnd === undefined) return "—";
  return `${(vnd / 1e6).toFixed(2).replace(".", ",")} tr ₫`;
}

/** GMV 30 ngày: "214,9 tr" / "1,2 tỷ". */
export function fmtGmvShort(vnd: number | null | undefined): string {
  if (vnd === null || vnd === undefined) return "—";
  if (vnd >= 1e9) return `${(vnd / 1e9).toFixed(1).replace(".", ",")} tỷ`;
  return `${(vnd / 1e6).toFixed(1).replace(".", ",")} tr`;
}

export function fmtSignedPct(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined) return "—";
  return `${n >= 0 ? "+" : ""}${n.toFixed(digits).replace(".", ",")} %`;
}

/** "08:07 hôm nay" / "3 ngày trước" / "09/10 15:30". */
export function fmtWhen(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "—";
  const at = new Date(iso.endsWith("Z") || /[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  if (Number.isNaN(at.getTime())) return "—";
  const local = (d: Date) => new Date(d.getTime() + 7 * 3600 * 1000);
  const a = local(at);
  const b = local(now);
  const hhmm = `${String(a.getUTCHours()).padStart(2, "0")}:${String(a.getUTCMinutes()).padStart(2, "0")}`;
  const dayA = Date.UTC(a.getUTCFullYear(), a.getUTCMonth(), a.getUTCDate());
  const dayB = Date.UTC(b.getUTCFullYear(), b.getUTCMonth(), b.getUTCDate());
  const days = Math.round((dayB - dayA) / 86_400_000);
  if (days === 0) return `${hhmm} hôm nay`;
  if (days > 0 && days < 7) return `${days} ngày trước`;
  return `${String(a.getUTCDate()).padStart(2, "0")}/${String(a.getUTCMonth() + 1).padStart(2, "0")} ${hhmm}`;
}

/** "10/10/2026". */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = iso.slice(0, 10).split("-");
  return d.length === 3 ? `${d[2]}/${d[1]}/${d[0]}` : "—";
}
