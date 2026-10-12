"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import type { ChangeRow } from "../../lib/ops/setting-changes";
import { C } from "./ops-shell";

/** D27.5 confirmation pieces — artboard OpsConfirm.dc.html. */

const SECONDARY = {
  font: "inherit",
  fontSize: 14,
  fontWeight: 600,
  color: C.ink,
  background: "#ffffff",
  border: `1px solid ${C.line}`,
  borderRadius: 10,
  minHeight: 44,
  padding: "0 16px",
  cursor: "pointer",
} as const;

const PRIMARY = {
  font: "inherit",
  fontSize: 14,
  fontWeight: 600,
  color: "#ffffff",
  background: C.pinkStrong,
  border: 0,
  borderRadius: 10,
  minHeight: 44,
  padding: "0 18px",
  cursor: "pointer",
} as const;

/**
 * "before → after" dialog: "Quay lại" / the confirm label. Escape = Quay lại.
 * `children` (D28: a package / cap choice, the contract number) sit between the
 * title and the before → after rows; `confirmDisabled` holds the confirm button
 * until they are complete.
 */
export function ConfirmDialog({
  title,
  rows,
  note,
  confirmLabel,
  onCancel,
  onConfirm,
  children,
  confirmDisabled = false,
}: {
  readonly title: string;
  readonly rows: readonly Pick<ChangeRow, "k" | "before" | "after">[];
  readonly note: string;
  readonly confirmLabel: string;
  readonly onCancel: () => void;
  readonly onConfirm: () => Promise<void>;
  readonly children?: ReactNode;
  readonly confirmDisabled?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const back = useRef<HTMLButtonElement>(null);
  // P22: a second press before React re-renders the button as disabled (double
  // click, Enter + click) must not send the change twice — the state flag alone
  // only takes effect on the next render.
  const inFlight = useRef(false);
  useEffect(() => {
    back.current?.focus();
  }, []);
  return (
    <div
      onKeyDown={(e) => {
        if (e.key === "Escape" && !busy && !inFlight.current) onCancel();
      }}
      style={{ position: "fixed", inset: 0, background: "rgba(26,26,31,0.42)", display: "flex", alignItems: "center", justifyContent: "center", padding: 16, zIndex: 30 }}
    >
      <div
        aria-labelledby="ops-cf-q"
        aria-modal="true"
        role="dialog"
        style={{ boxSizing: "border-box", width: 540, maxWidth: "100%", maxHeight: "100%", overflowY: "auto", background: "#ffffff", borderRadius: 16, padding: "22px 24px", display: "flex", flexDirection: "column", gap: 12, boxShadow: "0 20px 48px rgba(20,20,30,0.25)" }}
      >
        <h3 id="ops-cf-q" style={{ margin: 0, fontSize: 19, fontWeight: 700 }}>
          {title}
        </h3>
        {children}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {rows.map((d, i) => (
            <div
              data-testid="confirm-row"
              key={`${d.k}-${i}`}
              style={{ display: "grid", gridTemplateColumns: "150px minmax(0, 1fr)", gap: 10, fontSize: 14, borderTop: `1px solid ${C.lineSoft}`, paddingTop: 6 }}
            >
              <span style={{ color: C.muted }}>{d.k}</span>
              <span style={{ overflowWrap: "anywhere" }}>
                <span style={{ color: C.muted2, textDecoration: "line-through" }}>{d.before}</span> → <b>{d.after}</b>
              </span>
            </div>
          ))}
        </div>
        <span style={{ fontSize: 13, color: C.muted }}>{note}</span>
        {error ? (
          <span role="alert" style={{ color: C.red, fontSize: 13 }}>
            {error}
          </span>
        ) : null}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
          <button disabled={busy} onClick={() => !inFlight.current && onCancel()} ref={back} style={SECONDARY} type="button">
            Quay lại
          </button>
          <button
            disabled={busy || confirmDisabled}
            aria-busy={busy || undefined}
            onClick={async () => {
              if (inFlight.current || confirmDisabled) return;
              inFlight.current = true;
              setBusy(true);
              setError(null);
              try {
                await onConfirm();
              } catch (e) {
                setError(e instanceof Error ? e.message : "Không lưu được.");
                setBusy(false);
                inFlight.current = false;
              }
            }}
            style={{ ...PRIMARY, opacity: busy || confirmDisabled ? 0.6 : 1 }}
            type="button"
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Bottom bar "N thay đổi chưa lưu · summary · Bỏ thay đổi · Lưu thay đổi (N)". */
export function DraftBar({
  count,
  summary,
  onDiscard,
  onSave,
}: {
  readonly count: number;
  readonly summary: string;
  readonly onDiscard: () => void;
  readonly onSave: () => void;
}) {
  return (
    <div
      aria-label="Thay đổi chưa lưu"
      role="region"
      style={{ position: "fixed", left: 0, right: 0, bottom: 0, zIndex: 20, background: "#ffffff", borderTop: `2px solid ${C.pinkStrong}`, boxShadow: "0 -8px 24px rgba(20,20,30,0.08)", padding: "14px 28px", display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}
    >
      <b style={{ fontSize: 15 }}>{count} thay đổi chưa lưu</b>
      <span data-testid="draft-summary" style={{ fontSize: 13, color: C.muted, minWidth: 0, flex: "1 1 200px" }}>
        {summary}
      </span>
      <button onClick={onDiscard} style={{ ...SECONDARY, marginLeft: "auto" }} type="button">
        Bỏ thay đổi
      </button>
      <button onClick={onSave} style={PRIMARY} type="button">
        Lưu thay đổi ({count})
      </button>
    </div>
  );
}

/** "Đã lưu N thay đổi · ghi 1 dòng nhật ký" — fades after a few seconds. */
export function Toast({ text, onDone }: { readonly text: string; readonly onDone: () => void }) {
  useEffect(() => {
    const t = window.setTimeout(onDone, 4000);
    return () => window.clearTimeout(t);
  }, [text, onDone]);
  return (
    <div
      data-testid="ops-toast"
      role="status"
      style={{ position: "fixed", left: 28, bottom: 24, zIndex: 25, background: C.ink, color: "#ffffff", borderRadius: 10, padding: "12px 16px", fontSize: 14 }}
    >
      {text}
    </div>
  );
}
