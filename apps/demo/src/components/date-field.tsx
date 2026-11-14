"use client";

import { useState, type CSSProperties } from "react";

/**
 * A day field that always reads and writes dd/mm/yyyy. `<input type="date">` shows the day in the
 * browser's locale (mm/dd/yyyy on an English browser), which put 05/10 on screen as 10/05; the
 * value this field takes and gives stays ISO `YYYY-MM-DD`.
 */

const ISO = /^(\d{4})-(\d{2})-(\d{2})$/;
const VN = /^(\d{1,2})[/.\- ](\d{1,2})[/.\- ](\d{4})$/;

export function isoToDisplay(iso: string): string {
  const m = ISO.exec(iso);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : iso;
}

/** "05/10/2026" or "2026-10-05" → "2026-10-05"; anything else (or a day that does not exist) → null. */
export function parseDay(text: string): string | null {
  const t = text.trim();
  let y: number;
  let mo: number;
  let d: number;
  const iso = ISO.exec(t);
  const vn = VN.exec(t);
  if (iso) [y, mo, d] = [Number(iso[1]), Number(iso[2]), Number(iso[3])];
  else if (vn) [y, mo, d] = [Number(vn[3]), Number(vn[2]), Number(vn[1])];
  else return null;
  const probe = new Date(Date.UTC(y, mo - 1, d));
  if (probe.getUTCFullYear() !== y || probe.getUTCMonth() !== mo - 1 || probe.getUTCDate() !== d) return null;
  return `${String(y).padStart(4, "0")}-${String(mo).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

export function DateField({
  value,
  onChange,
  style,
  ariaLabel,
  className,
}: {
  readonly value: string;
  readonly onChange: (iso: string) => void;
  readonly style?: CSSProperties;
  readonly ariaLabel?: string;
  readonly className?: string;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  return (
    <input
      aria-label={ariaLabel}
      className={className}
      inputMode="numeric"
      onBlur={() => setDraft(null)}
      onChange={(e) => {
        const raw = e.target.value;
        const iso = parseDay(raw);
        if (iso) {
          setDraft(null);
          onChange(iso);
        } else {
          setDraft(raw);
        }
      }}
      placeholder="dd/mm/yyyy"
      style={style}
      type="text"
      value={draft ?? isoToDisplay(value)}
    />
  );
}
