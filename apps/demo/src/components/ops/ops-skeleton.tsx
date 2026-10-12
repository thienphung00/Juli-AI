import type { CSSProperties } from "react";

import { C, card } from "./ops-shell";

/**
 * Light loading placeholders (P22): grey bars shaped like the content that is
 * coming (a KPI row + cards, or a table), instead of a lone "Đang tải…". Same
 * card chrome as the Ops pages; a soft pulse that stops under
 * `prefers-reduced-motion`. Screen readers still hear "Đang tải…".
 */

const PULSE_CSS = `@keyframes ops-skel-pulse { 0%, 100% { opacity: 1 } 50% { opacity: 0.55 } }
.ops-skel-bar { background: #ececf0; border-radius: 6px; animation: ops-skel-pulse 1.4s ease-in-out infinite; }
@media (prefers-reduced-motion: reduce) { .ops-skel-bar { animation: none; } }`;

const srOnly: CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  overflow: "hidden",
  clip: "rect(0 0 0 0)",
  whiteSpace: "nowrap",
};

function Bar({ width, height = 12 }: { readonly width: number | string; readonly height?: number }) {
  return <span aria-hidden="true" className="ops-skel-bar" style={{ display: "block", width, height }} />;
}

function TableSkeleton({ rows }: { readonly rows: number }) {
  return (
    <div style={{ ...card, padding: 0, gap: 0 }}>
      <div style={{ display: "flex", gap: 24, padding: "14px 18px", borderBottom: `1px solid ${C.line}` }}>
        {[90, 140, 80, 110, 70].map((w, i) => (
          <Bar height={10} key={i} width={w} />
        ))}
      </div>
      {Array.from({ length: rows }, (_, r) => (
        <div key={r} style={{ display: "flex", gap: 24, alignItems: "center", padding: "14px 18px", borderBottom: r < rows - 1 ? `1px solid ${C.lineSoft}` : 0 }}>
          {[120, 180, 70, 100, 60].map((w, i) => (
            <Bar key={i} width={w - ((r * 13 + i * 7) % 30)} />
          ))}
        </div>
      ))}
    </div>
  );
}

function CardsSkeleton({ rows }: { readonly rows: number }) {
  return (
    <>
      <div className="ops-kpis" style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 12 }}>
        {[0, 1, 2, 3].map((i) => (
          <div key={i} style={card}>
            <Bar height={10} width="55%" />
            <Bar height={22} width="40%" />
          </div>
        ))}
      </div>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} style={card}>
          <Bar height={14} width={`${46 - (i % 3) * 8}%`} />
          <Bar width="92%" />
          <Bar width={`${70 - (i % 2) * 15}%`} />
        </div>
      ))}
    </>
  );
}

export function OpsSkeleton({
  variant = "table",
  rows = 5,
  testId = "ops-skeleton",
}: {
  readonly variant?: "table" | "cards";
  readonly rows?: number;
  readonly testId?: string;
}) {
  return (
    <div aria-busy="true" data-testid={testId} role="status" style={{ display: "flex", flexDirection: "column", gap: 12, position: "relative" }}>
      <style>{PULSE_CSS}</style>
      <span style={srOnly}>Đang tải…</span>
      {variant === "table" ? <TableSkeleton rows={rows} /> : <CardsSkeleton rows={rows} />}
    </div>
  );
}
