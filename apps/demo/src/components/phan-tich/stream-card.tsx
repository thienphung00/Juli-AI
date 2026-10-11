"use client";

import Link from "next/link";
import { useId } from "react";

import { decisionCardHref } from "../../lib/phan-tich/cards";
import type { CellMetric, CellView, Direction, StreamView } from "../../lib/phan-tich/model";
import type { RowView, TableView } from "../../lib/phan-tich/rows";
import type { RankingPayload } from "../../lib/phan-tich/types";

/**
 * One collapsible stream card (ADR-109 Amendment 2 d.1–3; PtProduct,
 * PtContent, PtMobile): name, GMV/ngày, Δ, "Yếu nhất: …" when collapsed;
 * open → the metric cells (clickable ones re-rank the table), the ranking
 * rows (expand in place), "Còn lại", "Tổng" = the cell's figure.
 */

export type RankingState =
  | { readonly status: "loading" }
  | { readonly status: "empty" }
  | { readonly status: "error" }
  | { readonly status: "ready"; readonly payload: RankingPayload };

export interface StreamCardProps {
  readonly view: StreamView;
  readonly open: boolean;
  readonly narrow: boolean;
  readonly metric: CellMetric | null;
  readonly direction: Direction;
  readonly row: string | null;
  readonly restOpen: boolean;
  readonly state: RankingState | undefined;
  readonly table: TableView | null;
  readonly onToggle: () => void;
  readonly onPickMetric: (metric: CellMetric) => void;
  readonly onPickDirection: (direction: Direction) => void;
  readonly onToggleRow: (id: string) => void;
  readonly onToggleRest: () => void;
  readonly onRetry: () => void;
  readonly onTaggedProduct: (productId: string) => void;
  readonly taggedHref: (productId: string) => string;
  /** P15: extra content under an open content row's facts ("Phân tích video"). */
  readonly renderRowDetail?: (row: RowView) => React.ReactNode;
}

function Chip({ tone, text, className = "pa-delta" }: { readonly tone: string; readonly text: string; readonly className?: string }) {
  return <span className={`${className} pa-delta--${tone}`}>{text}</span>;
}

function Cell({
  cell,
  on,
  onPick,
  streamLabel,
}: {
  readonly cell: CellView;
  readonly on: boolean;
  readonly onPick: () => void;
  readonly streamLabel: string;
}) {
  const state = cell.grey ? "grey" : !cell.clickable ? "fixed" : on ? "on" : cell.weak ? "weak" : "plain";
  return (
    <button
      aria-label={`${cell.label} · ${streamLabel}: ${cell.value}, ${cell.delta.text}, ${cell.before}, ${cell.impact}`}
      aria-pressed={cell.clickable ? on : undefined}
      className={`pa-cell pa-cell--${state}`}
      data-metric={cell.metric}
      disabled={!cell.clickable}
      onClick={cell.clickable ? onPick : undefined}
      type="button"
    >
      <span className="pa-cell__top">
        <span className="pa-cell__label">{cell.label}</span>
        {cell.weak ? <span className="pa-cell__flag">✦ Juli gợi ý</span> : null}
      </span>
      <span className="pa-cell__line">
        <span className="pa-cell__value">{cell.value}</span>
        <Chip className="pa-delta pa-cell__delta" text={cell.delta.text} tone={cell.delta.tone} />
      </span>
      <span className={`pa-cell__impact pa-impact--${cell.impactTone}`}>{cell.impact}</span>
      <span aria-hidden="true" className="pa-cell__before">
        {cell.before}
      </span>
    </button>
  );
}

function Confidence({ value }: { readonly value: RowView["confidence"] }) {
  if (!value) return <span />;
  return <span className={`pa-conf pa-conf--${value === "Rõ" ? "clear" : "ref"}`}>{value}</span>;
}

function Bar({ row }: { readonly row: RowView }) {
  return (
    <span className="pa-bar">
      <span className={`pa-bar__fill pa-bar__fill--${row.negative ? "down" : "up"}`} style={{ width: `${row.width}%` }} />
    </span>
  );
}

function Facts({ row, mobile, content }: { readonly row: RowView; readonly mobile: boolean; readonly content: boolean }) {
  return (
    <div className={`pa-facts${mobile ? " pa-facts--mobile" : ""}${content ? " pa-facts--content" : ""}`}>
      {row.facts.map((fact) => (
        <div className="pa-fact" key={fact.k}>
          <span className="pa-fact__k">{fact.k}</span>
          <span className="pa-fact__v">{fact.v}</span>
        </div>
      ))}
    </div>
  );
}

function CardLink({ row, mobile }: { readonly row: RowView; readonly mobile: boolean }) {
  if (row.card) {
    return (
      <Link className="pa-row__link" href={decisionCardHref(row.card.id)}>
        Xem đề xuất ›
      </Link>
    );
  }
  return <span className={`pa-row__none${mobile ? " pa-row__none--mobile" : ""}`}>Chưa có đề xuất</span>;
}

function Thumb() {
  return (
    <span aria-hidden="true" className="pa-thumb">
      <svg fill="none" height="16" stroke="currentColor" strokeLinejoin="round" strokeWidth="1.6" viewBox="0 0 16 16" width="16">
        <path d="M5 3.5v9l7-4.5z" />
      </svg>
    </span>
  );
}

function TaggedLink({ row, href, onOpen }: { readonly row: RowView; readonly href: (id: string) => string; readonly onOpen: (id: string) => void }) {
  if (!row.taggedProduct) return <span />;
  const productId = row.taggedProduct;
  return (
    <a
      className="pa-row__link"
      href={href(productId)}
      onClick={(event) => {
        event.preventDefault();
        onOpen(productId);
      }}
    >
      Xem sản phẩm được gắn ›
    </a>
  );
}

function DesktopRow({ row, open, content, props }: { readonly row: RowView; readonly open: boolean; readonly content: boolean; readonly props: StreamCardProps }) {
  return (
    <div className={`pa-row${open ? " pa-row--open" : ""}`} data-testid="pa-row" id={`pa-row-${row.id}`}>
      <div className={`pa-row__grid${content ? " pa-row__grid--content" : ""}`}>
        <button aria-expanded={open} className="pa-row__toggle" onClick={() => props.onToggleRow(row.id)} type="button">
          <span aria-hidden="true" className="pa-caret">
            {open ? "▾" : "▸"}
          </span>
          {content ? (
            <>
              <Thumb />
              <span className="pa-row__titles">
                <span className="pa-row__name">{row.name}</span>
                {row.meta ? <span className="pa-row__meta">{row.meta}</span> : null}
              </span>
            </>
          ) : (
            <>
              {row.sku ? <span className="pa-sku">{row.sku}</span> : null}
              <span className="pa-row__name">{row.name}</span>
            </>
          )}
        </button>
        <span className="pa-row__values">
          {row.before} → <b>{row.now}</b>
        </span>
        <span className="pa-row__gmv">
          <Bar row={row} />
          <b className={content ? "pa-row__money pa-row__money--content" : "pa-row__money"}>{row.gmv}</b>
        </span>
        <Confidence value={row.confidence} />
        <span className="pa-row__end">
          {content ? <TaggedLink href={props.taggedHref} onOpen={props.onTaggedProduct} row={row} /> : <CardLink mobile={false} row={row} />}
        </span>
      </div>
      {open ? <Facts content={content} mobile={false} row={row} /> : null}
      {open && content && props.renderRowDetail ? props.renderRowDetail(row) : null}
    </div>
  );
}

function MobileRow({ row, open, content, props }: { readonly row: RowView; readonly open: boolean; readonly content: boolean; readonly props: StreamCardProps }) {
  return (
    <div className={`pa-mrow${open ? " pa-row--open" : ""}`} data-testid="pa-row" id={`pa-row-${row.id}`}>
      <button aria-expanded={open} className="pa-mrow__toggle" onClick={() => props.onToggleRow(row.id)} type="button">
        <span className="pa-mrow__head">
          {row.sku ? <span className="pa-sku">{row.sku}</span> : null}
          <span className="pa-row__name">{row.name}</span>
          <span aria-hidden="true" className="pa-mrow__caret">
            {open ? "▾" : "▸"}
          </span>
        </span>
        {content && row.meta ? <span className="pa-row__meta">{row.meta}</span> : null}
        <span className="pa-mrow__line">
          <span>
            {row.before} → <b>{row.now}</b>
          </span>
          <Bar row={row} />
          <b>{row.gmv}</b>
        </span>
      </button>
      {open ? <Facts content={content} mobile row={row} /> : null}
      {open && content && props.renderRowDetail ? props.renderRowDetail(row) : null}
      <div className="pa-mrow__foot">
        <Confidence value={row.confidence} />
        {content ? <TaggedLink href={props.taggedHref} onOpen={props.onTaggedProduct} row={row} /> : <CardLink mobile row={row} />}
      </div>
    </div>
  );
}

function Ranking(props: StreamCardProps) {
  const { view, state, table, direction, narrow, restOpen, row } = props;
  const content = view.spec.rowKind !== "product";
  const restId = useId();
  if (!state || state.status === "loading") {
    return (
      <p aria-live="polite" className="pa-status" role="status">
        Đang tải bảng xếp hạng…
      </p>
    );
  }
  if (state.status === "empty") {
    return (
      <p className="pa-status" role="status">
        Chưa có bảng xếp hạng cho chỉ số này
      </p>
    );
  }
  if (state.status === "error" || !table) {
    return (
      <div className="pa-status" role="alert">
        <p>Không tải được bảng xếp hạng. Vui lòng thử lại.</p>
        <button className="qv-btn qv-btn--secondary" onClick={props.onRetry} type="button">
          Thử lại
        </button>
      </div>
    );
  }
  return (
    <div className="pa-table" data-testid="ranking-table">
      <div className="pa-table__head">
        <h3 className="pa-table__title">{table.title}</h3>
        {content ? null : (
          <div aria-label="Chiều xếp hạng" className="pa-dir" role="group">
            {(["down", "up"] as const).map((d) => (
              <button aria-pressed={direction === d} className="pa-dir__btn" key={d} onClick={() => props.onPickDirection(d)} type="button">
                {d === "down" ? "Kéo xuống" : "Kéo lên"}
              </button>
            ))}
          </div>
        )}
      </div>
      {!content && !narrow ? (
        <div aria-hidden="true" className="pa-row__grid pa-cols">
          <span>Sản phẩm</span>
          <span>{table.col} · trước → nay</span>
          <span>GMV/ngày</span>
          <span>Tin cậy</span>
          <span />
        </div>
      ) : null}
      {table.rows.length === 0 ? (
        <p className="pa-status">Không có {content ? "dòng" : "sản phẩm"} nào {direction === "down" || content ? "kéo xuống" : "kéo lên"} rõ rệt.</p>
      ) : null}
      {table.rows.map((r) =>
        narrow ? (
          <MobileRow content={content} key={r.id} open={row === r.id} props={props} row={r} />
        ) : (
          <DesktopRow content={content} key={r.id} open={row === r.id} props={props} row={r} />
        ),
      )}
      {content ? (
        <div className="pa-total">
          <span className="pa-total__label">Còn lại · {table.restLabel}</span>
          <b>{table.restSum}</b>
        </div>
      ) : (
        <>
          <div className="pa-rest">
            <button aria-controls={restId} aria-expanded={restOpen} className="pa-rest__toggle" onClick={props.onToggleRest} type="button">
              <span aria-hidden="true" className="pa-rest__caret">
                {restOpen ? "▾" : "▸"}
              </span>
              <span>Còn lại · {table.rest.length} dòng</span>
              <b className="pa-rest__sum">{table.restSum}</b>
            </button>
            {restOpen ? (
              <div className="pa-rest__list" id={restId}>
                {table.rest.map((line) => (
                  <div className="pa-rest__line" key={line.k}>
                    <span>{line.k}</span>
                    <b>{line.v}</b>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
          <div className="pa-total" data-testid="ranking-total">
            <span className="pa-total__label">{narrow ? "Tổng" : `Tổng · bằng số của ô ${table.col}`}</span>
            <b>{table.total}</b>
          </div>
        </>
      )}
    </div>
  );
}

export function StreamCard(props: StreamCardProps) {
  const { view, open, narrow, metric } = props;
  const titleId = useId();
  const cells = narrow ? view.cells.filter((c) => c.metric !== "gmv") : view.cells;
  return (
    <section aria-labelledby={titleId} className={`pa-stream${narrow ? " pa-stream--mobile" : ""}`} data-stream={view.spec.slug} data-testid="pa-stream">
      <div className="pa-stream__head">
        <h2 className="pa-stream__name" id={titleId}>
          {view.spec.label}
        </h2>
        <span className="pa-stream__gmv">{narrow ? view.gmvShort : view.gmvText}</span>
        <Chip text={view.delta.text} tone={view.delta.tone} />
        {!open && view.weakText && !narrow ? <span className="pa-weak">{view.weakText}</span> : null}
        <button aria-expanded={open} className="pa-stream__toggle" onClick={props.onToggle} type="button">
          {open ? "Thu gọn" : "Mở"}
        </button>
        {!open && view.weakText && narrow ? <span className="pa-weak pa-weak--mobile">{view.weakText}</span> : null}
      </div>
      {open ? (
        <div className="pa-stream__body">
          {view.present ? (
            <>
              <div className="pa-cells">
                {cells.map((cell) => (
                  <Cell
                    cell={cell}
                    key={cell.metric}
                    on={cell.metric === metric}
                    onPick={() => props.onPickMetric(cell.metric as CellMetric)}
                    streamLabel={view.spec.label}
                  />
                ))}
              </div>
              <Ranking {...props} />
            </>
          ) : (
            <p className="pa-status" role="status">
              Chưa có số liệu cho luồng này trong 60 ngày.
            </p>
          )}
        </div>
      ) : null}
    </section>
  );
}
