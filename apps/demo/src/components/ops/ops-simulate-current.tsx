"use client";

import Link from "next/link";

import { useCurrentShop } from "../../lib/ops/current-shop";
import type { OpsMe } from "../../lib/ops/types";
import { OpsSimulate } from "./ops-simulate";
import { C, OpsHeader, OpsPage, card } from "./ops-shell";
import { OpsSkeleton } from "./ops-skeleton";

/**
 * Main-nav "Mô phỏng" (D27.8): opens the shop last chosen in Tổng quan, in place.
 * Shops are chosen and searched only in Tổng quan; no shop list here.
 */
export function OpsSimulateCurrent({ me, api }: { readonly me: OpsMe; readonly api?: Parameters<typeof OpsSimulate>[0]["api"] }) {
  const shop = useCurrentShop();
  if (shop) return <OpsSimulate api={api} key={shop.id} me={me} shopId={shop.id} />;
  return (
    <OpsPage>
      <OpsHeader active="simulate" me={me} />
      <main style={{ padding: "22px 28px", display: "flex", flexDirection: "column", gap: 16 }}>
        <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700 }}>Mô phỏng</h1>
        {shop === undefined ? (
          <OpsSkeleton rows={3} variant="cards" />
        ) : (
          <div data-testid="simulate-no-shop" style={{ ...card, maxWidth: 520 }}>
            <span style={{ fontSize: 14, color: C.body }}>Chưa chọn shop nào.</span>
            <Link href="/ops" style={{ fontSize: 14, fontWeight: 600, textDecoration: "none", color: C.pink }}>
              Chọn một shop ở Tổng quan ›
            </Link>
          </div>
        )}
      </main>
    </OpsPage>
  );
}
