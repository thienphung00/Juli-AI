import type { ReactNode } from "react";

import { addToCartRate, aov, ctor, ctr, NO_DATA } from "../../lib/shop-analysis/derive";
import type { ChannelRow, Counts } from "../../lib/shop-analysis/types";
import {
  DEPENDS_ON_PRODUCT,
  formatMetric,
  isClickable,
  METRIC_NAMES,
  ordersPerCart,
  type Bottleneck,
  type Cell,
  type StreamSpec,
} from "../../lib/phan-tich/model";
import type { RankedMetric } from "../../lib/phan-tich/types";
import { change, compactMoney, num, pct } from "../../lib/vn-format";

/**
 * One funnel row per traffic stream, as the sales demo video draws it
 * (ADR-109 d.2): Lượt hiển thị sản phẩm → CTR → lượt bấm → [Thêm giỏ/bấm →
 * Thêm giỏ → Đơn/thêm giỏ] → Đơn → AOV → GMV/ngày, each tile "trước X ▲/▼ %"
 * (daily averages, last 30 vs prior 30 days). Clickable cells (d.4) are
 * buttons that re-rank the table; the bottleneck is outlined pink with the
 * "✦ Juli gợi ý" strip under the row.
 */

const ARROW = { up: "▲", down: "▼", flat: "" } as const;

function Pill({ prior, last }: { readonly prior: number | null; readonly last: number | null }) {
  const delta = change(prior, last);
  if (delta.text === "—") return null;
  return (
    <span className={`change-pill change-pill--${delta.tone}`}>
      {ARROW[delta.tone]} {delta.text.replace(/^[+−]/, "")}
    </span>
  );
}

interface TileProps {
  readonly label: string;
  readonly prior: number | null;
  readonly last: number | null;
  readonly format: (value: number | null) => string;
  readonly note?: string;
  /** Set → the tile is a button that selects this cell. */
  readonly metric?: RankedMetric;
  readonly selected?: boolean;
  readonly bottleneck?: boolean;
  readonly onSelect?: (metric: RankedMetric) => void;
  readonly streamLabel: string;
  readonly className?: string;
}

function TileBody({ label, prior, last, format, note, bottleneck }: TileProps) {
  return (
    <>
      {bottleneck ? (
        <span className="pt-tile__tag" aria-hidden="true">
          ✦ Juli gợi ý tối ưu
        </span>
      ) : null}
      <span className="pt-tile__label">{label}</span>
      <b className="pt-tile__value num">{format(last)}</b>
      <span className="pt-tile__prior num">
        trước {format(prior)} <Pill last={last} prior={prior} />
      </span>
      {note ? <span className="pt-tile__note">{note}</span> : null}
    </>
  );
}

function Tile(props: TileProps) {
  const { metric, selected, bottleneck, onSelect, streamLabel, label, className = "" } = props;
  const classes = [
    "pt-tile",
    metric ? "pt-tile--clickable" : "",
    selected ? "pt-tile--selected" : "",
    bottleneck ? "pt-tile--bottleneck" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");
  if (metric && onSelect) {
    return (
      <button
        aria-label={`${label} · ${streamLabel}: ${props.format(props.last)}, trước ${props.format(props.prior)}. Xếp hạng theo chỉ số này`}
        aria-pressed={Boolean(selected)}
        className={classes}
        data-metric={metric}
        onClick={() => onSelect(metric)}
        type="button"
      >
        <TileBody {...props} />
      </button>
    );
  }
  return (
    <div className={classes} data-metric-static={label}>
      <TileBody {...props} />
    </div>
  );
}

function Arrow() {
  return (
    <span aria-hidden="true" className="pt-flow__arrow">
      →
    </span>
  );
}

export interface StreamFunnelProps {
  readonly spec: StreamSpec;
  readonly row: ChannelRow | undefined;
  readonly selected: Cell | null;
  readonly bottleneck: Bottleneck | null;
  readonly suggestion: string | null;
  readonly onSelect: (cell: Cell) => void;
}

export function StreamFunnel({ spec, row, selected, bottleneck, suggestion, onSelect }: StreamFunnelProps) {
  const isHere = bottleneck?.stream === spec.stream;
  const titleId = `pt-stream-${spec.slug}`;
  if (!row) {
    return (
      <article aria-labelledby={titleId} className="card pt-stream" data-stream={spec.stream}>
        <div className="pt-stream__head">
          <h2 className="pt-stream__name" id={titleId}>
            {spec.label}
          </h2>
          <p className="pt-stream__sub">{spec.sub}</p>
        </div>
        <p className="pt-stream__missing">{NO_DATA}</p>
      </article>
    );
  }

  const p: Counts = row.comparison.prior;
  const q: Counts = row.comparison.last;
  const select = (metric: RankedMetric) => onSelect({ stream: spec.stream, metric });
  const tile = (metric: RankedMetric) => ({
    metric: isClickable(spec.stream, metric) ? metric : undefined,
    selected: selected?.stream === spec.stream && selected.metric === metric,
    bottleneck: isHere && bottleneck?.metric === metric,
    onSelect: select,
    streamLabel: spec.label,
  });
  const isContent = spec.rowKind !== "product";
  const lockedNote = (metric: RankedMetric) =>
    isContent && !isClickable(spec.stream, metric) ? DEPENDS_ON_PRODUCT : undefined;
  const hasCart = p.add_to_cart !== null && q.add_to_cart !== null && spec.stream === "product_card";
  const estimated = Boolean(q.orders_estimated || p.orders_estimated);
  const money = (v: number | null) => compactMoney(v);

  let ctorBlock: ReactNode;
  if (hasCart) {
    const ctorTile = tile("ctor");
    ctorBlock = (
      <div
        className={[
          "pt-ctor",
          ctorTile.selected ? "pt-ctor--selected" : "",
          ctorTile.bottleneck ? "pt-ctor--bottleneck" : "",
        ]
          .filter(Boolean)
          .join(" ")}
        role="group"
        aria-label={`CTOR và hai bước của nó · ${spec.label}`}
      >
        <Tile format={(v) => pct(v)} label="CTOR" last={ctor(q)} prior={ctor(p)} {...ctorTile} className="pt-tile--ctor-main" />
        <div className="pt-ctor__steps">
          <Tile
            format={(v) => pct(v)}
            label={METRIC_NAMES.add_to_cart_rate}
            last={addToCartRate(q)}
            prior={addToCartRate(p)}
            {...tile("add_to_cart_rate")}
          />
          <Tile
            format={(v) => num(v)}
            label="Thêm giỏ/ngày"
            last={q.add_to_cart}
            prior={p.add_to_cart}
            streamLabel={spec.label}
          />
          <Tile
            format={(v) => pct(v)}
            label={METRIC_NAMES.orders_per_cart}
            last={ordersPerCart(q)}
            prior={ordersPerCart(p)}
            {...tile("orders_per_cart")}
          />
        </div>
      </div>
    );
  } else {
    ctorBlock = (
      <Tile
        format={(v) => pct(v)}
        label={isContent ? "CTOR · gồm mua ngay" : "CTOR"}
        last={ctor(q)}
        note={lockedNote("ctor") ?? (estimated ? "ước tính" : undefined)}
        prior={ctor(p)}
        {...tile("ctor")}
      />
    );
  }

  return (
    <article
      aria-labelledby={titleId}
      className={`card pt-stream${isHere ? " pt-stream--focus" : ""}`}
      data-stream={spec.stream}
    >
      <div className="pt-stream__head">
        <h2 className="pt-stream__name" id={titleId}>
          {spec.label}
        </h2>
        <p className="pt-stream__sub">{spec.sub}</p>
      </div>
      <div className="pt-flow">
        <Tile
          format={(v) => num(v, 0)}
          label="Hiển thị/ngày"
          last={q.impressions}
          prior={p.impressions}
          {...tile("impressions")}
        />
        <Arrow />
        <Tile format={(v) => pct(v)} label="CTR" last={ctr(q)} prior={ctr(p)} {...tile("ctr")} />
        <Arrow />
        <Tile format={(v) => num(v)} label="Bấm/ngày" last={q.clicks} prior={p.clicks} streamLabel={spec.label} />
        <Arrow />
        {ctorBlock}
        <Arrow />
        <Tile
          format={(v) => num(v)}
          label="Đơn/ngày"
          last={q.sku_orders}
          note={estimated ? "ước tính" : undefined}
          prior={p.sku_orders}
          streamLabel={spec.label}
        />
        <Arrow />
        <Tile format={money} label="AOV" last={aov(q)} note={lockedNote("aov")} prior={aov(p)} {...tile("aov")} />
        <Arrow />
        <Tile format={money} label="GMV/ngày" last={q.gmv} prior={p.gmv} streamLabel={spec.label} />
      </div>
      {hasCart ? (
        <p className="pt-stream__formula num">
          CTOR (đơn/bấm) = Thêm giỏ/bấm × Đơn/thêm giỏ: {formatMetric("ctor", ctor(p))} →{" "}
          <b>{formatMetric("ctor", ctor(q))}</b> <Pill last={ctor(q)} prior={ctor(p)} />
        </p>
      ) : null}
      {isHere && suggestion ? (
        <p className="pt-suggest" data-testid="juli-suggestion">
          <span aria-hidden="true" className="pt-suggest__spark">
            ✦
          </span>
          <b>Juli gợi ý:</b> <span>{suggestion}</span>
        </p>
      ) : null}
    </article>
  );
}
