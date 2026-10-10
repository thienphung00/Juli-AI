"use client";

import { useId, useState, type ReactNode } from "react";

import type { CalendarView, PromoView } from "../../lib/phan-tich/extras";

/**
 * "Khuyến mãi" and "Lịch sale và chiến dịch" (ADR-109 Amendment 2 d.5,
 * PtProduct; PtMobile's compact lists below 768 px) — collapsed until "Xem thêm".
 */

function Collapsible({
  title,
  lede,
  testId,
  children,
}: {
  readonly title: string;
  readonly lede: string;
  readonly testId: string;
  readonly children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const titleId = useId();
  const bodyId = useId();
  return (
    <section aria-labelledby={titleId} className="pa-more" data-testid={testId}>
      <div className="pa-more__head">
        <h2 className="pa-more__title" id={titleId}>
          {title}
        </h2>
        <span className="pa-more__lede">{lede}</span>
        <button aria-controls={bodyId} aria-expanded={open} className="pa-stream__toggle" onClick={() => setOpen((v) => !v)} type="button">
          {open ? "Thu gọn" : "Xem thêm"}
        </button>
      </div>
      {open ? (
        <div className="pa-more__body" id={bodyId}>
          {children}
        </div>
      ) : null}
    </section>
  );
}

export function PromoSection({ promo }: { readonly promo: PromoView }) {
  return (
    <Collapsible lede="Flash sale, giảm giá, voucher · 60 ngày" testId="more-khuyen-mai" title="Khuyến mãi">
      <div className="pa-promo__stats">
        {promo.stats.map((stat) => (
          <div className="pa-promo__stat" key={stat.k}>
            <span className="pa-promo__k">{stat.k}</span>
            <span className="pa-promo__v">{stat.v}</span>
            <span className="pa-promo__sub">{stat.sub}</span>
          </div>
        ))}
      </div>
      {promo.rows.length > 0 ? (
        <>
          <div aria-hidden="true" className="pa-promo__grid pa-promo__cols">
            <span>Sản phẩm</span>
            <span>Loại</span>
            <span>Giảm thật</span>
            <span>GMV/ngày trong · ngoài</span>
          </div>
          {promo.rows.map((row) => (
            <div className="pa-promo__grid pa-promo__row" key={row.productId}>
              <span className="pa-promo__product">
                {row.sku ? <span className="pa-sku">{row.sku}</span> : null}
                <b>{row.name}</b>
              </span>
              <span>{row.kind}</span>
              <span className={row.shallow ? "pa-promo__depth--shallow" : undefined}>{row.depth}</span>
              <span>{row.gmv}</span>
            </div>
          ))}
        </>
      ) : (
        <p className="pa-status">Chưa có sản phẩm nào chạy flash sale, giảm giá hay mua nhiều giảm nhiều trong 60 ngày.</p>
      )}
    </Collapsible>
  );
}

export function CalendarSection({ calendar }: { readonly calendar: CalendarView | null }) {
  return (
    <Collapsible lede="GMV mỗi ngày cùng ngày sale · 60 ngày" testId="more-lich-sale" title="Lịch sale và chiến dịch">
      {calendar ? (
        <>
          <div className="pa-cal__legend">
            <span>
              <i className="pa-cal__swatch pa-cal__swatch--normal" />
              GMV/ngày
            </span>
            <span>
              <i className="pa-cal__swatch pa-cal__swatch--flash" />
              Ngày flash sale của shop
            </span>
            <span>
              <i className="pa-cal__swatch pa-cal__swatch--platform" />
              Ngày sale của TikTok{calendar.saleNames ? ` (${calendar.saleNames})` : ""}
            </span>
          </div>
          <div aria-label="GMV mỗi ngày trong 60 ngày" className="pa-cal__bars" role="img">
            {calendar.bars.map((bar) => (
              <span className={`pa-cal__bar pa-cal__bar--${bar.kind}`} key={bar.day} style={{ height: `${bar.height}%` }} />
            ))}
          </div>
          <div className="pa-cal__axis">
            <span>{calendar.first}</span>
            <span>{calendar.middle}</span>
            <span>{calendar.last}</span>
          </div>
          {calendar.tiles.length > 0 ? (
            <div className="pa-cal__tiles">
              {calendar.tiles.map((tile) => (
                <div className="pa-cal__tile" key={tile.title}>
                  <b>{tile.title}</b> · {tile.text}
                </div>
              ))}
            </div>
          ) : null}
        </>
      ) : (
        <p className="pa-status">Báo cáo này chưa có GMV từng ngày. Lịch sale sẽ có từ lần cập nhật tới.</p>
      )}
    </Collapsible>
  );
}

function MobileExtra({ title, items, testId }: { readonly title: string; readonly items: ReadonlyArray<{ k: string; v: string }>; readonly testId: string }) {
  const [open, setOpen] = useState(false);
  const titleId = useId();
  return (
    <section aria-labelledby={titleId} className="pa-more pa-more--mobile" data-testid={testId}>
      <div className="pa-more__head">
        <h2 className="pa-more__title" id={titleId}>
          {title}
        </h2>
        <button aria-expanded={open} className="pa-stream__toggle" onClick={() => setOpen((v) => !v)} type="button">
          {open ? "Thu gọn" : "Xem thêm"}
        </button>
      </div>
      {open ? (
        <div className="pa-more__items">
          {items.map((item) => (
            <div className="pa-more__item" key={item.k}>
              <span>{item.k}</span>
              <b>{item.v}</b>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

export function MobileExtras({ promo, calendar }: { readonly promo: PromoView; readonly calendar: CalendarView | null }) {
  const [flash, depth, voucher] = promo.stats;
  const promoItems = [
    { k: flash.k, v: `${flash.v} · ${flash.sub.replace(" tham gia", "")}` },
    { k: depth.k, v: depth.v },
    { k: voucher.k, v: voucher.v },
  ];
  const calendarItems = (calendar?.tiles ?? []).map((tile) => ({ k: tile.title, v: tile.text }));
  return (
    <>
      <MobileExtra items={promoItems} testId="more-khuyen-mai" title="Khuyến mãi" />
      <MobileExtra
        items={calendarItems.length > 0 ? calendarItems : [{ k: "Lịch sale", v: "Chưa có dữ liệu" }]}
        testId="more-lich-sale"
        title="Lịch sale và chiến dịch"
      />
    </>
  );
}
