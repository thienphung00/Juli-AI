"use client";

import Link from "next/link";
import { useEffect, useId, useState } from "react";

import { useShopee } from "../../lib/shopee-analytics/context";
import { stockText, variationText, type StockList, type StockRow } from "../../lib/shopee-analytics/stock";
import { Section } from "./ui";

/**
 * Sản phẩm (owner 2026-11-15), P100 Part S: one row per variation -- the variation (· SKU code),
 * "Còn 42 · hết khoảng 22/11" and the "Theo dõi" switch. Switching off asks first. Shown only where
 * the host has the stock API (the seller app; never Ops or the reviewer's sample shop). On a product
 * page: that product's variations. On the Sản phẩm list, `keys` (the e-mail's `ton_kho` link) lists
 * exactly those variations, each product name opening its product page.
 */
export function StockPanel({ productId, keys }: { readonly productId: string | null; readonly keys: readonly string[] }) {
  const { stock, links } = useShopee();
  const [list, setList] = useState<StockList | null>(null);
  const [failed, setFailed] = useState(false);
  const [asking, setAsking] = useState<StockRow | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    if (!stock) return;
    let live = true;
    stock.list().then(
      (data) => live && setList(data),
      () => live && setFailed(true),
    );
    return () => {
      live = false;
    };
  }, [stock]);

  if (!stock || failed || !list || !list.enabled) return null;
  const rows = keys.length ? list.rows.filter((r) => keys.includes(r.key)) : list.rows.filter((r) => r.item_id === productId);
  if (!rows.length) return null;

  const apply = (row: StockRow, tracked: boolean) => {
    setBusy(row.key);
    stock.setTracked(row.key, tracked).then(
      (got) => {
        setList((cur) => (cur ? { ...cur, rows: cur.rows.map((r) => (r.key === row.key ? { ...r, tracked: got.tracked } : r)) } : cur));
        setBusy(null);
      },
      () => setBusy(null),
    );
  };

  return (
    <Section testId="sa-stock-alert" title="Theo dõi tồn kho">
      <ul className="sa-stock__rows">
        {rows.map((row) => (
          <li className="sa-stock__row" data-testid={`sa-stock-${row.key}`} key={row.key}>
            <span className="sa-stock__name">
              {keys.length ? (
                <Link className="sa-stock__product sa-link" href={links.product(row.item_id, { tab: "hs", from: "san-pham" })}>
                  {row.product_name}
                </Link>
              ) : null}
              <span>{variationText(row)}</span>
            </span>
            <span className={`sa-stock__left${row.out_of_stock || row.soon ? " sa-stock__left--soon" : ""}`} data-testid={`sa-stock-left-${row.key}`}>
              {stockText(row)}
            </span>
            <button
              aria-checked={row.tracked}
              className={`sa-tq__switch sa-stock__switch${row.tracked ? " sa-tq__switch--on" : ""}`}
              data-testid={`sa-stock-track-${row.key}`}
              disabled={busy === row.key}
              onClick={() => (row.tracked ? setAsking(row) : apply(row, true))}
              role="switch"
              type="button"
            >
              <span aria-hidden="true" className="sa-tq__knob" />
              Theo dõi
            </button>
          </li>
        ))}
      </ul>
      {asking ? (
        <StopDialog
          onCancel={() => setAsking(null)}
          onConfirm={() => {
            const row = asking;
            setAsking(null);
            apply(row, false);
          }}
        />
      ) : null}
    </Section>
  );
}

export const STOP_TITLE = "Ngừng theo dõi SKU này?";
export const STOP_BODY = "Juli sẽ không gửi cảnh báo tồn kho và không tạo đề xuất cho SKU này.";

function StopDialog({ onCancel, onConfirm }: { readonly onCancel: () => void; readonly onConfirm: () => void }) {
  const id = useId();
  return (
    <div className="qv-overlay" data-testid="sa-stock-confirm">
      <div aria-labelledby={`${id}-t`} aria-modal="true" className="qv-dialog" role="alertdialog">
        <h3 className="qv-dialog__title" id={`${id}-t`}>
          {STOP_TITLE}
        </h3>
        <p className="qv-dialog__body">{STOP_BODY}</p>
        <div className="qv-dialog__actions">
          <button className="qv-btn qv-btn--secondary" onClick={onCancel} type="button">
            Huỷ
          </button>
          <button className="qv-btn qv-btn--primary" onClick={onConfirm} type="button">
            Ngừng theo dõi
          </button>
        </div>
      </div>
    </div>
  );
}
