"use client";

import Link from "next/link";
import { useMemo } from "react";

import { useShopee } from "../../lib/shopee-analytics/context";
import { fmt, pp, vnd } from "../../lib/shopee-analytics/format";
import { readWindow, windowParams, type WindowState } from "../../lib/shopee-analytics/params";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import type { Matrix } from "../../lib/shopee-analytics/types";
import { PeriodBar } from "./period-bar";
import { Empty, Ini, PageHead, ResourceState, Section, initialsOf } from "./ui";

/** Sản phẩm (the nav entry): the shop's products by GMV, each opening its product page. */
export function ProductListView({ params }: { readonly params: URLSearchParams }) {
  const host = useShopee();
  const state = useMemo(() => readWindow(params), [params]);
  const key = `${host.shopKey}|pl|${JSON.stringify(state.query)}`;
  const data = useResource(() => host.api.matrix({ ...state.query, sort: "gmv" }), key);
  return (
    <div className="sa-page" data-testid="sa-product-list">
      <PageHead eyebrow="SẢN PHẨM" title="Sản phẩm của shop" />
      <ResourceState resource={data}>{(m) => <List matrix={m} state={state} />}</ResourceState>
    </div>
  );
}

function List({ matrix, state }: { readonly matrix: Matrix; readonly state: WindowState }) {
  const { links } = useShopee();
  return (
    <>
      <PeriodBar
        hrefFor={(next) => links.screen("san-pham", windowParams(next))}
        previous={null}
        state={state}
        window={matrix.window}
      />
      <Section hint={`${matrix.product_count} sản phẩm · xếp theo GMV`} testId="sa-product-rows" title="Danh sách sản phẩm">
        {matrix.products.length === 0 ? (
          <Empty testId="sa-product-empty">Chưa có sản phẩm nào có đơn trong kỳ này.</Empty>
        ) : (
          matrix.products.map((p) => (
            <Link className="sa-plist" href={links.product(p.product_id, { tab: "hs", from: "san-pham" }, state)} key={p.product_id}>
              <Ini text={initialsOf(p.name)} />
              <span>
                <span className="sa-mname__t">{p.name}</span>
                <span className="sa-hint sa-block">{p.product_id}</span>
              </span>
              <span>
                <span className="sa-fcell__label">GMV</span>
                <b>{vnd(p.gmv)}</b>
              </span>
              <span>
                <span className="sa-fcell__label">Đơn</span>
                <b>{fmt(p.orders)}</b>
              </span>
              <span>
                <span className="sa-fcell__label">Biên cuối</span>
                <b>{pp(p.profit?.margin_pct, 1)}</b>
              </span>
            </Link>
          ))
        )}
      </Section>
    </>
  );
}
