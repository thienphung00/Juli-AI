"use client";

import Link from "next/link";
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";

import { OpsApiError, opsApi, type OpsApi } from "../../lib/ops/api";
import type { OpsMe } from "../../lib/ops/types";
import { buildGoogleAuthorizeUrl, readAuthSession } from "../../lib/supabase-auth";

/** Shared ops chrome (artboards `docs/product/design/ops/*.dc.html`). */

export const C = {
  ink: "#1a1a1f",
  page: "#f4f4f6",
  line: "#e3e3e8",
  lineSoft: "#f0f0f3",
  muted: "#5f5f6b",
  muted2: "#6b6b76",
  body: "#4a4a55",
  pink: "#b0386a",
  pinkStrong: "#c2306d",
  green: "#146c2e",
  red: "#a3222f",
  amber: "#8a4b00",
} as const;

export const FONT = "'Be Vietnam Pro', system-ui, sans-serif";

export const card: CSSProperties = {
  background: "#ffffff",
  border: `1px solid ${C.line}`,
  borderRadius: 14,
  padding: "16px 18px",
  display: "flex",
  flexDirection: "column",
  gap: 10,
};

export const STAGE_STYLE: Record<string, CSSProperties> = {
  trial: { background: "#e6f0fd", color: "#1d4f91" },
  self: { background: "#e3f5e8", color: C.green },
  pilot: { background: "#f3e8ff", color: "#5b2a86" },
};

/** The artboards are desktop (1440 px); below 900 px the columns stack. */
const OPS_NARROW_CSS = `@media (max-width: 900px) {
  .ops-sim, .ops-settings { grid-template-columns: minmax(0, 1fr) !important; }
  .ops-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }
}`;

export type OpsNavKey = "overview" | "staff" | "audit" | "simulate" | "settings";

export function OpsHeader({
  me,
  active,
  shopId,
  back,
}: {
  readonly me: OpsMe | null;
  readonly active?: OpsNavKey;
  readonly shopId?: string;
  readonly back?: boolean;
}) {
  const link = (key: OpsNavKey, href: string, label: string) =>
    active === key ? (
      <span aria-current="page" key={key} style={{ background: "#3a3a44", borderRadius: 8, padding: "6px 12px", fontWeight: 600 }}>
        {label}
      </span>
    ) : (
      <Link href={href} key={key} style={{ color: "#d6d6dc", textDecoration: "none", padding: "6px 12px" }}>
        {label}
      </Link>
    );
  const items = shopId
    ? [
        link("overview", "/ops", "Tổng quan"),
        link("simulate", `/ops/shops/${shopId}/mo-phong`, "Mô phỏng"),
        link("settings", `/ops/shops/${shopId}`, "Cài đặt shop"),
      ]
    : [link("overview", "/ops", "Tổng quan"), link("staff", "/ops/nhan-vien", "Nhân viên"), link("audit", "/ops/nhat-ky", "Nhật ký")];
  return (
    <header
      style={{ display: "flex", alignItems: "center", gap: 16, background: C.ink, color: "#ffffff", padding: "0 28px", minHeight: 60, flexWrap: "wrap" }}
    >
      <b style={{ fontSize: 18 }}>
        Juli <span style={{ color: "#f3a9c8" }}>Ops</span>
      </b>
      {back ? (
        <Link href="/ops" style={{ color: "#d6d6dc", textDecoration: "none", fontSize: 14 }}>
          ‹ Tổng quan
        </Link>
      ) : (
        <nav aria-label="Ops" style={{ display: "flex", gap: 4, fontSize: 14 }}>
          {items}
        </nav>
      )}
      {me ? (
        <span style={{ marginLeft: "auto", fontSize: 13, color: "#d6d6dc" }}>
          {me.email} · {me.role_label}
        </span>
      ) : null}
    </header>
  );
}

export function OpsPage({ children }: { readonly children: ReactNode }) {
  return (
    <div className="ops-page" style={{ minHeight: "100vh", fontFamily: FONT, color: C.ink, background: C.page, display: "flex", flexDirection: "column" }}>
      <style>{OPS_NARROW_CSS}</style>
      {children}
    </div>
  );
}

type GateState =
  | { kind: "loading" }
  | { kind: "signed-out"; googleHref: string | null }
  | { kind: "forbidden" }
  | { kind: "error" }
  | { kind: "ready"; me: OpsMe };

/** Signed in + an active staff row, or an honest state. */
export function OpsGate({
  api = opsApi,
  children,
}: {
  readonly api?: Pick<OpsApi, "me">;
  readonly children: (me: OpsMe) => ReactNode;
}) {
  const [state, setState] = useState<GateState>({ kind: "loading" });
  useEffect(() => {
    let live = true;
    const timer = window.setTimeout(() => {
      if (!readAuthSession()) {
        setState({ kind: "signed-out", googleHref: buildGoogleAuthorizeUrl(`${window.location.origin}/ops/dang-nhap`) });
        return;
      }
      api
        .me()
        .then((me) => live && setState({ kind: "ready", me }))
        .catch((error: unknown) => {
          if (!live) return;
          if (error instanceof OpsApiError && error.status === 401) {
            setState({ kind: "signed-out", googleHref: buildGoogleAuthorizeUrl(`${window.location.origin}/ops/dang-nhap`) });
          } else if (error instanceof OpsApiError && error.status === 403) setState({ kind: "forbidden" });
          else setState({ kind: "error" });
        });
    }, 0);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [api]);

  if (state.kind === "ready") return <>{children(state.me)}</>;
  return (
    <OpsPage>
      <OpsHeader me={null} />
      <main style={{ padding: "24px 28px" }}>
        <div role="status" style={{ ...card, maxWidth: 520 }}>
          {state.kind === "loading" ? <span>Đang tải…</span> : null}
          {state.kind === "signed-out" ? (
            <>
              <b>Đăng nhập Juli Ops</b>
              <span style={{ fontSize: 14, color: C.body }}>Dùng tài khoản Google @app-juli.com.</span>
              {state.googleHref ? (
                <a href={state.googleHref} style={{ fontWeight: 600 }}>
                  Đăng nhập với Google
                </a>
              ) : (
                <span>Chưa cấu hình đăng nhập.</span>
              )}
            </>
          ) : null}
          {state.kind === "forbidden" ? <span>Tài khoản này không có quyền vào Juli Ops.</span> : null}
          {state.kind === "error" ? <span>Không tải được Juli Ops. Thử lại sau.</span> : null}
        </div>
      </main>
    </OpsPage>
  );
}
