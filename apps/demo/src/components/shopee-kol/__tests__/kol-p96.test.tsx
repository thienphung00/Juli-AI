import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { fakeApi, product, critical } from "../../../lib/shopee-analytics/__tests__/fixtures";
import { ShopeeHostProvider, type ShopeeHost } from "../../../lib/shopee-analytics/context";
import { sellerLinks } from "../../../lib/shopee-analytics/links";
import { fakeKol, row } from "../../../lib/shopee-kol/__tests__/fixtures";
import { rowText } from "../../../lib/shopee-kol/model";
import { KolView } from "../kol-view";

function host(over: Partial<ShopeeHost> = {}): ShopeeHost {
  return { api: fakeApi({ product: product(), critical: critical() }), kol: fakeKol(), links: sellerLinks, shopKey: "shop-1", shopName: "Shop gia dụng", ...over };
}

describe("KOL tab from Juli Connector (P96, 2026-11-06)", () => {
  it("shows the creator's buyers next to clicks and conversion", async () => {
    const r = row({ kol_key: "kb", kol_clicks: 310, kol_buyers: 47 });
    expect(rowText(r).buyers).toBe("47");
    expect(rowText(row({ kol_buyers: null })).buyers).toBe("—");
    render(
      <ShopeeHostProvider host={host({ kol: fakeKol([r]) })}>
        <KolView />
      </ShopeeHostProvider>,
    );
    expect(await screen.findByRole("columnheader", { name: "Người mua của KOL" })).toBeInTheDocument();
    expect(within(screen.getByTestId(`kol-row-kb-${r.item_id}`)).getByText("47")).toBeInTheDocument();
  });

  it("the empty table says the rows come from Juli Connector, not a file upload", async () => {
    render(
      <ShopeeHostProvider host={host({ kol: fakeKol([]) })}>
        <KolView />
      </ShopeeHostProvider>,
    );
    const empty = await screen.findByTestId("kol-empty");
    expect(empty).toHaveTextContent("Juli Connector");
    expect(empty).toHaveTextContent("báo cáo chuyển đổi");
    expect(empty).not.toHaveTextContent("chưa đọc báo cáo này");
  });
});
