"use client";

import type { DemoDecisionItem } from "@juli/contracts";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { EMPTY_CARDS, decisionGroupHref, indexCards, type CardIndex } from "../../lib/phan-tich/cards";
import { calendarView, promoView } from "../../lib/phan-tich/extras";
import { perDay } from "../../lib/phan-tich/format";
import {
  METRIC_COLS,
  TABS,
  analysisHref,
  defaultMetric,
  defaultStream,
  pageTitle,
  resolveSelection,
  streamView,
  streamsOf,
  type CellMetric,
  type Direction,
  type QueryState,
  type Selection,
  type StreamView,
  type TabSlug,
} from "../../lib/phan-tich/model";
import { tableView, type TableView } from "../../lib/phan-tich/rows";
import type { RankedStream, RankingLoader, RankingPayload } from "../../lib/phan-tich/types";
import type { ShopDiagnosisReport } from "../../lib/shop-analysis/types";
import { useNarrow } from "../quyet-dinh/use-narrow";
import { CalendarSection, MobileExtras, PromoSection } from "./extras";
import type { ContentAnalysisClients } from "../../lib/content-analysis/types";
import { VideoAnalysis } from "../content-analysis/video-analysis";
import { StreamCard, type RankingState } from "./stream-card";

/**
 * Phân tích (ADR-109 Amendment 2; `docs/product/design/phan-tich/` PtProduct,
 * PtContent, PtMobile, PtFlow, LinkA), inside the app shell's slot.
 *
 *   PHÂN TÍCH · h1 (the conclusion) · "30 ngày · so với 30 ngày trước" · ⓘ
 *   [Sản phẩm][Nội dung]                 ✦ Juli gợi ý · … [Xem N đề xuất ›]
 *   Sản phẩm: … | Nội dung: … | Liên kết: chỉ theo dõi ở Trang chủ ›
 *   stream cards (one open): cells → ranking rows (expand in place) → Còn lại → Tổng
 *   Khuyến mãi / Lịch sale và chiến dịch (Sản phẩm, collapsed)
 *
 * Pure of where the data comes from (an injected source): the signed-in
 * door passes the shop's report, its ranking reader and its decisions; the
 * signed-out door ("Bản minh họa") passes the bundled sample, which issues
 * no request. URL state: `tab`, `stream` (`dong` = all collapsed), `metric`,
 * `huong=len`, `row`.
 */

export interface PhanTichViewProps {
  readonly report: ShopDiagnosisReport;
  readonly loadRanking: RankingLoader;
  /** The shop's cards (for "Xem đề xuất ›"); a failure only hides the links. */
  readonly loadDecisions: () => Promise<readonly DemoDecisionItem[]>;
  readonly query: QueryState;
  /** Writes the selection into the URL (router.replace in the app). */
  readonly onNavigate?: (href: string) => void;
  readonly sample?: boolean;
  /** P15 "Phân tích video" in Nội dung row detail; absent → no block. */
  readonly analysisClients?: ContentAnalysisClients | null;
}

export const INFO_TEXT =
  "Số trung bình mỗi ngày. Mỗi ô ghi số ₫/ngày mà thay đổi của chỉ số đó kéo GMV lên hoặc xuống. Bảng chia số đó cho từng sản phẩm; các dòng cộng lại đúng bằng số của ô.";

const rankingKey = (stream: RankedStream, metric: CellMetric) => `${stream}:${metric}`;

export function PhanTichView({ report, loadRanking, loadDecisions, query, onNavigate, sample = false, analysisClients = null }: PhanTichViewProps) {
  const narrow = useNarrow();
  const queryKey = `${query.tab ?? ""}|${query.stream ?? ""}|${query.metric ?? ""}|${query.huong ?? ""}|${query.row ?? ""}`;
  // The UI follows what the seller clicked straight away; the URL catches up
  // through `onNavigate`. A new URL from outside (a card's "Xem phân tích ›",
  // back/forward) takes over again.
  const [local, setLocal] = useState<{ source: string; selection: Selection } | null>(null);
  const resolved = useMemo(() => resolveSelection(report, query), [report, query]);
  const selection = local && local.source === queryKey ? local.selection : resolved;
  const { tab, stream: openStream, metric, direction: chosenDirection, row } = selection;

  const [restOpen, setRestOpen] = useState(false);
  const [infoOpen, setInfoOpen] = useState(false);

  const go = (next: Selection) => {
    setLocal({ source: queryKey, selection: next });
    setRestOpen(false);
    onNavigate?.(analysisHref(next));
  };

  // -- decisions (the card join) ------------------------------------------------------------
  const [cards, setCards] = useState<CardIndex>(EMPTY_CARDS);
  useEffect(() => {
    let cancelled = false;
    loadDecisions()
      .then((items) => {
        if (!cancelled) setCards(indexCards(items));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [loadDecisions]);

  // -- the open stream's ranking --------------------------------------------------------------
  const [rankings, setRankings] = useState<Record<string, RankingState>>({});
  const [retry, setRetry] = useState(0);
  const key = openStream && metric ? rankingKey(openStream, metric) : null;
  const known = useRef(rankings);
  useEffect(() => {
    known.current = rankings;
  });
  useEffect(() => {
    if (!openStream || !metric || !key) return;
    const have = known.current[key];
    if (have && have.status !== "error") return;
    let cancelled = false;
    setRankings((prev) => ({ ...prev, [key]: { status: "loading" } }));
    loadRanking(openStream, metric)
      .then((found) => {
        if (cancelled) return;
        setRankings((prev) => ({ ...prev, [key]: found ? { status: "ready", payload: found.ranking } : { status: "empty" } }));
      })
      .catch(() => {
        if (!cancelled) setRankings((prev) => ({ ...prev, [key]: { status: "error" } }));
      });
    return () => {
      cancelled = true;
    };
    // `rankings` is read through the ref so a finished load does not re-trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, loadRanking, retry]);

  const state: RankingState | undefined = key ? rankings[key] : undefined;
  const payload: RankingPayload | null = state?.status === "ready" ? state.payload : null;

  // A row named in the URL that sits on the other side (Kéo lên) shows that side.
  const otherSide = (d: Direction) => (d === "down" ? "up" : "down");
  const direction: Direction =
    payload && row && !(chosenDirection === "down" ? payload.down : payload.up).some((r) => r.id === row) &&
    (chosenDirection === "down" ? payload.up : payload.down).some((r) => r.id === row)
      ? otherSide(chosenDirection)
      : chosenDirection;
  const shown: Selection = { ...selection, direction };

  // Arriving on a row (a card's "Xem phân tích ›", a video's tagged product): scroll to it.
  const scrolledFor = useRef<string | null>(null);
  useEffect(() => {
    if (!payload || !row || scrolledFor.current === `${queryKey}|${row}`) return;
    const element = document.getElementById(`pa-row-${row}`);
    if (!element) return;
    scrolledFor.current = `${queryKey}|${row}`;
    if (query.row === row) element.scrollIntoView?.({ block: "center" });
  });

  const views: StreamView[] = useMemo(() => streamsOf(tab).map((s) => streamView(report, s.stream)), [report, tab]);
  const headStream = defaultStream(views);
  const headView = views.find((v) => v.spec.stream === headStream) ?? null;
  const weak = headView?.weakMetric ?? null;
  const weakCards = weak ? cards.countFor(weak) : 0;

  const table: TableView | null =
    payload && openStream && metric ? tableView({ report, stream: openStream, metric, direction, cards }, payload) : null;

  const selectTab = (next: TabSlug) => {
    if (next !== tab) go(resolveSelection(report, { tab: next }));
  };
  const toggleStream = (view: StreamView) => {
    const open = openStream === view.spec.stream;
    go(
      open
        ? { tab, stream: null, metric: null, direction: "down", row: null }
        : { tab, stream: view.spec.stream, metric: defaultMetric(view), direction: "down", row: null },
    );
  };
  const pickMetric = (view: StreamView, next: CellMetric) =>
    go({ tab, stream: view.spec.stream, metric: next, direction: "down", row: null });
  const pickDirection = (next: Direction) => go({ ...shown, direction: next, row: null });
  const toggleRow = (id: string) => go({ ...shown, row: row === id ? null : id });
  const taggedSelection = (productId: string) => resolveSelection(report, { tab: "san-pham", row: productId });

  const promo = promoView(report);
  const calendar = calendarView(report);

  return (
    <section aria-labelledby="analytics-title" className="pa-page" data-testid="phan-tich">
      <header className="pa-head">
        <p className="pa-eyebrow">PHÂN TÍCH</p>
        <div className="pa-head__line">
          <h1 className="pa-title" id="analytics-title">
            {pageTitle(report, tab)}
          </h1>
          <div className="pa-head__chips">
            <span className="pa-window">30 ngày · so với 30 ngày trước</span>
            <button
              aria-controls="pa-info"
              aria-expanded={infoOpen}
              aria-label="Cách tính"
              className="pa-info-btn"
              onClick={() => setInfoOpen((open) => !open)}
              type="button"
            >
              i
            </button>
          </div>
        </div>
        {infoOpen ? (
          <div className="pa-info" id="pa-info">
            {INFO_TEXT}
          </div>
        ) : null}
      </header>
      {sample ? (
        <p className="demo-notice sample-notice pa-sample" data-testid="mock-data-notice">
          Dữ liệu mẫu · {report.shop_name} là shop minh họa, không phải shop của bạn.
        </p>
      ) : null}

      <div className="pa-nav">
        <div className="pa-nav__row">
          <div aria-label="Phân tích" className="pa-tabs" role="tablist">
            {TABS.map((t) => (
              <button
                aria-controls="pa-panel"
                aria-selected={t.slug === tab}
                className="pa-tab"
                id={`pa-tab-${t.slug}`}
                key={t.slug}
                onClick={() => selectTab(t.slug)}
                role="tab"
                type="button"
              >
                {t.label}
              </button>
            ))}
          </div>
          {tab === "san-pham" && weak && headView ? (
            <div className="pa-suggest" data-testid="juli-suggestion">
              <span>
                <b>✦ Juli gợi ý</b>
                {narrow ? <br /> : " · "}
                {METRIC_COLS[weak]} kéo GMV {perDay(headView.weakContribution)}
              </span>
              {weakCards > 0 ? (
                <Link className="pa-suggest__btn" href={decisionGroupHref(weak)}>
                  Xem {weakCards} đề xuất ›
                </Link>
              ) : null}
            </div>
          ) : null}
        </div>
        <p className="pa-caption" data-testid="pa-caption">
          <b>Sản phẩm:</b>
          <span>Thẻ sản phẩm · Tab cửa hàng</span>
          <span aria-hidden="true" className="pa-caption__bar">
            |
          </span>
          <b>Nội dung:</b>
          <span>Video · LIVE</span>
          <span aria-hidden="true" className="pa-caption__bar">
            |
          </span>
          <b>Liên kết:</b>
          <span>chỉ theo dõi ở</span>
          <Link className="pa-caption__link" href="/">
            Trang chủ ›
          </Link>
        </p>
      </div>

      <div aria-labelledby={`pa-tab-${tab}`} className="pa-panel" id="pa-panel" role="tabpanel">
        {views.map((view) => {
          const open = openStream === view.spec.stream;
          return (
            <StreamCard
              direction={direction}
              key={view.spec.stream}
              metric={open ? metric : null}
              narrow={narrow}
              onPickDirection={pickDirection}
              onPickMetric={(m) => pickMetric(view, m)}
              onRetry={() => setRetry((n) => n + 1)}
              onTaggedProduct={(productId) => go(taggedSelection(productId))}
              onToggle={() => toggleStream(view)}
              onToggleRest={() => setRestOpen((value) => !value)}
              onToggleRow={toggleRow}
              open={open}
              restOpen={restOpen}
              row={row}
              state={open ? state : undefined}
              table={open ? table : null}
              taggedHref={(productId) => analysisHref(taggedSelection(productId))}
              renderRowDetail={
                analysisClients && view.spec.rowKind !== "product"
                  ? (r) => {
                      const kind = view.spec.rowKind === "video" ? "video" : "live";
                      return (
                        <VideoAnalysis
                          clients={analysisClients}
                          compact
                          key={r.id}
                          target={{ kind, contentRef: `${kind}:${r.id}`, productId: r.taggedProduct }}
                        />
                      );
                    }
                  : undefined
              }
              view={view}
            />
          );
        })}

        {tab === "san-pham" ? (
          narrow ? (
            <MobileExtras calendar={calendar} promo={promo} />
          ) : (
            <>
              <PromoSection promo={promo} />
              <CalendarSection calendar={calendar} />
            </>
          )
        ) : null}

        {tab === "noi-dung" ? (
          <p className="pa-foot">
            Ô xám: CTOR và AOV của video phụ thuộc trang sản phẩm, xem ở tab Sản phẩm.
            {sample ? " Số liệu là ví dụ minh hoạ." : ""}
          </p>
        ) : sample ? (
          <p className="pa-foot">Số liệu là ví dụ minh hoạ.</p>
        ) : null}
      </div>
    </section>
  );
}
