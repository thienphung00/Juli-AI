"use client";

import { useEffect, useId, useRef } from "react";

import { DASH } from "../../lib/shopee-analytics/format";
import { MAX_TITLE_CHARS, isRefused, titleCount, versionCode, versionName, versionTag, versionTable, type TableCell, type TableRow } from "../../lib/shopee-decisions/versions";
import type { Card, CardVersion } from "../../lib/shopee-decisions/types";
import { TextChip } from "../shopee-analytics/ui";

/**
 * The versions of one card side by side (`CardVersions.dc.html`): 2-4 columns next to "Hôm nay", a
 * radio picks the version that is approved, a breach never disables a button (it opens
 * {@link BreachDialog}), and the title box carries the 100-character counter.
 */

const toneClass = (c: TableCell["tone"]): string => (c === "up" ? "sa-tone--up" : c === "down" ? "sa-tone--down" : c === "muted" ? "sd-muted" : "");

export function VersionsTable({
  card,
  versions,
  sel,
  onPick,
  locked,
  todayText,
  rows: given,
  noToday = false,
  subLabel = "so với hôm nay",
}: {
  readonly card: Card;
  readonly versions: readonly CardVersion[];
  readonly sel: number;
  readonly onPick: (index: number) => void;
  readonly locked: boolean;
  readonly todayText: string;
  /** Other rows than the card's own table (KOL cards). */
  readonly rows?: readonly TableRow[];
  /** No "Hôm nay" column (KOL cards have nothing to compare with). */
  readonly noToday?: boolean;
  readonly subLabel?: string;
}) {
  const rows = given ?? versionTable(card, versions);
  const n = versions.length;
  const style = { ["--sv-cols" as string]: n } as React.CSSProperties;
  return (
    <section className="sa-card sv" data-testid="sv-table">
      <div className="sa-card__head">
        <h3 className="sa-h2" data-testid="sv-count">
          {n} phiên bản của cùng một thay đổi
        </h3>
        <span className="sa-hint">V1 là bản Juli đề xuất. Chọn một cột để duyệt; thanh trượt bên dưới chỉ chỉnh phiên bản đang chọn. Các số tính theo cùng một công thức, so với hôm nay.</span>
      </div>
      <div className="sv-scroll">
        <div className={`sv-grid ${noToday ? "sv-grid--notoday" : ""}`} role="radiogroup" aria-label="Phiên bản" style={style}>
          <div className="sv-head sv-head--label">
            <b>Chỉ số</b>
            <span>{subLabel}</span>
          </div>
          {noToday ? null : (
            <div className="sv-head sv-head--today">
              <b>Hôm nay</b>
              <span>{todayText}</span>
            </div>
          )}
          {versions.map((v, i) => {
            const on = i === sel;
            const tag = versionTag(v, i);
            const bad = tag.tone === "down";
            return (
              <button
                aria-checked={on}
                className={`sv-head sv-head--ver ${on ? "sv-head--on" : ""} ${bad ? "sv-head--bad" : ""}`}
                data-testid={`sv-ver-${v.version}`}
                disabled={locked || isRefused(v)}
                key={v.version}
                onClick={() => onPick(i)}
                role="radio"
                type="button"
              >
                <span className="sv-head__top">
                  <span aria-hidden="true" className={`sv-dot ${on ? "sv-dot--on" : ""}`} />
                  <b>{versionName(v)}</b>
                  <TextChip tone={tag.tone}>{tag.text}</TextChip>
                </span>
                <span className="sv-head__label">{v.label ?? versionName(v)}</span>
                <span className="sv-head__code">{versionCode(card, v)}</span>
              </button>
            );
          })}
          {rows.map((r) => (
            <RowCells key={r.key} noToday={noToday} row={r} sel={sel} />
          ))}
        </div>
      </div>
    </section>
  );
}

const VALUE_TONED = new Set(["sure", "exp", "chi", "floor", "cap", "limit"]);
const SMALL = new Set(["floor", "cap", "limit"]);

function RowCells({ row, sel, noToday }: { readonly row: TableRow; readonly sel: number; readonly noToday: boolean }) {
  return (
    <>
      <div className="sv-cell sv-cell--label" data-testid={`sv-row-${row.key}`}>
        <b>{row.label}</b>
        {row.sub ? <span>{row.sub}</span> : null}
      </div>
      {noToday ? null : (
        <div className="sv-cell sv-cell--today">
          <span className="sd-muted">{row.today ?? DASH}</span>
        </div>
      )}
      {row.cells.map((c, i) => (
        <div className={`sv-cell ${i === sel ? "sv-cell--sel" : ""} ${c.bad ? "sv-cell--bad" : ""}`} data-testid={`sv-${row.key}-${i + 1}`} key={i}>
          <span className={`sv-cell__v ${VALUE_TONED.has(row.key) ? toneClass(c.tone) : c.tone === "muted" ? "sd-muted" : ""} ${SMALL.has(row.key) ? "sv-cell__v--s" : ""}`}>{c.v}</span>
          {c.d ? <span className={`sv-cell__d sv-cell__d--${c.tone}`}>{c.d}</span> : null}
        </div>
      ))}
    </>
  );
}

/** "Quay lại" / "Vẫn tiếp tục": a breach is a warning, never a disabled button. */
export function BreachDialog({
  open,
  title,
  lines,
  closing,
  goLabel = "Vẫn tiếp tục",
  busy,
  sheet,
  onBack,
  onGo,
}: {
  readonly open: boolean;
  readonly title: string;
  readonly lines: readonly string[];
  /** The sentence under the lines: "…đã xác nhận, kèm giờ, trên thẻ này." (a card) / "…trên thẻ." (a manual offer). */
  readonly closing: string;
  readonly goLabel?: string;
  readonly busy?: boolean;
  /** A bottom sheet on a phone (`TuTaoPhuongAnMobile`). */
  readonly sheet?: boolean;
  readonly onBack: () => void;
  readonly onGo: () => void;
}) {
  const id = useId();
  const back = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    if (!open) return;
    back.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onBack();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onBack]);
  if (!open) return null;
  return (
    <div className={`qv-overlay ${sheet ? "sv-overlay--sheet" : ""}`} data-testid="sv-warn">
      <div aria-labelledby={`${id}-t`} aria-modal="true" className={`qv-dialog sv-warn ${sheet ? "sv-warn--sheet" : ""}`} role="alertdialog">
        <h3 className="qv-dialog__title" id={`${id}-t`}>
          {title}
        </h3>
        <div className="sv-warn__lines">
          {lines.map((l, i) => (
            <span data-testid="sv-warn-line" key={i}>
              {l}
            </span>
          ))}
        </div>
        <p className="qv-dialog__body">{closing}</p>
        <div className="qv-dialog__actions">
          <button className="qv-btn qv-btn--secondary" onClick={onBack} ref={back} type="button">
            Quay lại
          </button>
          <button className="qv-btn qv-btn--primary" disabled={busy} onClick={onGo} type="button">
            {goLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

/** The title of a title card: 100 characters at most, counted as the person types (D-4). */
export function TitleBox({ current, value, disabled, onChange, name }: { readonly current: string; readonly value: string; readonly disabled: boolean; readonly onChange: (next: string) => void; readonly name: string }) {
  const c = titleCount(value);
  const cur = titleCount(current);
  return (
    <div className="sv-title" data-testid="sv-title">
      <div className="sa-card__head">
        <h3 className="sa-h2">Nội dung tiêu đề của {name}</h3>
        <span className="sa-hint">
          Hôm nay: {current} ({cur.n}/100)
        </span>
      </div>
      <label className="sd-field__label" htmlFor="sv-title-box">
        Tiêu đề trên Shopee (tối đa {MAX_TITLE_CHARS} ký tự)
      </label>
      <textarea aria-describedby="sv-title-count" className={`sv-title__box ${c.over ? "sv-title__box--over" : ""}`} disabled={disabled} id="sv-title-box" onChange={(event) => onChange(event.target.value)} rows={2} value={value} />
      <div className="sv-title__meta">
        <span className={`sa-chip sa-chip--${c.tone === "up" ? "up" : c.tone === "warn" ? "warn" : "down"}`} data-testid="sv-title-count" id="sv-title-count">
          {c.n}/100
        </span>
        <span className={c.over ? "sv-title__over" : "sa-hint"}>{c.note}</span>
      </div>
      <p className="sa-hint">Giới hạn 100 ký tự áp dụng cho mọi tiêu đề Juli đề xuất (cắt ở ranh giới từ) và cho tiêu đề bạn tự nhập. Trên 100: không lưu, không duyệt.</p>
    </div>
  );
}
