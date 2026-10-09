"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import {
  analysisHref,
  channelRow,
  findBottleneck,
  METRIC_NAMES,
  METRIC_SLUGS,
  pageTitle,
  resolveSelection,
  specOf,
  streamsOf,
  suggestionLine,
  TABS,
  type Cell,
  type QueryState,
  type TabSlug,
} from "../../lib/phan-tich/model";
import { ANALYSIS_NOTES } from "../../lib/phan-tich/notes";
import type { RankingLoader, RankingRow } from "../../lib/phan-tich/types";
import type { ShopAnalysisEnvelope } from "../../lib/shop-analysis/types";
import { slashDate } from "../../lib/vn-format";
import { AppPageHeader } from "../app-shell/page-header";
import { BandsTable, FlashSection, VoucherSection } from "../shop-analysis/promotions";
import { TimelineSection } from "../shop-analysis/timeline";
import { DetailPanel } from "./detail-panel";
import { CollapsedSection, HeroList } from "./hero-list";
import { RankingTable, rankingTitle, type Direction, type RankingState } from "./ranking-table";
import { StreamFunnel } from "./stream-funnel";

/**
 * Phân tích (AC-8.6, ADR-109 decisions 2–5), inside the app shell's slot.
 *
 *   PHÂN TÍCH · SẢN PHẨM            ← AppPageHeader, h1 = the bottleneck
 *   [Sản phẩm] [Nội dung]           ← sub-tabs (URL `tab=`)
 *   stream funnel × 2               ← clickable cells (URL `stream=`, `metric=`)
 *   ranking table | Ví dụ panel     ← the selected cell's ranking (d.5)
 *   hero list (Sản phẩm)            ← expands in place
 *   Khuyến mãi / Dòng thời gian / Cách tính  ← collapsed, "Xem thêm"
 *
 * Pure of where the data comes from: the envelope is the shell's
 * (`useShopReport`), rankings come through `loadRanking` (the signed-in
 * client, or the bundled sample for anonymous visitors).
 */

export interface PhanTichViewProps {
  readonly envelope: ShopAnalysisEnvelope;
  readonly loadRanking: RankingLoader;
  readonly query: QueryState;
  /** Writes the selection into the URL (router.replace in the app). */
  readonly onNavigate?: (href: string) => void;
  readonly sample?: boolean;
}

const cellKey = (cell: Cell) => `${cell.stream}:${cell.metric}`;

export function PhanTichView({ envelope, loadRanking, query, onNavigate, sample = false }: PhanTichViewProps) {
  const report = envelope.report;
  const queryKey = `${query.tab ?? ""}|${query.stream ?? ""}|${query.metric ?? ""}`;
  // Local selection, keyed by the URL it was made on: a new URL from outside
  // (a Home link, back/forward, the router catching up) takes over again.
  const [local, setLocal] = useState<{ source: string; query: QueryState } | null>(null);
  const current = local && local.source === queryKey ? local.query : query;

  const selection = useMemo(() => resolveSelection(report, current), [report, current]);
  const { tab, cell } = selection;
  const bottleneck = useMemo(() => findBottleneck(report, tab), [report, tab]);
  const suggestion = bottleneck ? suggestionLine(report, bottleneck) : null;

  const [rankings, setRankings] = useState<Record<string, RankingState>>({});
  const [retry, setRetry] = useState(0);
  const [direction, setDirection] = useState<Direction>("down");
  const [rowId, setRowId] = useState<string | null>(null);

  const key = cell ? cellKey(cell) : null;
  const state: RankingState | undefined = key ? rankings[key] : undefined;

  const known = useRef(rankings);
  useEffect(() => {
    known.current = rankings;
  });

  useEffect(() => {
    if (!cell || !key) return;
    const have = known.current[key];
    if (have && have.status !== "error") return;
    let cancelled = false;
    setRankings((prev) => ({ ...prev, [key]: { status: "loading" } }));
    loadRanking(cell.stream, cell.metric)
      .then((found) => {
        if (cancelled) return;
        setRankings((prev) => ({
          ...prev,
          [key]: found ? { status: "ready", payload: found.ranking } : { status: "empty" },
        }));
      })
      .catch(() => {
        if (!cancelled) setRankings((prev) => ({ ...prev, [key]: { status: "error" } }));
      });
    return () => {
      cancelled = true;
    };
    // `cell` is derived from `key`; `rankings` is read through the ref so a
    // finished load does not re-trigger. `retry` re-runs after an error.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, loadRanking, retry]);

  const navigate = (next: QueryState) => {
    setLocal({ source: queryKey, query: next });
    setDirection("down");
    setRowId(null);
    const resolved = resolveSelection(report, next);
    onNavigate?.(analysisHref(resolved.tab, next.stream ? resolved.cell : null));
  };
  const selectTab = (next: TabSlug) => {
    if (next !== tab) navigate({ tab: next });
  };
  const selectCell = (next: Cell) => {
    navigate({ tab, stream: specOf(next.stream).slug, metric: METRIC_SLUGS[next.metric] });
  };

  const tabMeta = TABS.find((t) => t.slug === tab) ?? TABS[0];
  const w = report.windows;
  const payload = state?.status === "ready" ? state.payload : null;
  const rows: RankingRow[] = payload ? (direction === "down" ? payload.down : payload.up) : [];
  const selectedRow = rows.find((r) => r.id === rowId) ?? rows[0] ?? null;
  const profile = selectedRow ? report.profiles?.find((p) => p.product_id === selectedRow.id) : undefined;
  const spec = cell ? specOf(cell.stream) : null;
  const metricName = cell ? METRIC_NAMES[cell.metric] : "";

  return (
    <section aria-labelledby="analytics-title" className="pt-page" data-testid="phan-tich">
      <AppPageHeader
        eyebrow={`${tabMeta.eyebrow} · 30 ngày so với 30 ngày trước`}
        lede={`30 ngày gần đây ${slashDate(w.last_first)}–${slashDate(w.last_last)} so với ${slashDate(w.prior_first)}–${slashDate(w.prior_last)}. Mọi số là trung bình mỗi ngày. Bấm một chỉ số để xem cái gì kéo nó.`}
        title={pageTitle(report, tab)}
        titleId="analytics-title"
      />
      {sample ? (
        <p className="demo-notice sample-notice" data-testid="mock-data-notice">
          Dữ liệu mẫu · {report.shop_name} là shop minh họa, không phải shop của bạn.
        </p>
      ) : null}

      <div aria-label="Phân tích theo" className="pt-tabs" role="tablist">
        {TABS.map((t) => (
          <button
            aria-controls="pt-panel"
            aria-selected={t.slug === tab}
            className="pt-tabs__tab"
            id={`pt-tab-${t.slug}`}
            key={t.slug}
            onClick={() => selectTab(t.slug)}
            role="tab"
            type="button"
          >
            {t.label}
          </button>
        ))}
      </div>

      <div aria-labelledby={`pt-tab-${tab}`} className="pt-panel" id="pt-panel" role="tabpanel">
        <div className="pt-streams">
          {streamsOf(tab).map((s) => (
            <StreamFunnel
              bottleneck={bottleneck}
              key={s.stream}
              onSelect={selectCell}
              row={channelRow(report, s.stream)}
              selected={cell}
              spec={s}
              suggestion={suggestion}
            />
          ))}
        </div>

        {cell && spec ? (
          <div className="pt-drill">
            <section aria-labelledby="pt-ranking-title" className="card pt-ranking">
              <div className="pt-ranking__head">
                <div>
                  <p className="eyebrow">{spec.label}</p>
                  <h2 className="pt-section__title" id="pt-ranking-title">
                    {rankingTitle(spec.rowKind, metricName, direction)}
                  </h2>
                </div>
                <div aria-label="Chiều xếp hạng" className="pt-toggle" role="group">
                  {(["down", "up"] as const).map((d) => (
                    <button
                      aria-pressed={direction === d}
                      key={d}
                      onClick={() => {
                        setDirection(d);
                        setRowId(null);
                      }}
                      type="button"
                    >
                      {d === "down" ? "Kéo xuống" : "Kéo lên"}
                    </button>
                  ))}
                </div>
              </div>
              {!state || state.status === "loading" ? (
                <p aria-live="polite" className="text-muted" role="status">
                  Đang tải bảng xếp hạng…
                </p>
              ) : state.status === "empty" ? (
                <p className="pt-empty" role="status">
                  Chưa có bảng xếp hạng cho chỉ số này
                </p>
              ) : state.status === "error" ? (
                <div className="pt-empty" role="alert">
                  <p>Không tải được bảng xếp hạng. Vui lòng thử lại.</p>
                  <button className="btn-secondary" onClick={() => setRetry((n) => n + 1)} type="button">
                    Thử lại
                  </button>
                </div>
              ) : (
                <RankingTable
                  direction={direction}
                  onSelectRow={(row) => setRowId(row.id)}
                  payload={state.payload}
                  selectedRowId={selectedRow?.id ?? null}
                />
              )}
            </section>
            {payload && selectedRow ? <DetailPanel payload={payload} profile={profile} row={selectedRow} /> : null}
          </div>
        ) : null}

        {tab === "san-pham" ? (
          <>
            <HeroList report={report} />
            <CollapsedSection
              id="khuyen-mai"
              lede="Độ phủ flash sale và độ sâu thật, giảm giá sản phẩm và voucher trong 60 ngày."
              title="Khuyến mãi"
            >
              <BandsTable bands={report.shop_bands ?? []} />
              {report.shop_flash ? (
                <FlashSection bands={report.shop_bands ?? []} flash={report.shop_flash} shopLevel />
              ) : null}
              <VoucherSection summary={report.vouchers} />
            </CollapsedSection>
            <CollapsedSection
              id="dong-thoi-gian"
              lede="Trung bình 7 ngày của từng kênh, ngày flash sale và ngày sale nền tảng trên cùng một trục 60 ngày."
              title="Dòng thời gian sự kiện"
            >
              <TimelineSection report={report} />
            </CollapsedSection>
          </>
        ) : null}
        <CollapsedSection id="cach-tinh" lede="Cách Juli tính các con số trên trang này." title="Cách tính">
          <ul className="analysis-notes">
            {ANALYSIS_NOTES.map((note) => (
              <li key={note}>{note}</li>
            ))}
            <li>
              Bảng xếp hạng: mỗi dòng là GMV/ngày mà thay đổi của chỉ số đã chọn ở dòng đó kéo theo; các dòng
              cộng với ba dòng cuối (ít đơn, các dòng khác, thay đổi cơ cấu) đúng bằng phần của chỉ số đó trong
              thay đổi GMV của luồng.
            </li>
          </ul>
        </CollapsedSection>
      </div>
    </section>
  );
}
