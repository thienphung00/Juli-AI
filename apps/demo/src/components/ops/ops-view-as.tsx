"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { opsApi, type OpsApi } from "../../lib/ops/api";
import { createOpsViewFetch } from "../../lib/ops/view-fetch";
import type { OpsMe, ViewSession } from "../../lib/ops/types";
import { fetchMetricRanking } from "../../lib/phan-tich/rankings-client";
import { resolveTab } from "../../lib/quyet-dinh/copy";
import type { QdClients } from "../../lib/quyet-dinh/client-types";
import { fetchRecommendations } from "../../lib/recommendations-api-client";
import { fetchShopAnalysis } from "../../lib/shop-analysis/api-client";
import type { ShopAnalysisEnvelope } from "../../lib/shop-analysis/types";
import { readAuthSession } from "../../lib/supabase-auth";
import { HomeOverview } from "../home/home-overview";
import { SignedInPhanTich } from "../phan-tich/signed-in-phan-tich";
import { resolveMeasureTab, QuyetDinhView } from "../quyet-dinh/quyet-dinh-view";
import { REAL_QD_CLIENTS } from "../quyet-dinh/signed-in-quyet-dinh";
import { C, FONT } from "./ops-shell";

/**
 * "Xem như shop" — artboard OpsViewAs.dc.html (D25.3, amended 2026-10-10:
 * ALWAYS read-only). The seller's own screens (Trang chủ, Quyết định with run
 * details, Phân tích, Quy tắc) under a banner; every GET is re-pointed to the
 * ops view API (`createOpsViewFetch`), every write is refused (client and
 * server), and the seller views sit inside a disabled `<fieldset>` so no write
 * control can be pressed. Every session is logged.
 */

type Tab = "home" | "decisions" | "analytics" | "rules";

function withFetch<T extends object>(options: T, fetchImpl: typeof fetch): T {
  return { ...options, fetchImpl };
}

/** REAL_QD_CLIENTS with every request going through the ops view fetch. */
export function opsQdClients(fetchImpl: typeof fetch): QdClients {
  const real = REAL_QD_CLIENTS;
  return {
    ...real,
    fetchDecisions: (o) => real.fetchDecisions(withFetch(o, fetchImpl)),
    approve: (id, o) => real.approve(id, withFetch(o, fetchImpl)),
    reject: (o, id, reason) => real.reject(withFetch(o, fetchImpl), id, reason),
    fetchRuns: (o) => real.fetchRuns(withFetch(o, fetchImpl)),
    fetchRules: (o) => real.fetchRules(withFetch(o, fetchImpl)),
    putRule: (o, key, value, setBy, scope) => real.putRule(withFetch(o, fetchImpl), key, value, setBy, scope),
    deleteRule: (o, key, scope) => real.deleteRule(withFetch(o, fetchImpl), key, scope),
    fetchChanges: (o, id) => real.fetchChanges(withFetch(o, fetchImpl), id),
    startRevert: (o, id, r) => real.startRevert(withFetch(o, fetchImpl), id, r),
    fetchQuestions: (o) => real.fetchQuestions(withFetch(o, fetchImpl)),
    dismissQuestion: (o, id) => real.dismissQuestion(withFetch(o, fetchImpl), id),
    confirm: (runId, call, decision, option, o) => real.confirm(runId, call, decision, option, { ...(o ?? {}), fetchImpl } as typeof o),
    decline: (o, id, r) => real.decline(withFetch(o, fetchImpl), id, r),
    uploadPhoto: (o, id, f) => real.uploadPhoto(withFetch(o, fetchImpl), id, f),
    fetchInstructions: (o, id) => real.fetchInstructions(withFetch(o, fetchImpl), id),
    markApplied: (o, id) => real.markApplied(withFetch(o, fetchImpl), id),
    fetchMeasurement: (o, id) => real.fetchMeasurement(withFetch(o, fetchImpl), id),
    fetchRunDetail: (o, id) => real.fetchRunDetail(withFetch(o, fetchImpl), id),
    useContent: (o, id, v, e) => real.useContent(withFetch(o, fetchImpl), id, v, e),
    redraftContent: (o, id) => real.redraftContent(withFetch(o, fetchImpl), id),
    markPublished: (o, id) => real.markPublished(withFetch(o, fetchImpl), id),
    streamFetch: fetchImpl,
  };
}

type Api = Pick<OpsApi, "viewSession">;

export function OpsViewAs({
  shopId,
  api = opsApi,
  baseFetch,
}: {
  /** The staff member (shown by the gate; view-as itself never acts as them). */
  readonly me: OpsMe;
  readonly shopId: string;
  readonly api?: Api;
  readonly baseFetch?: typeof fetch;
}) {
  const [session, setSession] = useState<ViewSession | null>(null);
  const [failed, setFailed] = useState(false);
  const [tab, setTab] = useState<Tab>("decisions");
  const [qdParams, setQdParams] = useState(new URLSearchParams());
  const [ptParams, setPtParams] = useState(new URLSearchParams());
  const [envelope, setEnvelope] = useState<ShopAnalysisEnvelope | null | undefined>(undefined);
  const token = readAuthSession()?.accessToken ?? "";

  useEffect(() => {
    let live = true;
    api
      .viewSession(shopId, "view")
      .then((s) => live && setSession(s))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [api, shopId]);

  const viewFetch = useMemo(() => createOpsViewFetch({ shopId, baseFetch }), [shopId, baseFetch]);
  const clients = useMemo(() => opsQdClients(viewFetch), [viewFetch]);

  useEffect(() => {
    if (!session) return;
    let live = true;
    fetchShopAnalysis({ token, shopId, fetchImpl: viewFetch })
      .then((e) => live && setEnvelope(e))
      .catch(() => live && setEnvelope(null));
    return () => {
      live = false;
    };
  }, [session, token, shopId, viewFetch]);

  const onNavigate = useCallback((href: string) => {
    const [path, search = ""] = href.split("?");
    const params = new URLSearchParams(search);
    if (path.startsWith("/analytics")) {
      setPtParams(params);
      setTab("analytics");
    } else if (path.startsWith("/decisions")) {
      setQdParams(params);
      setTab("decisions");
    } else if (path === "/" || path === "") {
      setTab("home");
    }
  }, []);

  const name = session?.shop.shop_name ?? "…";
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join("");
  const qdQuery = {
    tab: resolveTab(qdParams.get("tab")),
    run: qdParams.get("run"),
    rulesOpen: tab === "rules" || qdParams.get("quy-tac") === "1",
    measureTab: resolveMeasureTab(qdParams.get("moc")),
    focusCard: qdParams.get("the"),
    focusMetric: qdParams.get("nhom"),
  };
  const ptQuery = {
    tab: ptParams.get("tab"),
    stream: ptParams.get("stream"),
    metric: ptParams.get("metric"),
    huong: ptParams.get("huong"),
    row: ptParams.get("row"),
  };

  return (
    <div style={{ minHeight: "100vh", fontFamily: FONT, color: C.ink, background: "#f7f5f6", display: "flex", flexDirection: "column" }}>
      <div
        data-testid="view-as-banner"
        role="status"
        style={{ display: "flex", alignItems: "center", gap: 14, background: C.ink, color: "#fff", padding: "0 24px", minHeight: 52, fontSize: 14, flexWrap: "wrap" }}
      >
        <b>{`Đang xem như ${name} · chỉ xem, không ghi được`}</b>
        <span style={{ opacity: 0.85 }}>Phiên xem được ghi nhật ký · không hiện dữ liệu người mua</span>
        <Link
          href={`/ops/shops/${shopId}`}
          onClick={() => void api.viewSession(shopId, "exit").catch(() => undefined)}
          style={{ marginLeft: "auto", color: "#fff", fontWeight: 600, textDecoration: "none", minHeight: 36, display: "inline-flex", alignItems: "center" }}
        >
          Thoát
        </Link>
      </div>
      {failed ? (
        <p role="alert" style={{ padding: 24 }}>
          Không mở được Xem như shop.
        </p>
      ) : null}
      {session ? (
        <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
          <nav aria-label="Seller" style={{ width: 104, borderRight: "1px solid #f1e6eb", background: "#fff", display: "flex", flexDirection: "column", alignItems: "center", gap: 18, paddingTop: 18, fontSize: 12, color: C.body }}>
            <b style={{ fontSize: 20, color: C.ink }}>Juli.</b>
            {(
              [
                ["home", "Trang chủ"],
                ["decisions", "Quyết định"],
                ["analytics", "Phân tích"],
                ["juli", "Juli"],
                ["rules", "Quy tắc"],
              ] as const
            ).map(([id, label]) => (
              <button
                aria-current={tab === id ? "page" : undefined}
                key={id}
                disabled={id === "juli"}
                onClick={() => id !== "juli" && setTab(id)}
                title={id === "juli" ? "Trợ lý Juli của seller: không có trong Xem như shop" : undefined}
                style={{ font: "inherit", fontSize: 12, background: "transparent", border: 0, cursor: "pointer", color: tab === id ? C.pink : C.body, fontWeight: tab === id ? 700 : 400 }}
                type="button"
              >
                {label}
              </button>
            ))}
          </nav>
          <main style={{ flex: 1, padding: "22px 28px", display: "flex", flexDirection: "column", gap: 14, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <span style={{ width: 44, height: 44, borderRadius: 12, background: "#f3a9c8", display: "inline-flex", alignItems: "center", justifyContent: "center", color: "#fff", fontWeight: 700 }}>{initials}</span>
              <span style={{ display: "flex", flexDirection: "column" }}>
                <b style={{ fontSize: 17 }}>{name}</b>
                <span style={{ fontSize: 12, color: C.muted }}>TikTok Shop · {STAGE_NAMES[session.stage]}</span>
              </span>
              <span data-testid="write-note" style={{ marginLeft: "auto", fontSize: 13, color: C.muted }}>
                Xem được mọi trang của seller (Trang chủ, Quyết định, Phân tích, Quy tắc, lượt chạy). Mọi nút ghi đều khoá.
              </span>
            </div>
            <fieldset
              data-testid="seller-view"
              disabled
              style={{ border: 0, margin: 0, padding: 0, minWidth: 0 }}
              title="Chế độ xem: không thể thao tác thay seller"
            >
              {tab === "home" ? (
                envelope ? <HomeOverview envelope={envelope} /> : <p role="status">{envelope === null ? "Shop chưa có báo cáo." : "Đang tải…"}</p>
              ) : null}
              {tab === "analytics" ? (
                envelope ? (
                  <SignedInPhanTich
                    envelope={envelope}
                    fetchDecisions={(o) => fetchRecommendations({ ...o, fetchImpl: viewFetch })}
                    fetchRanking={(o) => fetchMetricRanking({ ...o, fetchImpl: viewFetch })}
                    onNavigate={onNavigate}
                    query={ptQuery}
                    shopId={shopId}
                    token={token}
                  />
                ) : (
                  <p role="status">{envelope === null ? "Shop chưa có báo cáo." : "Đang tải…"}</p>
                )
              ) : null}
              {tab === "decisions" || tab === "rules" ? (
                <QuyetDinhView clients={clients} key={tab} onNavigate={onNavigate} query={qdQuery} shop={{ id: shopId, name }} token={token} />
              ) : null}
            </fieldset>
          </main>
        </div>
      ) : null}
    </div>
  );
}

const STAGE_NAMES: Record<string, string> = { trial: "Thử nghiệm", self: "Tự vận hành", pilot: "Pilot đặc biệt" };
