"use client";

import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";

import { opsApi, type OpsApi } from "../../lib/ops/api";
import { fmtInt, fmtK, fmtM, fmtPct, fmtSignedPct } from "../../lib/ops/format";
import { STABILITY_COPY, STEP, cleanDeltas, inNoise, simulate, step, trendChip } from "../../lib/ops/simulation";
import type { BandStats, Deltas, KpiId, OpsMe, SimCell, SimulationPage, Stability, StreamId } from "../../lib/ops/types";
import { C, OpsHeader, OpsPage, STAGE_STYLE, card } from "./ops-shell";

/**
 * "Mô phỏng" — artboard OpsSimulate.dc.html (D25.10 + D25.11 window / trend).
 * Drawn last and NOT yet explicitly reviewed by the owner: flagged in the
 * contract and PROGRESS for review.
 */

const WINDOWS = [7, 14, 30, 90] as const;
const GRID = "210px repeat(4, minmax(0, 1fr)) 160px";
const VGRID = "minmax(0, 2fr) repeat(4, minmax(0, 1fr)) 130px";
const STAB_STYLE: Record<Stability, CSSProperties> = {
  stable: { color: C.green, background: "#e3f5e8" },
  medium: { color: C.amber, background: "#fff4e0" },
  volatile: { color: C.red, background: "#fdecec" },
  unknown: { color: C.body, background: "#f0eef0" },
};
const BAR: Record<Stability, string> = { stable: "#1f8a3d", medium: "#c96a00", volatile: C.pinkStrong, unknown: "#b8b8c0" };
const TREND_STYLE: Record<string, CSSProperties> = {
  up: { color: C.green, background: "#e3f5e8" },
  down: { color: C.red, background: "#fdecec" },
  flat: { color: C.body, background: "#f0eef0" },
  none: { color: C.muted2, background: "#f0eef0" },
};
const STREAM_LABEL: Record<StreamId, string> = { product_card: "Thẻ sản phẩm", shop_tab: "Tab cửa hàng", seller_video: "Video", seller_live: "LIVE" };
const KPI_LABEL: Record<KpiId, string> = { impressions: "Hiển thị", ctr: "CTR", ctor: "CTOR", aov: "AOV" };

function value(kpi: KpiId, v: number | null): string {
  if (v === null) return "—";
  if (kpi === "impressions") return fmtInt(v);
  if (kpi === "aov") return fmtK(v);
  return fmtPct(v);
}

function range(kpi: KpiId, band: BandStats | null): string {
  if (!band) return "—";
  if (kpi === "impressions") return `${fmtInt(band.p10)} – ${fmtInt(band.p90)}`;
  const f = (x: number) => (x * 100).toFixed(1).replace(".", ",");
  return `${f(band.p10)} – ${f(band.p90)} %`;
}

function bandText(band: BandStats | null): string {
  return band?.band_pct === null || band?.band_pct === undefined ? "—" : `±${Math.round(band.band_pct)} %`;
}

type Api = Pick<OpsApi, "simulation" | "createScenario" | "setTarget">;

export function OpsSimulate({ me, shopId, api = opsApi }: { readonly me: OpsMe; readonly shopId: string; readonly api?: Api }) {
  const [win, setWin] = useState<number>(30);
  const [page, setPage] = useState<SimulationPage | null>(null);
  const [failed, setFailed] = useState(false);
  const [deltas, setDeltas] = useState<Deltas>({});
  const [sel, setSel] = useState<StreamId>("product_card");
  const [sort, setSort] = useState<"stable" | "volatile">("stable");
  const [selectedScenario, setSelectedScenario] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const canEdit = me.role !== "viewer";

  const load = useCallback(
    (w: number) => {
      api
        .simulation(shopId, w)
        .then((p) => {
          setPage(p);
          setFailed(false);
        })
        .catch(() => setFailed(true));
    },
    [api, shopId],
  );

  useEffect(() => {
    load(win);
  }, [load, win]);

  const streams = useMemo(() => page?.streams ?? [], [page]);
  const result = useMemo(() => simulate(streams, deltas), [streams, deltas]);
  const status = page?.status;
  const available = Boolean(status?.baseline_available);
  const actions = useMemo(() => {
    const out: { cell: string; what: string }[] = [];
    for (const s of streams) {
      for (const c of s.cells) {
        const d = deltas[s.stream]?.[c.kpi] ?? 0;
        if (d && c.actions) out.push({ cell: `${s.name} · ${c.label} ${d > 0 ? "+" : ""}${d} %`, what: c.actions });
      }
    }
    return out;
  }, [streams, deltas]);

  const save = async (asTarget: boolean) => {
    const clean = cleanDeltas(deltas);
    const now = new Date(Date.now() + 7 * 3600 * 1000);
    const p = (n: number) => String(n).padStart(2, "0");
    const name = `Kịch bản ${p(now.getUTCDate())}/${p(now.getUTCMonth() + 1)} ${p(now.getUTCHours())}:${p(now.getUTCMinutes())}`;
    try {
      const created = await api.createScenario(shopId, name, clean, asTarget);
      setSelectedScenario(created.data.id);
      setNote(asTarget ? "Đã đặt làm mục tiêu của shop." : "Đã lưu kịch bản.");
      load(win);
    } catch (e) {
      setNote(e instanceof Error ? e.message : "Không lưu được.");
    }
  };

  const setTarget = async () => {
    if (selectedScenario) {
      await api.setTarget(shopId, selectedScenario);
      setNote("Đã đặt làm mục tiêu của shop.");
      load(win);
    } else {
      await save(true);
    }
  };

  const vol = page?.volatility[sel];
  const vrows = [...(vol?.rows ?? [])].sort((a, b) => {
    const x = a.impressions_cv ?? 9;
    const y = b.impressions_cv ?? 9;
    return sort === "stable" ? x - y : y - x;
  });
  const shopName = page?.shop.shop_name ?? "";
  const winNote = `Gốc: trung bình ${win} ngày · ▲▼ so với ${win} ngày trước đó · dao động trong ${win} ngày`;
  const totalDelta = result.totalNew - result.totalBase;

  return (
    <OpsPage>
      <OpsHeader active="simulate" me={me} shopId={shopId} />
      <main style={{ padding: "22px 28px", display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700 }}>Mô phỏng · {shopName}</h1>
          <div aria-label="Khoảng thời gian" role="radiogroup" style={{ display: "inline-flex", gap: 4, background: "#fff", border: `1px solid ${C.line}`, borderRadius: 10, padding: 3 }}>
            {WINDOWS.map((n) => {
              const st = page?.windows.find((w) => w.days === n);
              const greyed = st ? !st.comparable : false;
              return (
                <button
                  aria-checked={win === n}
                  key={n}
                  onClick={() => setWin(n)}
                  role="radio"
                  style={{
                    font: "inherit",
                    fontSize: 13,
                    fontWeight: 600,
                    border: 0,
                    borderRadius: 8,
                    minHeight: 34,
                    padding: "0 12px",
                    cursor: "pointer",
                    ...(win === n ? { color: "#fff", background: C.ink } : { color: greyed ? "#a8a8b0" : C.body, background: "transparent" }),
                  }}
                  title={greyed ? `Chưa đủ dữ liệu (cần 2 × ${n} ngày)` : undefined}
                  type="button"
                >
                  {n} ngày
                </button>
              );
            })}
          </div>
          <span style={{ fontSize: 12, fontWeight: 600, color: C.body, background: "#fff", border: `1px solid ${C.line}`, borderRadius: 999, padding: "4px 10px" }}>{winNote}</span>
          {page ? <span style={{ fontSize: 12, fontWeight: 600, borderRadius: 999, padding: "4px 10px", ...STAGE_STYLE[page.stage] }}>{STAGE_NAMES[page.stage]}</span> : null}
          <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
            <button onClick={() => setDeltas({})} style={btn(false)} type="button">
              Về gốc
            </button>
            <button disabled={!canEdit || !available} onClick={() => void save(false)} style={btn(true)} type="button">
              Lưu kịch bản
            </button>
          </div>
        </div>
        {failed ? <p role="alert">Không tải được mô phỏng.</p> : null}
        {!page && !failed ? <p role="status">Đang tải…</p> : null}
        {page && status && !status.comparable ? (
          <p data-testid="window-insufficient" role="status" style={{ margin: 0, fontSize: 13, color: C.amber, fontWeight: 600 }}>
            Chưa đủ dữ liệu (cần 2 × {win} ngày) · hiện có {status.history_days} ngày
            {available ? " — gốc dùng được, chưa so sánh được ▲▼" : ""}
          </p>
        ) : null}
        {page ? (
          <div className="ops-sim" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 360px", gap: 16, alignItems: "start" }}>
            <section style={{ ...card, opacity: available ? 1 : 0.5, overflowX: "auto" }}>
              <div style={{ display: "grid", gridTemplateColumns: GRID, gap: 10, fontSize: 12, fontWeight: 600, color: C.muted, minWidth: 900 }}>
                <span>Luồng · độ ổn định</span>
                <span>Hiển thị/ngày</span>
                <span>CTR</span>
                <span>CTOR</span>
                <span>AOV</span>
                <span>GMV/ngày</span>
              </div>
              {streams.map((s) => {
                const r = result.perStream[s.stream];
                const stab = STABILITY_COPY[s.stability];
                return (
                  <div data-testid={`sim-row-${s.stream}`} key={s.stream} style={{ display: "grid", gridTemplateColumns: GRID, gap: 10, alignItems: "stretch", borderTop: `1px solid ${C.lineSoft}`, paddingTop: 10, minWidth: 900 }}>
                    <button
                      aria-pressed={sel === s.stream}
                      onClick={() => setSel(s.stream)}
                      style={{ font: "inherit", textAlign: "left", background: "transparent", border: 0, padding: 0, cursor: "pointer", display: "flex", flexDirection: "column", gap: 4, color: C.ink }}
                      type="button"
                    >
                      <b style={{ fontSize: 15 }}>{s.name}</b>
                      <span style={{ alignSelf: "flex-start", fontSize: 11, fontWeight: 700, borderRadius: 999, padding: "3px 8px", ...STAB_STYLE[s.stability] }}>{stab.label}</span>
                      <span style={{ fontSize: 11, color: C.muted }}>
                        Biến thiên hiển thị {s.impressions_cv === null ? "—" : `${Math.round(s.impressions_cv * 100)} %`}
                      </span>
                    </button>
                    {s.cells.map((c) => (
                      <Cell
                        canEdit={available}
                        cell={c}
                        delta={deltas[s.stream]?.[c.kpi] ?? 0}
                        key={c.kpi}
                        onStep={(by) => setDeltas(step(deltas, s.stream, c.kpi, by))}
                        stream={s.stream}
                      />
                    ))}
                    <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", gap: 2, background: "#faf7f8", borderRadius: 10, padding: "8px 10px" }}>
                      <b style={{ fontSize: 15 }}>{fmtM(r?.next ?? 0)}</b>
                      <span style={{ fontSize: 11, color: C.muted }}>gốc {fmtM(r?.base ?? 0)}</span>
                      <span style={{ fontSize: 12, fontWeight: 700, color: pctColor(r?.pct ?? 0) }}>{fmtSignedPct(r?.pct ?? 0)}</span>
                    </div>
                  </div>
                );
              })}
              <p style={{ margin: 0, fontSize: 12, color: C.muted2 }}>
                Hiển thị là chỉ số gián tiếp (thuật toán): chỉ tác động qua quảng cáo, chiến dịch, nội dung. Mỗi lần bấm ± đổi 5 %. Ô viền đứt bị khoá theo bản đồ Hành động.
              </p>
            </section>
            <aside style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div data-testid="sim-total" style={{ background: C.ink, color: "#fff", borderRadius: 14, padding: "16px 18px", display: "flex", flexDirection: "column", gap: 6 }}>
                <span style={{ fontSize: 12, color: "#d6d6dc" }}>GMV cả shop sau mô phỏng</span>
                <b style={{ fontSize: 30 }}>{fmtM(result.totalNew)}/ngày</b>
                <span style={{ fontSize: 14, color: "#d6d6dc" }}>gốc {fmtM(result.totalBase)}/ngày</span>
                <span style={{ fontSize: 16, fontWeight: 700, color: "#9fe3b4" }}>
                  {fmtSignedPct(result.pct ?? 0)} · {totalDelta >= 0 ? "+" : ""}
                  {Math.round(totalDelta / 1000)}k ₫/ngày
                </span>
                <span style={{ fontSize: 13, color: "#d6d6dc" }}>≈ {((totalDelta * 30) / 1e6).toFixed(1).replace(".", ",")} tr ₫ mỗi tháng</span>
              </div>
              <div style={{ ...card, padding: "14px 16px", gap: 8, fontSize: 13 }}>
                <b style={{ fontSize: 14 }}>Hành động có thể tạo ra thay đổi này</b>
                {(actions.length ? actions : [{ cell: "Chưa chỉnh ô nào", what: "bấm ± ở một ô để xem Hành động tương ứng" }]).map((a) => (
                  <div data-testid="sim-action" key={a.cell} style={{ borderTop: `1px solid ${C.lineSoft}`, paddingTop: 6 }}>
                    <b>{a.cell}</b> · {a.what}
                  </div>
                ))}
              </div>
              <div style={{ ...card, padding: "14px 16px", gap: 8, fontSize: 13 }}>
                <b style={{ fontSize: 14 }}>Kịch bản đã lưu</b>
                {page.scenarios.length === 0 ? <span style={{ color: C.muted2 }}>Chưa có kịch bản.</span> : null}
                {page.scenarios.map((sc) => (
                  <button
                    data-testid="sim-scenario"
                    key={sc.id}
                    onClick={() => {
                      setDeltas(sc.deltas);
                      setSelectedScenario(sc.id);
                    }}
                    style={{ font: "inherit", display: "flex", alignItems: "center", gap: 8, borderTop: `1px solid ${C.lineSoft}`, paddingTop: 6, background: "transparent", border: 0, textAlign: "left", cursor: "pointer" }}
                    type="button"
                  >
                    <span style={{ flex: 1 }}>
                      {sc.name} · {fmtSignedPct(sc.result?.delta_pct ?? null)} GMV
                    </span>
                    {sc.is_target ? <span style={{ fontSize: 11, fontWeight: 700, color: C.green }}>Mục tiêu shop</span> : null}
                    {sc.id === selectedScenario && !sc.is_target ? <span style={{ fontSize: 11, fontWeight: 700, color: C.pink }}>đang xem</span> : null}
                  </button>
                ))}
                <button
                  disabled={!canEdit || !available}
                  onClick={() => void setTarget()}
                  style={{ font: "inherit", fontSize: 13, fontWeight: 600, color: C.pink, background: "transparent", border: 0, minHeight: 36, cursor: "pointer", textAlign: "left" }}
                  type="button"
                >
                  Đặt kịch bản đang xem làm mục tiêu của shop ›
                </button>
                {note ? <span role="status">{note}</span> : null}
              </div>
            </aside>
          </div>
        ) : null}
        {page && available ? (
          <section style={{ ...card, overflowX: "auto" }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
              <h2 style={{ margin: 0, fontSize: 17, fontWeight: 700 }}>Độ dao động · {STREAM_LABEL[sel]}</h2>
              <span style={{ fontSize: 13, color: C.muted }}>
                Từng {vol?.row_kind ?? "dòng"}: khoảng dao động thường ngày (p10–p90 trong {win} ngày) · chọn dòng ổn định để đặt mục tiêu
              </span>
              <div style={{ marginLeft: "auto", display: "inline-flex", gap: 4, background: "#f7f7f9", border: `1px solid ${C.line}`, borderRadius: 10, padding: 3 }}>
                {(
                  [
                    ["stable", "Ổn định trước"],
                    ["volatile", "Dao động trước"],
                  ] as const
                ).map(([id, label]) => (
                  <button
                    aria-pressed={sort === id}
                    key={id}
                    onClick={() => setSort(id)}
                    style={{
                      font: "inherit",
                      fontSize: 12,
                      fontWeight: 600,
                      border: 0,
                      borderRadius: 8,
                      minHeight: 32,
                      padding: "0 10px",
                      cursor: "pointer",
                      ...(sort === id ? { color: C.ink, background: "#fff", boxShadow: "0 1px 2px rgba(20,20,30,0.08)" } : { color: C.muted, background: "transparent" }),
                    }}
                    type="button"
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: VGRID, gap: 10, fontSize: 12, fontWeight: 600, color: C.muted, padding: "0 8px", minWidth: 900 }}>
              <span>{(vol?.row_kind ?? "Dòng").replace(/^./, (x) => x.toUpperCase())}</span>
              <span>Hiển thị/ngày (thấp – cao)</span>
              <span>CTR (thấp – cao)</span>
              <span>CTOR (thấp – cao)</span>
              <span>Hệ số biến thiên hiển thị</span>
              <span>Đánh giá</span>
            </div>
            {vrows.length === 0 ? <span style={{ fontSize: 13, color: C.muted2, padding: "0 8px" }}>Chưa đủ dữ liệu từng dòng cho khoảng này.</span> : null}
            {vrows.map((v) => (
              <div data-testid="vol-row" key={v.id} style={{ display: "grid", gridTemplateColumns: VGRID, gap: 10, alignItems: "center", borderTop: `1px solid ${C.lineSoft}`, padding: 8, fontSize: 13, minWidth: 900 }}>
                <span>
                  <b>{v.name}</b>
                </span>
                <span>{range("impressions", v.impressions)}</span>
                <span>{range("ctr", v.ctr)}</span>
                <span>{range("ctor", v.ctor)}</span>
                <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ flex: 1, height: 6, background: C.lineSoft, borderRadius: 999, display: "flex" }}>
                    <span style={{ height: 6, borderRadius: 999, width: `${Math.min(100, (v.impressions_cv ?? 0) * 100)}%`, background: BAR[v.stability] }} />
                  </span>
                  {v.impressions_cv === null ? "—" : `${Math.round(v.impressions_cv * 100)} %`}
                </span>
                <span style={{ justifySelf: "start", fontSize: 11, fontWeight: 700, borderRadius: 999, padding: "3px 8px", ...STAB_STYLE[v.stability] }}>{STABILITY_COPY[v.stability].row}</span>
              </div>
            ))}
          </section>
        ) : null}
        <p style={{ margin: 0, fontSize: 12, color: C.muted2 }}>
          Mô phỏng cộng theo công thức GMV = Hiển thị × CTR × CTOR × AOV cho từng luồng; không phải dự báo của mô hình.
        </p>
      </main>
    </OpsPage>
  );
}

const STAGE_NAMES: Record<string, string> = { trial: "Thử nghiệm", self: "Tự vận hành", pilot: "Pilot đặc biệt" };

function pctColor(pct: number): string {
  return pct > 0 ? C.green : pct < 0 ? C.red : C.body;
}

function btn(primary: boolean): CSSProperties {
  return primary
    ? { font: "inherit", fontSize: 14, fontWeight: 600, color: "#fff", background: C.ink, border: 0, borderRadius: 10, minHeight: 40, padding: "0 14px", cursor: "pointer" }
    : { font: "inherit", fontSize: 14, fontWeight: 600, color: C.ink, background: "#fff", border: `1px solid ${C.line}`, borderRadius: 10, minHeight: 40, padding: "0 14px", cursor: "pointer" };
}

function Cell({
  cell,
  delta,
  stream,
  onStep,
  canEdit,
}: {
  readonly cell: SimCell;
  readonly delta: number;
  readonly stream: StreamId;
  readonly onStep: (by: number) => void;
  readonly canEdit: boolean;
}) {
  const now = cell.value === null ? null : cell.value * (1 + delta / 100);
  const trend = trendChip(cell.trend_pct);
  const noisy = inNoise(delta, cell.band?.band_pct);
  const box: CSSProperties = cell.locked
    ? { background: "#f0eef0", border: "1px dashed #d6d2d6" }
    : delta !== 0
      ? { background: "#fff7fa", border: `2px solid ${C.pinkStrong}` }
      : { background: "#fff", border: "1px solid #ece3e7" };
  const label = `${STREAM_LABEL[stream]} ${KPI_LABEL[cell.kpi]}`;
  return (
    <div data-locked={cell.locked} data-testid={`sim-cell-${stream}-${cell.kpi}`} style={{ borderRadius: 10, padding: "8px 10px", display: "flex", flexDirection: "column", gap: 4, ...box }}>
      <span style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 6, flexWrap: "wrap" }}>
        <span style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
          <b style={{ fontSize: 15 }}>{value(cell.kpi, now)}</b>
          <span data-testid="trend-chip" style={{ fontSize: 11, fontWeight: 600, borderRadius: 6, padding: "1px 6px", ...TREND_STYLE[trend.tone] }}>
            {trend.text}
          </span>
        </span>
        {!cell.locked && cell.indirect ? <span style={{ fontSize: 11, fontWeight: 700, color: C.amber }}>gián tiếp ⚠</span> : null}
      </span>
      <span style={{ fontSize: 11, color: C.muted }}>Dao động thường: {bandText(cell.band)}</span>
      {cell.locked ? (
        <span style={{ fontSize: 11, color: C.body }}>Khoá · phụ thuộc trang sản phẩm</span>
      ) : (
        <>
          <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <button aria-label={`Giảm 5 % ${label}`} disabled={!canEdit} onClick={() => onStep(-STEP)} style={stepBtn} type="button">
              −
            </button>
            <span style={{ minWidth: 54, textAlign: "center", fontSize: 13, fontWeight: 700, color: pctColor(delta) }}>
              {delta > 0 ? "+" : ""}
              {delta} %
            </span>
            <button aria-label={`Tăng 5 % ${label}`} disabled={!canEdit} onClick={() => onStep(STEP)} style={stepBtn} type="button">
              +
            </button>
          </span>
          {delta !== 0 ? (
            <span style={{ fontSize: 11, fontWeight: 600, color: noisy ? C.amber : C.green }}>{noisy ? "Trong dao động thường ngày" : "Vượt dao động · đo được"}</span>
          ) : null}
        </>
      )}
    </div>
  );
}

const stepBtn: CSSProperties = {
  font: "inherit",
  fontSize: 14,
  fontWeight: 700,
  width: 28,
  height: 28,
  borderRadius: 6,
  border: `1px solid ${C.line}`,
  background: "#fff",
  cursor: "pointer",
};
